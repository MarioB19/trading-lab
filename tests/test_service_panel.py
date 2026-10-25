"""Panel único (F3): límite de intentos, atribución, investigación y descarga del respaldo del piloto."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
import json
import threading

import pytest

from lab import hosted, ops, service
from lab.runtime import DATABASE_NAME
from lab.storage import SQLiteStore
from test_hosted import imported_store

AUTH = "Basic " + base64.b64encode(b"tester:test-only").decode()


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("TRADING_DASHBOARD_USER", "tester")
    monkeypatch.setenv("TRADING_DASHBOARD_PASSWORD", "test-only")


@contextmanager
def serving(data_dir, tmp_path, **kwargs):
    config = tmp_path / "config.yaml"
    config.write_text("sleeves:\n  crypto: {capital: 500}\n  stocks: {capital: 500}\n")
    server = service.make_server(data_dir, port=0, config_path=config, require_auth=True, **kwargs)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def get(port, path, authorization=AUTH, forwarded=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.putrequest("GET", path)
        if authorization is not None:
            connection.putheader("Authorization", authorization)
        if forwarded:
            connection.putheader("X-Forwarded-For", forwarded)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_throttle_locks_after_failures_then_recovers():
    now = [0.0]
    throttle = service.AuthThrottle(max_failures=3, window=60, lockout=30, clock=lambda: now[0])
    for _ in range(2):
        throttle.failure("a")
    assert throttle.retry_after("a") == 0
    throttle.failure("a")
    assert throttle.retry_after("a") == 30 and throttle.retry_after("b") == 0
    now[0] = 31
    assert throttle.retry_after("a") == 0
    throttle.failure("a"); throttle.success("a"); throttle.failure("a"); throttle.failure("a")
    assert throttle.retry_after("a") == 0  # un acceso correcto reinicia el conteo


def test_wrong_passwords_get_429_even_with_the_right_one_and_other_clients_are_not_blocked(tmp_path, credentials):
    throttle = service.AuthThrottle(max_failures=3, window=60, lockout=60)
    bad = "Basic " + base64.b64encode(b"tester:wrong").decode()
    with serving(tmp_path / "absent", tmp_path, throttle=throttle) as port:
        assert get(port, "/api/status", authorization=None, forwarded="1.1.1.1")[0] == 401  # sin credenciales no cuenta
        for _ in range(3):
            assert get(port, "/api/status", authorization=bad, forwarded="spoof, 1.1.1.1")[0] == 401
        status, headers, _ = get(port, "/api/status", forwarded="1.1.1.1")
        assert status == 429 and int(headers["Retry-After"]) > 0
        assert get(port, "/api/status", forwarded="2.2.2.2")[0] == 200
        assert get(port, "/healthz", authorization=None, forwarded="1.1.1.1")[0] == 200


def test_attribution_research_and_tabs_asset_are_served(tmp_path, credentials):
    data, store = imported_store(tmp_path)
    with serving(data, tmp_path) as port:
        status, _, body = get(port, "/api/attribution")
        assert status == 200 and set(json.loads(body)) >= {"week", "days_28", "since_start", "method"}
        assert get(port, "/api/attribution?end=ayer")[0] == 400
        status, _, body = get(port, "/api/research")
        research = json.loads(body)
        assert status == 200 and research["backlog"]["siguiente"]["id"] and not research["errors"]
        assert get(port, "/tabs.js")[0] == 200
        assert get(port, "/tabs.js", authorization=None)[0] == 401


def test_latest_backup_downloads_by_verified_parts_and_restores(tmp_path, credentials):
    data, store = imported_store(tmp_path)
    backups = tmp_path / "backups"
    with serving(data, tmp_path, backup_dir=backups) as port:
        assert get(port, "/api/backups/latest")[0] == 404  # aún no hay respaldo
        hosted.perform_backup(data, backups)
        status, _, body = get(port, "/api/backups/latest")
        latest = json.loads(body)
        assert status == 200 and "path" not in latest
        out = tmp_path / "descarga"
        out.mkdir()
        for kind, name, size in (("db", latest["file"], latest["bytes"]),
                                 ("manifest", latest["manifest_file"], latest["manifest_bytes"])):
            blob = b""
            for offset in range(0, size, 4096):
                length = min(4096, size - offset)
                code, headers, part = get(port, f"/api/backups/part?file={latest['file']}&kind={kind}&offset={offset}&length={length}")
                assert code == 200 and hashlib.sha256(part).hexdigest() == headers["X-Part-Sha256"]
                blob += part
            (out / name).write_bytes(blob)
        assert hashlib.sha256((out / latest["file"]).read_bytes()).hexdigest() == latest["sha256"]
        ops.restore(out / latest["file"], tmp_path / "restaurada")
        assert SQLiteStore(tmp_path / "restaurada" / DATABASE_NAME).read_document("deployment")["mode"] == "paper"
        assert get(port, "/api/backups/part?file=../config.yaml&offset=0&length=1")[0] == 409
        assert get(port, f"/api/backups/part?file={latest['file']}&kind=db&offset=0&length={service.MAX_PART + 1}")[0] == 416
        assert get(port, "/api/backups/latest", authorization=None)[0] == 401
