"""Only synthetic, offline fixtures: no performance experiment or production state."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest
import yaml

from lab import paper_comparison as paper
from lab.experiments import ResearchGateError, canonical_hash
from lab.storage import SQLiteStore


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout.decode().strip()


def frames(plan, now):
    out = {}
    for block in paper.BLOCKS:
        sc = plan["portfolios"]["control"][block]
        end = paper.latest_closed_candle(sc, now.tz_convert("UTC").tz_localize(None))
        dates = pd.date_range(end=end, periods=360, freq="D" if block == "crypto" else "B", name="date")
        assets = sc["universe"] if block == "crypto" else list(sc["mix"])
        rng = np.random.default_rng(49)
        out[block] = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.003, .008, (360, len(assets))), axis=0)),
                                  index=dates, columns=assets)
    return out


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    plan, variants = paper.comparison_plan()
    root = tmp_path / "code"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Synthetic fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    prereg = root / "prereg.md"
    metadata = {"status": "approved", "protocol_version": 1, "experiment_id": paper.EXPERIMENT_ID,
                "config_sha256": canonical_hash(plan), "variant_ids": [v["id"] for v in variants],
                "hypothesis": "integrity fixture only", "evaluation_window": "synthetic",
                "criteria": dict.fromkeys(("walk_forward", "placebo", "bootstrap", "cost_stress", "drawdown"), "synthetic")}
    prereg.write_text("---\n" + yaml.safe_dump(metadata) + "---\nSynthetic only.\n")
    git(root, "add", "prereg.md")
    git(root, "commit", "-m", "synthetic preregistration")
    commit = git(root, "rev-parse", "HEAD")
    (root / "code.py").write_text("# integrity fixture\n")
    git(root, "add", "code.py")
    git(root, "commit", "-m", "synthetic code after registration")
    monkeypatch.setattr(paper, "ROOT", root)
    monkeypatch.setattr(paper, "PREREGISTRATION", prereg)
    monkeypatch.setattr(paper, "comparison_plan", lambda: (copy.deepcopy(plan), copy.deepcopy(variants)))
    monkeypatch.setattr(paper, "assert_current_control", lambda p: None)
    clock = {"now": pd.Timestamp("2026-09-28T02:00:00Z")}
    monkeypatch.setattr(paper, "_now", lambda: clock["now"])
    data_dir = tmp_path / "new-paper-only"
    inputs = tmp_path / "csv"
    inputs.mkdir()
    paths = {block: inputs / f"{block}.csv" for block in paper.BLOCKS}
    def save():
        for block, frame in frames(plan, clock["now"]).items():
            frame.to_csv(paths[block], float_format="%.17g")
    save()
    def run(**kw):
        return paper.run_once(commit, data_dir, **({} if kw.get("fetch") else {
            "crypto_prices": paths["crypto"], "stocks_prices": paths["stocks"]}), **kw)
    return {"root": root, "prereg": prereg, "commit": commit, "clock": clock, "plan": plan,
            "directory": data_dir, "paths": paths, "save": save, "run": run}


def test_shared_frames_independent_ledgers_and_exact_stock_control(experiment, monkeypatch):
    from lab import bot, brokers
    for name in ("load_env", "make_broker"):
        monkeypatch.setattr(bot, name, lambda *a, **k: pytest.fail("operational path called"))
    for name in ("AlpacaBroker", "BitsoBroker", "BookSimBroker"):
        monkeypatch.setattr(brokers, name, lambda *a, **k: pytest.fail("external broker called"))
    received = {}
    original = paper.run_sleeve
    def track(name, sc, prices, *args, **kwargs):
        received[name] = prices.copy(deep=True)
        result = original(name, sc, prices, *args, **kwargs)
        prices.iloc[0, 0] = 1  # no mutation may reach the other portfolio
        return result
    monkeypatch.setattr(paper, "run_sleeve", track)
    report = experiment["run"]()
    for block in paper.BLOCKS:
        pd.testing.assert_frame_equal(received[f"control.{block}"], received[f"aggressive.{block}"])
    assert report["portfolios"]["control"]["blocks"]["stocks"] == report["portfolios"]["aggressive"]["blocks"]["stocks"]
    assert report["observed_days"] == 1 and not report["complete"]
    assert not report["live_authorized"] and not report["ready_for_human_review"]
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    state = store.read_document("state")
    assert len(state["sleeves"]) == 4
    for sleeve in state["sleeves"].values():
        assert sleeve["capital_base"] == 500
        assert sleeve["ledger"]["cash"] >= 0
        assert all(q >= 0 for q in sleeve["ledger"]["positions"].values())
    assert report["cost_model"]["crypto"]["approx_one_way_bps"] == pytest.approx(45)
    assert (experiment["directory"] / "comparison.md").is_file()
    assert json.loads((experiment["directory"] / "comparison.json").read_text())["run_id"] == report["run_id"]


def test_restart_same_pair_is_idempotent_and_does_not_age_paper(experiment, monkeypatch):
    first = experiment["run"]()
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    before = {key: store.read_document(key) for key in ("state", "comparison_ticks", "comparison_history")}
    counts = (len(store.rows("trades")), len(store.rows("equity")))
    experiment["clock"]["now"] += pd.Timedelta(hours=1)
    monkeypatch.setattr(paper, "run_sleeve", lambda *a, **kw: pytest.fail("replayed same candle"))
    assert experiment["run"]() == first
    assert (len(store.rows("trades")), len(store.rows("equity"))) == counts
    assert {key: store.read_document(key) for key in before} == before


def test_failed_second_portfolio_rolls_back_entire_pair_and_restarts(experiment, monkeypatch):
    original = paper.run_sleeve
    def fail(name, *args, **kwargs):
        if name == "aggressive.crypto":
            raise RuntimeError("synthetic process interruption")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(paper, "run_sleeve", fail)
    with pytest.raises(RuntimeError, match="interruption"):
        experiment["run"]()
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    assert store.rows("trades") == [] and store.rows("equity") == []
    assert store.read_document("comparison_history") == []
    assert all(s["ledger"] == {"cash": 500., "positions": {}} for s in store.read_document("state")["sleeves"].values())
    assert paper.status(experiment["directory"])["unresolved_errors"] == 1
    monkeypatch.setattr(paper, "run_sleeve", original)
    assert experiment["run"]()["observed_days"] == 1
    assert paper.status(experiment["directory"])["health"]["status"] == "ok"


def test_database_failure_rolls_back_state_trades_and_snapshots(experiment, monkeypatch):
    experiment["run"]()
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    before = {name: store.read_document(name) for name in ("state", "snapshot", "comparison", "comparison_ticks")}
    trades = store.rows("trades")
    equity = store.rows("equity")
    experiment["clock"]["now"] += pd.Timedelta(days=1)
    experiment["save"]()
    original = SQLiteStore._rows
    def fail(self, db, table, rows):
        original(self, db, table, rows)
        if table == "equity":
            raise RuntimeError("synthetic commit interruption")
    monkeypatch.setattr(SQLiteStore, "_rows", fail)
    with pytest.raises(RuntimeError, match="interruption"):
        experiment["run"]()
    assert {name: store.read_document(name) for name in before} == before
    assert store.rows("trades") == trades and store.rows("equity") == equity
    assert paper.status(experiment["directory"])["status"] == "error"
    monkeypatch.setattr(SQLiteStore, "_rows", original)
    assert experiment["run"]()["observed_days"] == 2


def test_revised_same_candle_is_blocked_and_cannot_change_portfolio(experiment):
    experiment["run"]()
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    state = store.read_document("state")
    p = experiment["paths"]["crypto"]
    frame = pd.read_csv(p, index_col=0)
    frame.iloc[-1, 0] *= 1.001
    frame.to_csv(p)
    with pytest.raises(ResearchGateError, match="revisados"):
        experiment["run"]()
    assert store.read_document("state") == state
    assert len(store.read_document("comparison_history")) == 1


@pytest.mark.parametrize("violation", ["dirty", "same_commit", "draft"])
def test_gate_blocks_before_csv_network_or_output(experiment, monkeypatch, violation):
    if violation == "dirty":
        (experiment["root"] / "uncommitted.txt").write_text("dirty")
    elif violation == "same_commit":
        experiment["commit"] = git(experiment["root"], "rev-parse", "HEAD")
    else:
        experiment["prereg"].write_text(experiment["prereg"].read_text().replace("status: approved", "status: draft"))
    monkeypatch.setattr(paper, "fetch_prices", lambda *a, **kw: pytest.fail("gate allowed network"))
    for path in experiment["paths"].values():
        path.unlink()
    with pytest.raises(ResearchGateError):
        paper.run_once(experiment["commit"], experiment["directory"], fetch=True)
    assert not experiment["directory"].exists()


def test_validation_rejects_future_and_unclosed_ny_candles(experiment):
    plan = experiment["plan"]
    now = experiment["clock"]["now"]
    data = frames(plan, now)
    crypto = data["crypto"]
    crypto.loc[pd.Timestamp("2026-09-28")] = crypto.iloc[-1]
    with pytest.raises(ResearchGateError, match="futuras"):
        paper.validate_prices(crypto.to_csv().encode(), "crypto", plan["portfolios"]["control"]["crypto"], now)
    before_close = pd.Timestamp("2026-09-28T20:59:00Z")  # 16:59 New York
    stocks = data["stocks"]
    stocks.loc[pd.Timestamp("2026-09-28")] = stocks.iloc[-1]
    raw = stocks.to_csv().encode()
    sc = plan["portfolios"]["control"]["stocks"]
    with pytest.raises(ResearchGateError, match="futuras"):
        paper.validate_prices(raw, "stocks", sc, before_close)
    assert paper.validate_prices(raw, "stocks", sc, before_close + pd.Timedelta(minutes=1)).index[-1] == pd.Timestamp("2026-09-28")


@pytest.mark.parametrize("problem", ["duplicate", "short", "negative", "infinite", "missing_asset", "gap", "header_duplicate"])
def test_invalid_inputs_fail_closed(experiment, problem):
    plan = experiment["plan"]
    now = experiment["clock"]["now"]
    frame = frames(plan, now)["crypto"]
    if problem == "duplicate":
        frame = pd.concat([frame.iloc[:1], frame])
    elif problem == "short":
        frame = frame.iloc[-249:]
    elif problem == "negative":
        frame.iloc[20, 0] = -1
    elif problem == "infinite":
        frame.iloc[20, 0] = np.inf
    elif problem == "missing_asset":
        frame = frame.drop(columns=frame.columns[0])
    elif problem == "gap":
        frame = frame.drop(index=frame.index[20])
    raw = frame.to_csv().encode()
    if problem == "header_duplicate":
        raw = raw.replace(b"BTC,ETH", b"BTC,BTC", 1)
    with pytest.raises(ResearchGateError):
        paper.validate_prices(raw, "crypto", plan["portfolios"]["control"]["crypto"], now)


def test_public_fetch_once_per_market_then_frozen_reuse(experiment, monkeypatch):
    calls = []
    data = frames(experiment["plan"], experiment["clock"]["now"])
    def fetch(name, sc, now, notes):
        calls.append((name, sc["universe"]))
        return data[name].copy(deep=True)
    monkeypatch.setattr(paper, "fetch_prices", fetch)
    first = experiment["run"](fetch=True)
    assert [name for name, _ in calls] == ["crypto", "stocks"]
    assert calls[1][1] == ["SPY", "IEF"]
    assert experiment["run"](fetch=True) == first
    assert len(calls) == 2
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    frozen = store.read_document("comparison_inputs")["crypto"]
    (experiment["directory"] / frozen["file"]).write_text("corrupted")
    with pytest.raises(ResearchGateError, match="modificada"):
        experiment["run"](fetch=True)


def test_sparse_real_observations_do_not_become_28_days_from_history(experiment):
    experiment["run"]()
    experiment["clock"]["now"] += pd.Timedelta(days=35)
    experiment["save"]()
    report = experiment["run"]()
    assert report["elapsed_days"] == 35
    assert report["observed_days"] == 2
    assert report["remaining_observed_days"] == 26
    assert not report["complete"] and not report["ready_for_human_review"]


def test_rejects_operational_database_or_different_experiment(experiment):
    directory = experiment["directory"]
    directory.mkdir()
    marker = directory / "runtime.yaml"
    marker.write_text("synthetic runtime marker")
    with pytest.raises(ResearchGateError, match="operativo"):
        experiment["run"]()
    marker.unlink()
    SQLiteStore(directory / paper.DB_NAME).write_document("comparison_manifest", {"type": "other"})
    with pytest.raises(ResearchGateError, match="no pertenece"):
        experiment["run"]()


def test_status_describe_do_not_initialize_or_run(experiment, monkeypatch, capsys):
    monkeypatch.setattr(paper, "run_sleeve", lambda *a, **kw: pytest.fail("strategy ran"))
    monkeypatch.setattr(paper, "fetch_prices", lambda *a, **kw: pytest.fail("market data requested"))
    assert paper.main(["--describe"]) == 0
    assert paper.main(["--status", "--data-dir", str(experiment["directory"])]) == 0
    assert not experiment["directory"].exists()
    assert "declared_not_run" in capsys.readouterr().out


def test_commit_survives_interruption_before_report_export(experiment, monkeypatch):
    original = paper._export
    calls = []
    def fail_once(*args):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("synthetic export interruption after commit")
        return original(*args)
    monkeypatch.setattr(paper, "_export", fail_once)
    with pytest.raises(OSError, match="after commit"):
        experiment["run"]()
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    trades, equity = store.rows("trades"), store.rows("equity")
    assert trades and len(equity) == 4
    monkeypatch.setattr(paper, "run_sleeve", lambda *a, **k: pytest.fail("committed trades replayed"))
    recovered = experiment["run"]()
    assert store.rows("trades") == trades and store.rows("equity") == equity
    assert recovered["observed_days"] == 1
    assert json.loads((experiment["directory"] / "comparison.json").read_text()) == recovered


def test_process_exit_mid_pair_does_not_persist_one_portfolio(experiment, monkeypatch):
    original = paper.run_sleeve
    def killed(name, *args, **kwargs):
        if name == "aggressive.stocks":
            raise SystemExit("synthetic kill")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(paper, "run_sleeve", killed)
    with pytest.raises(SystemExit):
        experiment["run"]()
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    assert store.rows("trades") == []
    assert store.read_document("comparison_ticks") == {}
    monkeypatch.setattr(paper, "run_sleeve", original)
    assert experiment["run"]()["observed_days"] == 1
    assert len(store.rows("equity")) == 4


def test_daily_gap_is_durable_and_not_cleared_by_identical_retry(experiment):
    experiment["run"]()
    experiment["clock"]["now"] += pd.Timedelta(days=3)
    experiment["save"]()
    report = experiment["run"]()
    assert report["observation_gaps"][0]["missing_daily_decisions"] == 2
    assert report["unresolved_errors"] == 1
    assert report["status"] == "incomplete_observation_gaps"
    assert experiment["run"]()["unresolved_errors"] == 1
    assert paper.status(experiment["directory"])["unresolved_errors"] == 1
    assert not report["complete"]


def test_control_drift_blocks_before_io(experiment, monkeypatch):
    def reject(plan):
        raise ResearchGateError("synthetic changed control")
    monkeypatch.setattr(paper, "assert_current_control", reject)
    monkeypatch.setattr(paper, "fetch_prices", lambda *a, **k: pytest.fail("fetch before control gate"))
    with pytest.raises(ResearchGateError, match="changed control"):
        experiment["run"](fetch=True)
    assert not experiment["directory"].exists()


def test_pending_result_never_commits_other_sleeves(experiment, monkeypatch):
    original = paper.run_sleeve
    def pending(name, *args, **kwargs):
        result = original(name, *args, **kwargs)
        if name == "aggressive.stocks":
            result["status"] = "pending"
        return result
    monkeypatch.setattr(paper, "run_sleeve", pending)
    with pytest.raises(ResearchGateError, match="pending"):
        experiment["run"]()
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    assert not store.rows("trades") and not store.rows("equity")
    assert not store.read_document("comparison_ticks")


def test_clock_rollback_rejected_without_new_evidence(experiment):
    experiment["run"]()
    experiment["clock"]["now"] -= pd.Timedelta(minutes=1)
    with pytest.raises(ResearchGateError, match="reloj retrocedió"):
        experiment["run"]()
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    assert len(store.read_document("comparison_history")) == 1


def test_holiday_without_new_stock_close_keeps_frozen_vintage(experiment, monkeypatch):
    initial = frames(experiment["plan"], experiment["clock"]["now"])
    def fetch(name, sc, now, notes):
        if name == "stocks":
            # Simulated Monday holiday: same prices, provider's warmup start advances.
            return initial[name].iloc[2:].copy() if now > pd.Timestamp("2026-09-28T20:00Z") else initial[name].copy()
        return frames(experiment["plan"], now)[name]
    monkeypatch.setattr(paper, "fetch_prices", fetch)
    first = experiment["run"](fetch=True)
    experiment["clock"]["now"] += pd.Timedelta(days=1)
    next_pair = experiment["run"](fetch=True)
    assert next_pair["datasets"]["stocks"]["sha256"] == first["datasets"]["stocks"]["sha256"]
    assert next_pair["observed_days"] == 2 and not next_pair["observation_gaps"]


def test_holiday_provider_revision_does_not_replace_old_capture(experiment, monkeypatch):
    initial = frames(experiment["plan"], experiment["clock"]["now"])
    def fetch(name, sc, now, notes):
        if name == "stocks":
            frame = initial[name].copy()
            if now > pd.Timestamp("2026-09-28T20:00Z"):
                frame.iloc[-1, 0] *= 1.01
            return frame
        return frames(experiment["plan"], now)[name]
    monkeypatch.setattr(paper, "fetch_prices", fetch)
    first = experiment["run"](fetch=True)
    experiment["clock"]["now"] += pd.Timedelta(days=1)
    with pytest.raises(ResearchGateError, match="revisados"):
        experiment["run"](fetch=True)
    store = SQLiteStore(experiment["directory"] / paper.DB_NAME)
    assert store.read_document("comparison")["run_id"] == first["run_id"]
    assert len(store.read_document("comparison_history")) == 1


def test_non_usd_provenance_rejected_before_reading_inputs(experiment, monkeypatch):
    monkeypatch.setattr(paper, "_inputs", lambda *a, **k: pytest.fail("non USD data was read"))
    with pytest.raises(ResearchGateError, match="USD"):
        experiment["run"](provenance={"crypto": {"quote": "MXN"}})
    assert not experiment["directory"].exists()
