from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import subprocess
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from lab import ops, runtime
from lab.service import make_server
from lab.storage import SQLiteStore


@pytest.fixture
def imported(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "state.json").write_text(json.dumps({"sleeves": {"crypto": {
        "mode": "paper", "capital_base": 500, "peak": 500,
        "ledger": {"cash": 400, "positions": {"BTC": 1}}, "last_candle": "2026-09-26"}}}))
    (source / "snapshot.json").write_text(json.dumps({"mode": "paper", "sleeves": {
        "crypto": {"mode": "paper", "status": "ok", "equity": 500}}}))
    (source / "live.json").write_text(json.dumps({"mode": "paper", "sleeves": {
        "crypto": {"mode": "paper", "status": "ok", "equity": 500}}}))
    (source / "trades.csv").write_text("run_at_utc,sleeve,mode,asset,side,qty,price,value,status\n2026-09-26 00:20,crypto,paper,BTC,buy,1,100,100,filled\n")
    (source / "equity.csv").write_text("date,sleeve,mode,equity,cash,flow\n2026-09-26,crypto,paper,500,400,\n")
    target = tmp_path / "runtime"
    result = ops.import_legacy(source, target)
    return source, target, result


def test_import_is_explicit_preserves_source_and_rejects_overwrite(imported):
    source, target, result = imported
    assert result["mode"] == "paper" and result["cloud_connected"] is False
    assert not (target / "worker.enabled").exists()
    assert result["source_sha256"]["state.json"] == ops.sha256(source / "state.json")
    store = SQLiteStore(target / runtime.DATABASE_NAME)
    assert store.read_document("state")["sleeves"]["crypto"]["ledger"]["cash"] == 400
    assert len(store.rows("trades")) == 1
    with pytest.raises(ValueError, match="ya contiene"):
        ops.import_legacy(source, target)


def test_backup_restore_and_checksum_fail_closed(imported, tmp_path):
    _, target, _ = imported
    destination = tmp_path / "backups" / "sample.sqlite3"
    manifest = ops.backup(target, destination)
    assert ops.verify_backup(destination)["sha256"] == manifest["sha256"]
    restored = tmp_path / "restored"
    ops.restore(destination, restored)
    store = SQLiteStore(restored / runtime.DATABASE_NAME)
    assert store.rows("trades") == SQLiteStore(target / runtime.DATABASE_NAME).rows("trades")
    assert store.read_document("runtime_health")["last_success_utc"] is None
    assert not (restored / "worker.enabled").exists()
    with pytest.raises(ValueError, match="vacío"):
        ops.restore(destination, restored)
    with destination.open("ab") as handle:
        handle.write(b"damaged")
    with pytest.raises(ValueError, match="SHA256"):
        ops.verify_backup(destination)


def test_import_rejects_live_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state.json").write_text(json.dumps({"sleeves": {"x": {"mode": "live"}}}))
    with pytest.raises(ValueError, match="paper"):
        ops.import_legacy(source, tmp_path / "dest")


def test_activation_requires_cutover_and_runtime_refuses_disabled(imported):
    _, target, _ = imported
    with pytest.raises(ValueError, match="cutover"):
        ops.activate(target, False)
    assert runtime.main(["--config", "config.yaml", "--data-dir", str(target), "--once"]) == 2
    assert ops.activate(target, True)["mode"] == "paper"
    assert (target / "worker.enabled").exists()
    assert ops.main(["deactivate", "--data-dir", str(target)]) == 0
    assert not (target / "worker.enabled").exists()


def test_config_redirects_state_without_changing_strategy(imported):
    from lab.bot import load_config
    _, target, _ = imported
    source = Path(__file__).resolve().parents[1] / "config.yaml"
    original = source.read_bytes()
    path, digest = runtime.prepare_config(source, target, 300)
    cfg = load_config(path)
    assert len(digest) == 64
    assert cfg["mode"] == "paper"
    assert cfg["sleeves"] == load_config(source)["sleeves"]
    assert cfg["paths"]["database"] == str(target / runtime.DATABASE_NAME)
    assert source.read_bytes() == original
    cfg["mode"] = "live"
    with pytest.raises(ValueError, match="paper"):
        runtime.validate_config(cfg)


def test_runtime_lock_excludes_second_writer(tmp_path):
    with runtime.exclusive_lock(tmp_path / "runtime.lock"):
        with pytest.raises(RuntimeError, match="bloqueo"):
            with runtime.exclusive_lock(tmp_path / "runtime.lock"):
                pytest.fail("second writer acquired the lock")
    with runtime.exclusive_lock(tmp_path / "runtime.lock"):
        pass


