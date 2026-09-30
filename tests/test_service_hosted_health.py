from __future__ import annotations

import datetime as dt
import json
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from lab.runtime import DATABASE_NAME
from lab.service import Reader, make_server
from lab.storage import SQLiteStore


@pytest.fixture
def healthy(tmp_path):
    store = SQLiteStore(tmp_path / DATABASE_NAME)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    store.commit_run({"sleeves": {"crypto": {"mode": "paper", "capital_base": 500}}}, [], [],
                     {"mode": "paper", "sleeves": {"crypto": {"mode": "paper", "status": "ok"}}})
    store.commit_live({"mode": "paper", "sleeves": {"crypto": {"status": "ok"}}}, [])
    store.write_document("deployment", {"mode": "paper", "imported_at_utc": now})
    store.write_document("runtime_health", {"status": "ok", "last_success_utc": now, "interval_seconds": 300})
    (tmp_path / "worker.enabled").write_text("synthetic test marker\n")
    return store, Reader(tmp_path), tmp_path


def test_local_without_hosted_document_keeps_existing_readiness(healthy):
    _, reader, _ = healthy
    result = reader.status()
    assert result["ready"] is True
    assert result["hosted"] == {}


@pytest.mark.parametrize("document,reason", [
    ({"status": "paused", "worker_status": "paused"}, "pausado"),
    ({"status": "running", "worker_status": "paused"}, "pausado"),
    ({"status": "stopped", "worker_status": "running"}, "detenido"),
    ({"status": "running", "worker_status": "stopped"}, "detenido"),
    ({"status": "error", "worker_status": "running"}, "error"),
    ({"status": "running", "worker_status": "error"}, "error"),
    ({"status": "running"}, "no verificado"),
    ({"worker_status": "running"}, "no verificado"),
    ({"status": "starting", "worker_status": "running"}, "no verificado"),
    ({}, "no verificado"),
])
def test_hosted_state_can_veto_a_recent_success_and_persisted_activation(healthy, document, reason):
    store, reader, _ = healthy
    store.write_document("hosted_health", document)
    result = reader.status()
    assert result["ready"] is False
    assert reason in result["reason"]
    assert result["hosted"] == document
    assert result["runtime"]["status"] == "ok"


@pytest.mark.parametrize("document", [None, [], "running"])
def test_malformed_hosted_document_is_not_treated_as_local(healthy, document):
    store, reader, _ = healthy
    store.write_document("hosted_health", document)
    result = reader.status()
    assert result["ready"] is False
    assert "no verificado" in result["reason"]


def test_failed_backup_blocks_readiness_until_reported_healthy(healthy):
    store, reader, _ = healthy
    document = {"status": "running", "worker_status": "running", "backup_status": "error"}
    store.write_document("hosted_health", document)
    result = reader.status()
    assert result["ready"] is False
    assert "backup" in result["reason"]
    store.write_document("hosted_health", {**document, "backup_status": "ok"})
    assert reader.status()["ready"] is True


def test_running_hosted_does_not_replace_runtime_freshness_or_activation(healthy):
    store, reader, directory = healthy
    store.write_document("hosted_health", {"status": "running", "worker_status": "running"})
    assert reader.status()["ready"] is True  # No backup_status before the first backup is allowed.
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
    store.write_document("runtime_health", {"status": "ok", "last_success_utc": old, "interval_seconds": 300})
    result = reader.status()
    assert result["ready"] is False and "Heartbeat vencido" in result["reason"]
    (directory / "worker.enabled").unlink()
    assert "desactivada" in reader.status()["reason"]


def test_http_status_exposes_hosted_pause_and_readiness_returns_unavailable(healthy):
    store, _, directory = healthy
    store.write_document("hosted_health", {"status": "paused", "worker_status": "paused"})
    server = make_server(directory, port=0)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(url + "/api/status") as response:
            status = json.load(response)
            assert status["ready"] is False and status["hosted"]["worker_status"] == "paused"
        with pytest.raises(HTTPError) as error:
            urlopen(url + "/readyz")
        assert error.value.code == 503
        with urlopen(url + "/healthz") as response:
            assert json.load(response) == {"status": "alive", "read_only": True}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
