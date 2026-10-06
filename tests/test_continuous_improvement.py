"""Offline adversarial checks; no new trading experiment is run by these tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sqlite3

import pytest

from lab import continuous_improvement as ci
from lab import improvement_sources as sources
from lab import runtime

NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)


def fill(side, value, fee, ts, *, wid="scalping-v1", qty=1):
    return {"strategy": wid, "side": side, "qty": qty, "value": value, "fee": fee,
            "ts": ts, "mode": "paper", "liquidity": "taker"}


@pytest.fixture
def snapshot():
    base = int((NOW - timedelta(hours=12)).timestamp() * 1000)
    return {"schema_version": 1, "collected_at_utc": NOW.isoformat(),
        "pilot": {"mode": "paper", "as_of_utc": NOW.isoformat(), "files_match": True,
            "healthy": True, "reconciled": True, "current": {"equity_usd": 995, "pnl_usd": -5},
            "execution_quality": {"total": {"maker_known_trades": 3, "filled_trades": 28}},
            "evidence": {"execution": {k: {"integrity": "verified"} for k in ("crypto", "stocks")}}},
        "arena": {"mode": "paper", "as_of_utc": NOW.isoformat(), "files_match": True,
            "healthy": True, "reconciled": True, "current": {"equity_usd": 3999, "pnl_usd": -1},
            "started_at_utc": (NOW - timedelta(hours=30)).isoformat(),
            "fills": [fill("buy", 100, .36, base), fill("sell", 100.5, .36, base + 1000)],
            "daily_report": {"days": [{"date": "2026-10-05", "in_progress": False,
                "no_data": False, "partial_start": False, "quality": {"coverage": 1.}, "error_count": 0}]}}}


@pytest.fixture
def output(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "DEFAULT_OUTPUT", tmp_path / "research")
    return tmp_path / "research"


def test_cost_inversion_is_measured_not_a_second_fee_subtraction(snapshot):
    report = ci.diagnose(snapshot, now=NOW)
    assert report["balances"]["arena"]["pnl_usd"] == -1
    cycle = report["closed_cycles"][0]
    assert cycle["gross_pnl_usd"] == .5
    assert cycle["net_pnl_usd"] == pytest.approx(-.22)
    issue = next(x for x in report["priorities"] if x["id"].endswith("cost_inversion"))
    assert issue["evidence"]["positive_gross_negative_net"] == 1
    assert issue["evidence"]["sufficient_sample"] is False
    assert issue["strategy_change_authorized"] is False


def test_daily_loss_is_not_a_parameter_change_trigger(snapshot):
    a = ci.diagnose(snapshot, now=NOW)
    snapshot["pilot"]["current"] = {"equity_usd": 1005, "pnl_usd": 5}
    snapshot["arena"]["current"] = {"equity_usd": 4001, "pnl_usd": 1}
    b = ci.diagnose(snapshot, now=NOW)
    assert a["priorities"] == b["priorities"]
    assert b["daily_strategy_change_required"] is False
    assert b["candidate_promoted"] is False


@pytest.mark.parametrize("field,value", [("mode", "live"), ("files_match", False),
    ("healthy", False), ("reconciled", False), ("as_of_utc", "2026-10-05T00:00:00+00:00")])
def test_bad_source_blocks_research(snapshot, field, value):
    snapshot["arena"][field] = value
    report = ci.diagnose(snapshot, now=NOW)
    assert report["status"] == "blocked_by_data_quality"
    assert report["closed_cycles"] == []
    assert all(i["category"] == "technical" for i in report["priorities"])
    assert report["balances"] == {}


def test_missing_source_is_not_invented_zero_return(snapshot):
    del snapshot["pilot"]
    r = ci.diagnose(snapshot, now=NOW)
    assert r["status"] == "blocked_by_data_quality" and not r["balances"]
    assert r["priorities"][0]["id"] == "pilot:unavailable"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, None])
def test_invalid_balances_block_without_fabricating_a_result(snapshot, value):
    snapshot["arena"]["current"]["equity_usd"] = value
    assert ci.diagnose(snapshot, now=NOW)["status"] == "blocked_by_data_quality"


def test_open_and_partial_positions_are_not_closed_cycles():
    assert ci.closed_cycles([fill("buy", 100, 1, 1)], 0) == []
    values = [fill("buy", 100, 1, 1), fill("sell", 55, .5, 2, qty=.5),
              fill("sell", 55, .5, 3, qty=.5)]
    result = ci.closed_cycles(values, 0)
    assert len(result) == 1 and result[0]["net_pnl_usd"] == 8
    assert ci.closed_cycles(values, 4) == []
    with pytest.raises(ValueError, match="inventario"):
        ci.closed_cycles([fill("sell", 100, 1, 1)], 0)


def test_retries_are_idempotent_and_intraday_updates_do_not_add_days(snapshot, output):
    identity = {"code_commit": "synthetic", "kind": "offline_test"}
    first = ci.run(snapshot, output, now=NOW, verified_proof=identity)
    again = ci.run(snapshot, output, now=NOW + timedelta(seconds=10), verified_proof=identity)
    assert first["new_record"] is True and again["new_record"] is False
    assert len(ci.read_history(output)) == 1
    snapshot["arena"]["current"]["equity_usd"] = 3998
    update = ci.run(snapshot, output, now=NOW + timedelta(seconds=20), verified_proof=identity)
    assert len(ci.read_history(output)) == 2
    assert all(x["observed_days"] == 1 for x in update["report"]["priorities"])
    tomorrow = NOW + timedelta(days=1)
    snapshot["collected_at_utc"] = tomorrow.isoformat()
    for name in ("arena", "pilot"):
        snapshot[name]["as_of_utc"] = tomorrow.isoformat()
    last = ci.run(snapshot, output, now=tomorrow, verified_proof=identity)
    assert all(x["observed_days"] == 2 for x in last["report"]["priorities"])


def test_ledger_tampering_is_detected(snapshot, output):
    ci.run(snapshot, output, now=NOW, verified_proof={"code_commit": "synthetic"})
    ledger = output / "ledger.jsonl"
    ledger.write_text(ledger.read_text().replace('"daily_review"', '"forged_review"'))
    with pytest.raises(ci.ResearchGateError, match="alterada"):
        ci.read_history(output)


def test_archived_report_tampering_is_detected_on_retry(snapshot, output):
    ci.run(snapshot, output, now=NOW, verified_proof={"code_commit": "synthetic"})
    event = ci.read_history(output)[0]
    path = output / event["report_path"]
    path.write_text('{}')
    with pytest.raises(ci.ResearchGateError, match="alterado"):
        ci.run(snapshot, output, now=NOW, verified_proof={"code_commit": "synthetic"})


def test_cannot_write_into_operational_state(tmp_path, output):
    with pytest.raises(ValueError, match="dedicado"):
        ci._output(tmp_path / "state")
    output.mkdir()
    (output / "escape").symlink_to(tmp_path / "state")
    with pytest.raises(ValueError, match="dedicado"):
        ci._output(output / "escape")


def test_collection_failure_preserves_good_source_and_redacts_exception():
    def reader(name):
        if name == "pilot":
            raise RuntimeError("secret-value-not-for-output")
        return {"mode": "paper"}
    r = sources.collect(reader)
    assert r["arena"] == {"mode": "paper"}
    assert "pilot" not in r
    assert "secret-value" not in json.dumps(r)


def test_arena_reader_keeps_complete_cycles_beyond_dashboard_limit(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    base = int(NOW.timestamp() * 1000)
    fills = [fill("buy" if i % 2 == 0 else "sell", 100, .36, base + i) for i in range(513)]
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE fills(id INTEGER PRIMARY KEY, payload TEXT)")
        db.executemany("INSERT INTO fills(payload) VALUES(?)", [(json.dumps(f),) for f in fills])
    before = path.read_bytes()
    observed = sources.arena_fills_at_count(path, 512)
    assert observed == fills[:512]  # Excludes a newer fill after the status cut.
    assert len(ci.closed_cycles(observed, base)) == 256
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="incompleto"):
        sources.arena_fills_at_count(path, 514)


@pytest.mark.parametrize("status", ["ok", "running"])
def test_normal_pilot_cycle_is_healthy_when_readiness_is_verified(status):
    assert sources.pilot_is_healthy({"ready": True, "runtime": {"status": status, "errors": []}})


def test_reader_accepts_actual_runtime_in_progress_document(tmp_path, monkeypatch):
    # Observe the real runtime's initial write before synthetic components run.
    documents = {"runtime_health": {"last_success_utc": NOW.isoformat()}}
    class Store:
        def read_document(self, key, default=None): return documents.get(key, default)
        def write_document(self, key, value): documents[key] = deepcopy(value)
    class Observed(Exception): pass
    config = tmp_path / "synthetic.yaml"
    config.write_text("mode: paper\n")
    monkeypatch.setattr(runtime, "utc_now", lambda: NOW.isoformat())
    def observe(command, **kwargs):
        health = documents["runtime_health"]
        assert health["status"] == "running" and "errors" not in health
        ready, _ = runtime.readiness(health, True, now=NOW)
        assert ready and sources.pilot_is_healthy({"ready": ready, "runtime": health})
        raise Observed()
    with pytest.raises(Observed):
        runtime.run_cycle(config, Store(), 300, runner=observe)


@pytest.mark.parametrize("status", [
    {"ready": False, "runtime": {"status": "running"}},
    {"ready": True, "runtime": {"status": "running", "errors": None}},
    {"ready": True, "runtime": {"status": "ok", "errors": None}},
    {"ready": True, "runtime": {"status": "running", "errors": {}}},
])
def test_running_without_completed_error_field_still_requires_verified_readiness(status):
    assert not sources.pilot_is_healthy(status)


@pytest.mark.parametrize("status", [{"ready": False, "runtime": {"status": "running", "errors": []}},
    {"ready": True, "runtime": {"status": "error", "errors": []}},
    {"ready": True, "runtime": {"status": "running", "errors": ["failure"]}},
    {"ready": True, "runtime": {"status": "ok"}}])
def test_in_progress_cannot_hide_missing_readiness_or_an_actual_error(status):
    assert not sources.pilot_is_healthy(status)


def test_collect_run_retries_once_and_retains_blocked_reading(snapshot, output, monkeypatch, capsys):
    broken = deepcopy(snapshot)
    broken["pilot"]["healthy"] = False
    fetched, calls = iter([broken, snapshot]), []
    monkeypatch.setattr(ci, "proof", lambda: {"code_commit": "synthetic"})
    def reader():
        calls.append(True)
        return next(fetched)
    original = ci.run
    monkeypatch.setattr(sources, "collect", reader)
    monkeypatch.setattr(ci, "run", lambda s, out, **kw: original(s, out, now=NOW, **kw))
    ci.main(["--output", str(output), "collect-run"])
    assert len(calls) == 2
    events = ci.read_history(output)
    assert [e["status"] for e in events] == ["blocked_by_data_quality", "review_complete"]
    assert capsys.readouterr().out.find('"retried_once": true') >= 0


@pytest.fixture
def candidate():
    start, end = NOW + timedelta(days=1), NOW + timedelta(days=29)
    r = {"candidate_id": "synthetic", "config_sha256": "config", "proof": {"code_commit": "code"},
         "registered_at_utc": NOW.isoformat(), "declared_trials": 2,
         "config": {"evaluation": {"holdout_start": start.isoformat(),
             "holdout_end": end.isoformat(), "final_evaluation_at": end.isoformat()}}}
    v = {"config_sha256": "config", "code_commit": "code", "run_id": "run", "artifact_integrity_verified": True,
         "checks": {k: True for k in ci.policy()["candidate_requirements"]},
         "holdout_start": start.isoformat(), "holdout_end": end.isoformat(),
         "corrected_trial_count": 2, "evaluated_at_utc": end.isoformat(), "evaluation_count": 1}
    p = {"config_sha256": "config", "code_commit": "code", "run_id": "run", "artifact_integrity_verified": True,
         "started_at": start.isoformat(), "ended_at": end.isoformat(), "observed_days": 28,
         "continuous": True, "observation_gaps": [], "complete": True, "unresolved_errors": 0}
    return r, v, p, end


def test_cannot_peek_at_candidate_and_promote_each_day(candidate):
    r, _, _, end = candidate
    result = ci.candidate_decision(r, {}, {}, now=end - timedelta(seconds=1))
    assert result["status"] == "collecting_until_declared_evaluation"
    assert not result["ready_for_human_review"]


def test_complete_evidence_only_enables_review_never_deployment(candidate):
    r, v, p, end = candidate
    result = ci.candidate_decision(r, v, p, now=end)
    assert result["ready_for_human_review"]
    assert not result["candidate_promoted"] and not result["automatic_deployment"] and not result["live_authorized"]


@pytest.mark.parametrize("failure", ["missing_check", "wrong_identity", "short_period", "gap", "trials", "repeated_evaluation", "past_paper", "no_integrity"])
def test_profit_alone_cannot_override_promotion_gates(candidate, failure):
    r, v, p, end = deepcopy(candidate)
    v["net_profit"] = 1000000  # Irrelevant to missing scientific evidence.
    if failure == "missing_check": del v["checks"]["execution_equivalence"]
    if failure == "wrong_identity": p["code_commit"] = "another-code"
    if failure == "short_period": p["observed_days"] = 27
    if failure == "gap": p["observation_gaps"] = ["missing-day"]
    if failure == "trials": v["corrected_trial_count"] = 1
    if failure == "repeated_evaluation": v["evaluation_count"] = 2
    if failure == "past_paper": p["started_at"] = (NOW - timedelta(days=29)).isoformat()
    if failure == "no_integrity": v["artifact_integrity_verified"] = False
    result = ci.candidate_decision(r, v, p, now=end)
    assert not result["ready_for_human_review"] and result["reasons"]


def test_controller_cannot_be_invoked_on_dirty_unpreregistered_code(monkeypatch):
    called = []
    monkeypatch.setattr(ci, "proof", lambda: (_ for _ in ()).throw(ci.ResearchGateError("dirty")))
    monkeypatch.setattr(sources, "collect", lambda: called.append(True))
    with pytest.raises(ci.ResearchGateError):
        ci.main(["collect-run"])
    assert called == []


@pytest.fixture
def candidate_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init")
    git("config", "user.name", "Synthetic test")
    git("config", "user.email", "synthetic@example.invalid")
    config = {"experiment_id": "synthetic-one", "mode": "paper", "live_authorized": False,
        "variants": [{"id": "one", "sleeve": "synthetic", "params": {"threshold": 2}}],
        "evaluation": {"holdout_start": (NOW + timedelta(days=1)).isoformat(),
                       "holdout_end": (NOW + timedelta(days=29)).isoformat(),
                       "final_evaluation_at": (NOW + timedelta(days=29)).isoformat()}}
    config_path, prereg = root / "candidate.json", root / "prereg.md"
    config_path.write_text(json.dumps(config))
    prereg.write_text('---\nprotocol_version: 1\nstatus: approved\nexperiment_id: synthetic-one\n'
        'hypothesis: Synthetic offline gate fixture\nevaluation_window: Reserved future days\n'
        'config_sha256: ' + ci.canonical_hash(config) + '\nvariant_ids: [one]\ncriteria:\n'
        + ''.join('  ' + k + ': synthetic criterion\n' for k in ['walk_forward', 'placebo', 'bootstrap', 'cost_stress', 'drawdown'])
        + '---\n')
    (root / '.gitignore').write_text('reports/experiments/\n')
    git("add", ".")
    git("commit", "-m", "Synthetic preregistration")
    commit = git("rev-parse", "HEAD")
    (root / "src/lab").mkdir(parents=True)
    (root / "src/lab/research_multi.py").write_text('SLEEVES = {"synthetic": {"grid": {"threshold": [1, 2]}}}\n')
    git("add", ".")
    git("commit", "-m", "Synthetic subsequent code")
    return root, config_path, prereg, commit, config


def test_registration_checks_real_git_proof_and_counts_an_attempt(candidate_repo, output):
    root, cfg, prereg, commit, _ = candidate_repo
    event = ci.register_candidate(cfg, prereg, commit, output, root=root, now=NOW)
    assert event["declared_trials"] == 1
    assert len(ci.read_history(output)) == 1
    with pytest.raises(ci.ResearchGateError, match="ya registrada"):
        ci.register_candidate(cfg, prereg, commit, output, root=root, now=NOW)
    assert len(ci.read_history(output)) == 1


def test_registered_grid_cannot_be_bypassed(candidate_repo, output, monkeypatch):
    root, cfg, prereg, commit, config = candidate_repo
    config["variants"][0]["params"]["threshold"] = 999
    cfg.write_text(json.dumps(config))
    monkeypatch.setattr(ci, "verify_preregistration", lambda *a: {"code_commit": "synthetic"})
    with pytest.raises(ci.ResearchGateError, match="grid contado"):
        ci.register_candidate(cfg, prereg, commit, output, root=root, now=NOW)
    assert ci.read_history(output) == []


def test_registration_cannot_use_already_observed_holdout(candidate_repo, output, monkeypatch):
    root, cfg, prereg, commit, config = candidate_repo
    config["evaluation"]["holdout_start"] = (NOW - timedelta(days=30)).isoformat()
    cfg.write_text(json.dumps(config))
    monkeypatch.setattr(ci, "verify_preregistration", lambda *a: {"code_commit": "synthetic"})
    with pytest.raises(ci.ResearchGateError, match="futuras"):
        ci.register_candidate(cfg, prereg, commit, output, root=root, now=NOW)


def test_cannot_generate_new_candidate_every_loss_day(candidate_repo, output, monkeypatch):
    root, cfg, prereg, commit, config = candidate_repo
    ci.register_candidate(cfg, prereg, commit, output, root=root, now=NOW)
    config["experiment_id"] = "synthetic-two"
    for k in config["evaluation"]:
        config["evaluation"][k] = (ci._time(config["evaluation"][k]) + timedelta(days=2)).isoformat()
    cfg.write_text(json.dumps(config))
    monkeypatch.setattr(ci, "verify_preregistration", lambda *a: {"code_commit": "synthetic"})
    with pytest.raises(ci.ResearchGateError, match="intervalo"):
        ci.register_candidate(cfg, prereg, commit, output, root=root, now=NOW + timedelta(days=1))
    assert len(ci.read_history(output)) == 1


def test_final_review_does_not_open_results_early_and_rejects_tampering(candidate_repo, output, monkeypatch):
    root, cfg, prereg, commit, config = candidate_repo
    ci.register_candidate(cfg, prereg, commit, output, root=root, now=NOW)
    monkeypatch.setattr(ci, "ROOT", root)
    manifest = root / "reports/experiments/synthetic-one/manifest.json"
    early = ci.final_review("synthetic-one", manifest, output, now=NOW)
    assert early["status"] == "collecting_until_declared_evaluation" and not manifest.exists()
    manifest.parent.mkdir(parents=True)
    (manifest.parent / 'validation.json').write_text('{}')
    manifest.write_text(json.dumps({"candidate_id": "synthetic-one", "artifacts": {"validation.json": "wrong"},
                                    "validation": "validation.json", "paper": "paper.json"}))
    with pytest.raises(ci.ResearchGateError, match="alterado"):
        ci.final_review("synthetic-one", manifest, output, now=NOW + timedelta(days=30))
    assert len(ci.read_history(output)) == 1
