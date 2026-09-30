"""Integridad de la observación futura con precios sintéticos; sin mercado/red."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest
import yaml

from lab import paper_comparison as paper, paper_ops, rotation_plan
from lab.aggressive_plan import roles_for, validate_registered_variants
from lab.experiments import ResearchGateError, canonical_hash, file_hash, variant_id
from lab.portfolio import PortfolioParams
from lab.rotation_observer import prospective_decision
from lab.storage import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]


def plan_copy():
    return yaml.safe_load((ROOT / "configs/experiments/rotation_paper_v1.yaml").read_text())


def test_frozen_plan_variants_are_in_the_grid_and_only_rotation_changes():
    plan = plan_copy()
    assert canonical_hash(plan) == rotation_plan.PLAN_SHA256
    validate_registered_variants(plan)
    candidate = deepcopy(plan["portfolios"]["candidate"])
    assert candidate["crypto"]["params"].pop("rotation_buffer") == .15
    assert candidate == plan["portfolios"]["control"]
    assert roles_for(plan) == ("control", "candidate")


def test_plan_refuses_changed_protocol_and_incomplete_historical_evidence(tmp_path, monkeypatch):
    plan = plan_copy()
    directory = tmp_path / "reports/experiments/rotation-v2" / plan["historical_evidence"]["run_id"]
    directory.mkdir(parents=True)
    manifest = {"status": "completed", "live_authorized": False,
                "config_sha256": plan["historical_evidence"]["config_sha256"],
                "run_id": directory.name, "variant_states": {str(i): "completed" for i in range(90)}}
    results = {"crypto": {"rotation_comparison": {"checks": dict.fromkeys(rotation_plan.CHECKS, True), "promoted": False}}}
    for name, contents in (("manifest", manifest), ("results", results)):
        item = plan["historical_evidence"][name]
        p = tmp_path / item["path"]
        p.write_text(json.dumps(contents))
        item["sha256"] = file_hash(p)
    monkeypatch.setattr(rotation_plan, "ROOT", tmp_path)
    monkeypatch.setattr(rotation_plan, "PLAN_SHA256", canonical_hash(plan))
    rotation_plan.validate_plan(plan)
    changed = deepcopy(plan)
    changed["portfolios"]["candidate"]["crypto"]["fee"] = 0
    with pytest.raises(ResearchGateError, match="preregistro"):
        rotation_plan.validate_plan(changed)
    (tmp_path / plan["historical_evidence"]["results"]["path"]).write_text("{}")
    with pytest.raises(ResearchGateError, match="evidencia"):
        rotation_plan.validate_plan(plan)


def test_candidate_ledgers_idempotence_and_backup_restore_are_isolated(tmp_path, monkeypatch):
    plan = plan_copy()
    variants = []
    for role in roles_for(plan):
        p = PortfolioParams.from_dict(plan["portfolios"][role]["crypto"]["params"]).to_dict()
        variants.append({"id": variant_id("crypto", p, "bitso"), "sleeve": "crypto",
                         "role": role, "params": p, "universe": "bitso", "status": "declared"})
    code = tmp_path / "code"
    code.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(code), *args], capture_output=True, check=True).stdout.decode().strip()
    git("init"); git("config", "user.name", "Synthetic"); git("config", "user.email", "fixture@example.invalid")
    prereg = code / "prereg.md"
    meta = {"status": "approved", "protocol_version": 1, "experiment_id": plan["experiment_id"],
            "config_sha256": canonical_hash(plan), "variant_ids": [v["id"] for v in variants],
            "hypothesis": "synthetic fixture", "evaluation_window": "synthetic fixture",
            "criteria": dict.fromkeys(("walk_forward", "placebo", "bootstrap", "cost_stress", "drawdown"), "synthetic")}
    prereg.write_text("---\n" + yaml.safe_dump(meta) + "---\n")
    git("add", "prereg.md"); git("commit", "-m", "Preregistro sintético"); commit = git("rev-parse", "HEAD")
    (code / "code.py").write_text("# synthetic\n"); git("add", "code.py"); git("commit", "-m", "Código sintético posterior")
    now = pd.Timestamp("2026-09-30T02:00:00Z")
    monkeypatch.setattr(paper, "ROOT", code)
    monkeypatch.setattr(paper, "preregistration_path", lambda p: prereg)
    monkeypatch.setattr(paper, "comparison_plan", lambda p=None: (deepcopy(plan), deepcopy(variants)))
    monkeypatch.setattr(paper, "assert_current_control", lambda p: None)
    monkeypatch.setattr(paper, "_now", lambda: now)
    monkeypatch.setattr(paper, "fetch_prices", lambda *a: pytest.fail("network called"))
    paths = {}
    for block in paper.BLOCKS:
        sc = plan["portfolios"]["control"][block]
        end = paper.latest_closed_candle(sc, now.tz_convert("UTC").tz_localize(None))
        idx = pd.date_range(end=end, periods=360, freq="D" if block == "crypto" else "B", name="date")
        assets = sc["universe"] if block == "crypto" else list(sc["mix"])
        rng = np.random.default_rng(49)
        frame = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.003, .008, (360, len(assets))), axis=0)), index=idx, columns=assets)
        paths[block] = tmp_path / f"{block}.csv"
        frame.to_csv(paths[block], float_format="%.17g")
    destination = tmp_path / "isolated-paper"
    kwargs = dict(crypto_prices=paths["crypto"], stocks_prices=paths["stocks"])
    report = paper.run_once(commit, destination, **kwargs)
    assert report["observed_days"] == 1 and not report["complete"]
    assert report["portfolios"]["control"]["blocks"]["stocks"] == report["portfolios"]["candidate"]["blocks"]["stocks"]
    store = SQLiteStore(destination / paper.DB_NAME)
    before = store.read_document("state")
    assert set(before["sleeves"]) == {f"{r}.{b}" for r in ("control", "candidate") for b in paper.BLOCKS}
    assert paper.run_once(commit, destination, **kwargs) == report
    assert store.read_document("state") == before
    bundle = tmp_path / "backup"
    paper_ops.backup(destination, bundle)
    assert paper_ops.verify_backup(bundle)["verified"]
    restored = tmp_path / "restored-inactive"
    paper_ops.restore(bundle, restored)
    assert SQLiteStore(restored / paper.DB_NAME).read_document("state") == before


def test_good_metrics_cannot_replace_elapsed_days_continuity_or_execution_validation():
    c = {"return_pct": 1., "max_drawdown_pct": -2., "traded_notional_usd": 1000.}
    a = {"return_pct": 2., "max_drawdown_pct": -1., "traded_notional_usd": 800.}
    report = {"experiment_id": "rotation-paper-v1", "mode": "paper", "live_authorized": False,
              "complete": False, "observed_days": 1, "elapsed_days": 0, "unresolved_errors": 0,
              "observation_gaps": [], "portfolios": {"control": {"blocks": {"crypto": c}}, "candidate": {"blocks": {"crypto": a}}}}
    assert not prospective_decision(report)["paper_criteria_pass"]
    report.update(complete=True, observed_days=28, elapsed_days=28)
    verdict = prospective_decision(report)
    assert verdict["paper_criteria_pass"] and not verdict["ready_for_human_review"]
    assert not verdict["candidate_promoted"] and not verdict["live_authorized"]
    report["observation_gaps"] = [{"missing_daily_decisions": 1}]
    assert not prospective_decision(report)["paper_criteria_pass"]
