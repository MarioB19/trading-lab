"""Integridad con datos sintéticos offline; no mide nuevas estrategias de mercado."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest
import yaml

from lab import research_multi
from lab.experiments import (ExperimentRun, ResearchGateError, append_event, canonical_hash,
                             file_hash, promotion_gate, verify_preregistration)
from lab.portfolio import PortfolioParams, listed_universe, simulate_portfolio, target_weights
from lab.validation import finite_randomization_pvalue


def _walk_fixture():
    idx = pd.date_range("2019-01-01", "2021-01-05", freq="D")
    prices = pd.DataFrame(100., index=idx, columns=["A"])
    prices.loc["2020-01-02":, "A"] = 80.
    prices.loc["2020-01-03":, "A"] = 64.
    prices.loc["2020-12-30":, "A"] = 50.
    weights = pd.DataFrame(1., index=idx, columns=["A"])
    noise = np.where(np.arange(len(idx)) % 2, .001, -.001)
    runs = {}
    for key, sign, brake in (("sin_freno", 1, False), ("con_freno", -1, True)):
        ret = pd.Series(sign * np.where(idx.year == 2019, .01, -.03) + noise, index=idx)
        runs[key] = {"W": weights, "params": PortfolioParams(dd_brake=brake),
                     "bt": pd.DataFrame({"ret": ret})}
    return prices, runs


def test_walk_forward_future_selection_cannot_rewrite_history():
    prices, runs = _walk_fixture()
    cfg = {"cost": 0., "band": 0.}
    full, picks = research_multi.walk_forward(prices, runs, 2020, "2019-01-01", 365, cfg)
    prefix, old_picks = research_multi.walk_forward(prices.loc[:"2020-12-31"], runs,
                                                   2020, "2019-01-01", 365, cfg)
    assert [p["pick"] for p in picks] == ["sin_freno", "con_freno"]
    assert picks[0] == old_picks[0]
    pd.testing.assert_frame_equal(full.loc[prefix.index], prefix)
    assert full.loc["2020-01-03", "ret"] == pytest.approx(-.2)
    # A enero llega el capital previo y su caída; no se reinicia al cambiar de regla.
    assert full.loc["2021-01-01", "brake"] < 1


def test_walk_forward_first_year_return_uses_previous_trading_close():
    prices, runs = _walk_fixture()
    prices = prices.loc[prices.index.dayofweek < 5]
    for run in runs.values():
        run["W"] = run["W"].reindex(prices.index)
    bt, _ = research_multi.walk_forward(prices, runs, 2020, "2019-01-01", 252,
                                        {"cost": .001, "band": 0.})
    assert bt.loc[:"2019-12-31", "turnover"].sum() == 0
    assert bt.loc["2020-01-01", "turnover"] == 1


def test_parameter_switch_preserves_kill_and_never_rebuys():
    idx = pd.date_range("2020-01-01", periods=5)
    prices = pd.DataFrame({"A": [100, 80, 64, 64, 90]}, index=idx)
    weights = pd.DataFrame(1., index=idx, columns=["A"])
    p = PortfolioParams(dd_brake=False)
    schedule = pd.Series([p, p, PortfolioParams(dd_brake=True), p, p], index=idx)
    bt = simulate_portfolio(prices, weights, p, cost=0., band=0., kill_dd=.25,
                            params_by_date=schedule)
    assert bt.iloc[2]["ret"] == pytest.approx(-.2)
    assert (bt.iloc[3:]["position"] == 0).all()
    assert (bt.iloc[3:]["brake"] == 0).all()
    assert (1 + bt["ret"]).prod() == pytest.approx(.64)
    with pytest.raises(ValueError, match="índice"):
        simulate_portfolio(prices, weights, p, params_by_date=schedule.iloc[:-1])


def test_optional_covariance_shrinkage_is_causal_and_constrained():
    rng = np.random.default_rng(44)
    idx = pd.date_range("2020-01-01", periods=390)
    prices = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.002, .02, (390, 3)), axis=0)),
                          columns=["BTC", "ETH", "SOL"], index=idx)
    p = PortfolioParams(cov_estimator="ledoit_wolf", regime_asset=None)
    full = target_weights(prices, listed_universe(prices), p)
    prefix = target_weights(prices.iloc[:330], listed_universe(prices.iloc[:330]), p)
    pd.testing.assert_frame_equal(full.iloc[:330], prefix)
    assert (full.sum(axis=1) <= 1 + 1e-12).all()
    assert (full >= 0).all().all() and (full <= .4 + 1e-12).all().all()


def test_finite_placebo_includes_observation_and_ties():
    assert finite_randomization_pvalue(10, np.arange(200) / 100) == pytest.approx(1 / 201)
    assert finite_randomization_pvalue(1, [1, 2, 0]) == .75
    with pytest.raises(ValueError):
        finite_randomization_pvalue(1, [np.nan])
    with pytest.raises(ValueError):
        finite_randomization_pvalue(1, [])


def test_describing_optional_grid_does_not_run_and_counts_only_declared(monkeypatch):
    monkeypatch.setattr(research_multi, "load_sleeve", lambda *a: pytest.fail("no descargar"))
    original = json.dumps(research_multi.SLEEVES, sort_keys=True)
    standard, old = research_multi.research_plan()
    plan, variants = research_multi.research_plan(universe="bitso", cov_estimator="ledoit_wolf")
    assert len(variants) == len(old) * 2
    assert len({v["id"] for v in variants}) == len(variants)
    assert all(v["status"] == "declared" for v in variants)
    assert plan["sleeves"]["crypto"]["universe"] == "bitso"
    assert standard["sleeves"]["crypto"]["candidate"]["cov_estimator"] == "sample"
    assert original == json.dumps(research_multi.SLEEVES, sort_keys=True)
    with pytest.raises(ResearchGateError):
        research_multi.run()


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout.decode().strip()


@pytest.fixture
def prereg_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Synthetic test")
    _git(root, "config", "user.email", "synthetic@example.invalid")
    config = {"universe": "synthetic"}
    variants = [{"id": "synthetic-one", "status": "declared"}]
    path = root / "prereg.md"
    meta = {"status": "approved", "protocol_version": 1, "experiment_id": "synthetic",
            "config_sha256": canonical_hash(config), "variant_ids": ["synthetic-one"],
            "hypothesis": "Solo integridad", "evaluation_window": "fixture offline",
            "criteria": dict.fromkeys(("walk_forward", "placebo", "bootstrap", "cost_stress", "drawdown"),
                                       "criterio sintético")}
    path.write_text("---\n" + yaml.safe_dump(meta) + "---\nPreregistro de prueba.\n")
    _git(root, "add", "prereg.md")
    _git(root, "commit", "-m", "preregistro sintético")
    commit = _git(root, "rev-parse", "HEAD")
    return root, path, commit, config, variants


def _add_code(root):
    (root / "code.py").write_text("# fixture\n")
    _git(root, "add", "code.py")
    _git(root, "commit", "-m", "código sintético posterior")


def test_preregistration_requires_earlier_commit_and_exact_configuration(prereg_repo):
    root, path, commit, config, variants = prereg_repo
    ids = [v["id"] for v in variants]
    with pytest.raises(ResearchGateError, match="anterior"):
        verify_preregistration(root, path, commit, "synthetic", config, ids)
    _add_code(root)
    proof = verify_preregistration(root, path, commit, "synthetic", config, ids)
    assert proof["sha256"] == file_hash(path)
    with pytest.raises(ResearchGateError, match="configuración"):
        verify_preregistration(root, path, commit, "synthetic", {"other": True}, ids)
    with pytest.raises(ResearchGateError, match="grid"):
        verify_preregistration(root, path, commit, "synthetic", config, [])
    path.write_text(path.read_text() + "cambio no declarado\n")
    with pytest.raises(ResearchGateError, match="difiere"):
        verify_preregistration(root, path, commit, "synthetic", config, ids)


def test_preregistration_rejects_draft_and_dirty_code(prereg_repo):
    root, path, commit, config, variants = prereg_repo
    path.write_text(path.read_text().replace("status: approved", "status: draft"))
    _git(root, "add", "prereg.md")
    _git(root, "commit", "-m", "borrador sintético")
    draft = _git(root, "rev-parse", "HEAD")
    _add_code(root)
    with pytest.raises(ResearchGateError, match="borrador"):
        verify_preregistration(root, path, draft, "synthetic", config, ["synthetic-one"])
    (root / "code.py").write_text("# modificado\n")
    with pytest.raises(ResearchGateError, match="sin commit"):
        verify_preregistration(root, path, draft, "synthetic", config, ["synthetic-one"])


def test_manifest_freezes_inputs_and_ledger_separates_declared_from_executed(prereg_repo, tmp_path):
    root, path, commit, config, variants = prereg_repo
    _add_code(root)
    ledger = tmp_path / "ledger.jsonl"
    run = ExperimentRun(root, "synthetic", path, commit, config, variants, tmp_path / "out", ledger)
    prices = pd.DataFrame({"A": [1., np.nan, 2.]}, index=pd.date_range("2020-01-01", periods=3))
    manifest = run.freeze_dataset("synthetic", prices, prices.notna(), {"point_in_time_complete": False})
    assert manifest["missing_by_asset"]["A"] == 1
    assert file_hash(run.directory / manifest["files"]["prices"]["file"]) == manifest["files"]["prices"]["sha256"]
    with pytest.raises(ResearchGateError, match="todas"):
        run.finish("completed")
    with pytest.raises(ResearchGateError, match="declarada"):
        run.variant("undeclared", "started")
    run.variant("synthetic-one", "started")
    run.variant("synthetic-one", "completed")
    run.finish("completed")
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [e["kind"] for e in events].count("variant_started") == 1
    assert run.manifest["live_authorized"] is False
    ledger.write_text(ledger.read_text().replace("run_started", "run_changed", 1))
    with pytest.raises(ResearchGateError, match="integridad"):
        append_event(ledger, {"kind": "attempt"})


def test_promotion_requires_matching_evidence_and_four_complete_weeks():
    validation = {"config_sha256": "config", "code_commit": "code", "run_id": "run",
                  "checks": dict.fromkeys(("walk_forward", "placebo", "bootstrap", "cost_stress", "drawdown", "causality"), True)}
    paper = {"config_sha256": "config", "code_commit": "code", "run_id": "run",
             "started_at": "2026-01-01T00:00:00+00:00", "ended_at": "2026-01-29T00:00:00+00:00",
             "observed_days": 28, "complete": True, "unresolved_errors": 0}
    now = datetime(2026, 1, 30, tzinfo=timezone.utc)
    passed = promotion_gate(validation, paper, now)
    assert passed["ready_for_human_review"] and not passed["live_authorized"]
    assert not promotion_gate(validation, {**paper, "observed_days": 27}, now)["ready_for_human_review"]
    assert not promotion_gate(validation, {**paper, "code_commit": "different"}, now)["ready_for_human_review"]
