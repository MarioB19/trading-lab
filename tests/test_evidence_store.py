from datetime import datetime, timedelta, timezone
import json
import subprocess

import pytest
import yaml

from lab.evidence import build_summary, collect_once, persist, fingerprint
from lab.storage import SQLiteStore

NOW = datetime(2026, 10, 4, 18, tzinfo=timezone.utc)


def capture():
    return {"status": "ok", "observed_at_utc": NOW.isoformat(), "records": [],
            "panels": {"stocks": {"csv": "private-large-series", "sha256": "panel-hash", "rows": 720}},
            "signal_replay": {"stocks": {"passed": True}}, "errors": []}


def test_capture_is_idempotent_and_backed_up_with_operational_commit(tmp_path):
    store = SQLiteStore(tmp_path / "trading.sqlite3")
    decision = {"sleeve": "crypto", "status": "verified", "inputs": {"a": 1}}
    for _ in range(2):
        store.commit_run({"version": 1}, [{"execution_id": "one", "qty": .3}], [], {}, evidence=[decision])
    with store.transaction() as db:
        persist(db, "market", capture())
    restored = SQLiteStore(store.backup(tmp_path / "backup.sqlite3"))
    with restored.connect() as db:
        result = build_summary(db, now=NOW)
    assert result["counts"] == {"execution": 1, "market": 1}
    assert result["execution"]["crypto"]["integrity"] == "verified"
    assert result["market"]["panels"]["stocks"] == {"sha256": "panel-hash", "rows": 720}
    assert restored.read_document("state") == {"version": 1}
    assert len(restored.rows("trades")) == 1
    assert result["profitability_verified"] is result["live_authorized"] is False


def test_invalid_capture_does_not_discard_executed_fills(tmp_path):
    store = SQLiteStore(tmp_path / "trading.sqlite3")
    store.commit_run({"v": 1}, [{"execution_id": "one"}], [], {}, evidence=[{"price": float("nan")}])
    assert store.read_document("state") == {"v": 1}
    assert len(store.rows("trades")) == 1
    assert store.events()[0]["kind"] == "evidence_error"


def test_tampered_latest_payload_fails_closed_and_old_market_is_stale(tmp_path):
    store = SQLiteStore(tmp_path / "trading.sqlite3")
    with store.transaction() as db:
        persist(db, "market", capture())
    with store.connect() as db:
        assert build_summary(db, now=NOW + timedelta(days=2))["status"] == "stale"
    ref = store.read_document("evidence_index")["latest"]["market"]["document"]
    # Deliberate corruption in isolated fixture; not an operational write path.
    store.write_document(ref, {**capture(), "status": "different"})
    store.write_document("evidence_collection", {"status": "partial"})
    with store.connect() as db:
        result = build_summary(db, now=NOW)
    assert result["status"] == "error"
    assert result["market"] is None


def config(tmp_path):
    cfg = yaml.safe_load(open("config.yaml").read())
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_daily_collection_and_failed_retries_have_bounded_frequency(tmp_path):
    store = SQLiteStore(tmp_path / "trading.sqlite3")
    path = config(tmp_path)
    calls = []
    def collector(cfg, now):
        calls.append(now)
        return {**capture(), "observed_at_utc": now.isoformat()}
    assert collect_once(path, store, collector=collector, now=NOW)["status"] == "ok"
    assert collect_once(path, store, collector=collector, now=NOW+timedelta(hours=2))["status"] == "skip"
    assert collect_once(path, store, collector=collector, now=NOW+timedelta(days=1))["status"] == "ok"
    assert len(calls) == 2
    ref = store.read_document("evidence_index")["latest"]["market"]["document"]
    saved = store.read_document(ref)
    assert saved["digest"] == fingerprint({k: v for k, v in saved.items() if k != "digest"})
    def failed(cfg, now):
        raise ValueError("provider text must not leak")
    later = NOW+timedelta(days=2)
    result = collect_once(path, store, collector=failed, now=later)
    assert result["status"] == "error" and result["error"] == "ValueError"
    assert "provider" not in json.dumps(result)
    assert collect_once(path, store, collector=collector, now=later+timedelta(minutes=5))["status"] == "skip"
    assert collect_once(path, store, collector=collector, now=later+timedelta(hours=1))["status"] == "ok"


def test_partial_public_coverage_does_not_repeat_large_payloads_hourly(tmp_path):
    store = SQLiteStore(tmp_path / "trading.sqlite3")
    path = config(tmp_path)
    def partial(cfg, now):
        return {**capture(), "status": "partial"}
    assert collect_once(path, store, collector=partial, now=NOW)["status"] == "partial"
    assert collect_once(path, store, collector=partial, now=NOW+timedelta(hours=2))["status"] == "skip"
    assert store.read_document("evidence_index")["counts"]["market"] == 1


def test_collection_never_accepts_non_paper_config(tmp_path):
    store = SQLiteStore(tmp_path / "trading.sqlite3")
    path = config(tmp_path)
    cfg = yaml.safe_load(path.read_text()); cfg["mode"] = "invalid"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match="paper"):
        collect_once(path, store, collector=lambda *a, **kw: pytest.fail("must not fetch"), now=NOW)