def test_cycle_records_component_failure_even_if_other_component_succeeds(imported):
    _, target, _ = imported
    store = SQLiteStore(target / runtime.DATABASE_NAME)
    config = target / "config.yaml"
    config.write_text("mode: paper\n")
    calls = []
    def runner(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[2] == "lab.bot" else 0, "blocked", "")
    health = runtime.run_cycle(config, store, 300, runner=runner)
    assert health["status"] == "error"
    assert health["last_success_utc"] is None
    assert len(calls) == 2
    assert all("--live" not in cmd for cmd in calls)
    assert store.read_document("runtime_health")["errors"][0]["component"] == "lab.bot"


def test_readiness_rejects_stale_or_failed_heartbeat():
    now = dt.datetime(2026, 9, 28, tzinfo=dt.timezone.utc)
    valid = {"status": "ok", "last_success_utc": now.isoformat(), "interval_seconds": 300}
    assert runtime.readiness(valid, True, now=now)[0]
    assert not runtime.readiness(valid, False, now=now)[0]
    assert not runtime.readiness(valid, True, now=now + dt.timedelta(minutes=12))[0]
    assert not runtime.readiness({**valid, "status": "error"}, True, now=now)[0]
    for status in ("unknown", "pending", None, "stopped"):
        assert not runtime.readiness({**valid, "status": status}, True, now=now)[0]
    assert runtime.readiness({**valid, "status": "running"}, True, now=now)[0]


def test_cycle_needs_new_observation_and_all_active_sleeves(imported):
    _, target, _ = imported
    store = SQLiteStore(target / runtime.DATABASE_NAME)
    config = target / "config.yaml"
    config.write_text("mode: paper\nsleeves:\n  crypto:\n    enabled: true\n")
    def no_updates(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "", "")
    health = runtime.run_cycle(config, store, 300, runner=no_updates)
    assert health["status"] == "error"
    assert any("observación nueva" in error["detail"] for error in health["errors"])
    def fresh_observation(cmd, **kwargs):
        if cmd[2] == "lab.realtime":
            store.write_document("live", {"mode": "paper", "sleeves": {"crypto": {"status": "ok"}}})
        return subprocess.CompletedProcess(cmd, 0, "", "")
    assert runtime.run_cycle(config, store, 300, runner=fresh_observation)["status"] == "ok"
    config.write_text("mode: paper\nsleeves:\n  crypto:\n    enabled: true\n  stocks:\n    enabled: true\n")
    health = runtime.run_cycle(config, store, 300, runner=fresh_observation)
    assert health["status"] == "error"
    assert any("Faltan bloques" in error["detail"] for error in health["errors"])


def test_api_does_not_label_mismatched_modes_as_paper(imported):
    from lab.service import Reader
    _, target, _ = imported
    store = SQLiteStore(target / runtime.DATABASE_NAME)
    store.write_document("live", {"mode": "live", "sleeves": {"crypto": {"status": "ok"}}})
    status = Reader(target).status()
    assert status["ready"] is False and status["mode"] == "unverified"
    assert "bloqueada" in status["reason"]


def test_api_read_only_and_does_not_create_a_database(tmp_path):
    target = tmp_path / "uninitialized"
    server = make_server(target, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(url + "/healthz") as response:
            assert json.load(response)["read_only"] is True
        with urlopen(url + "/api/status") as response:
            assert json.load(response)["ready"] is False
        for endpoint, code in (("/readyz", 503), ("/api/trades?limit=1000", 400), ("/api/secrets", 404)):
            with pytest.raises(HTTPError) as error:
                urlopen(url + endpoint)
            assert error.value.code == code
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "/api/orders", data=b"{}", method="POST"))
        assert error.value.code == 405
        with urlopen(url + "/") as response:
            assert b"SIMULADO" in response.read()
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert not target.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_api_reads_imported_orders_and_snapshots(imported):
    from lab.service import Reader
    _, target, _ = imported
    reader = Reader(target)
    assert reader.status()["snapshot"]["sleeves"]["crypto"]["equity"] == 500
    assert reader.rows("trades", 10)[0]["asset"] == "BTC"
    with pytest.raises(ValueError):
        reader.rows("documents; DROP TABLE orders", 10)
