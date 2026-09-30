from __future__ import annotations

import base64
from contextlib import contextmanager
from http.client import HTTPConnection
import json
import threading

import pytest

from lab import service


def basic(user="operador-á", password="contraseña:prueba-🔒"):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")


@contextmanager
def serving(tmp_path, *, require_auth=True):
    config = tmp_path / "config.yaml"
    config.write_text("sleeves:\n  crypto: {capital: 500}\n  stocks: {capital: 500}\n")
    server = service.make_server(tmp_path / "absent-data", port=0, config_path=config, require_auth=require_auth)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert not (tmp_path / "absent-data").exists()


def request(port, path, authorization=None, *, method="GET", extra_headers=()):
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.putrequest(method, path)
        if authorization is not None:
            connection.putheader("Authorization", authorization)
        for name, value in extra_headers:
            connection.putheader(name, value)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("TRADING_DASHBOARD_USER", "operador-á")
    monkeypatch.setenv("TRADING_DASHBOARD_PASSWORD", "contraseña:prueba-🔒")


def test_auth_protects_assets_apis_readiness_and_unknown_paths(tmp_path, credentials):
    with serving(tmp_path) as port:
        for path in ("/", "/operations.js", "/operations.css", "/api/status", "/api/performance",
                     "/api/trades", "/api/comparison", "/api/execution-quality", "/readyz", "/unknown"):
            status, headers, body = request(port, path)
            assert status == 401, path
            assert headers["WWW-Authenticate"] == 'Basic realm="Trading Lab", charset="UTF-8"'
            assert headers["Cache-Control"] == "no-store"
            assert json.loads(body) == {"error": "Autenticación requerida"}


@pytest.mark.parametrize("header", [
    "Basic", "Bearer token", "Basic !!!", "Basic YQ", "Basic YTo= extra",
    "Basic " + base64.b64encode(b"user-without-colon").decode(),
    "Basic " + base64.b64encode(b"\xff:\xfe").decode(),
    basic(password="incorrecta"), basic(user="otro"),
])
def test_malformed_or_wrong_credentials_are_denied_without_echo(tmp_path, credentials, header, capsys):
    with serving(tmp_path) as port:
        status, _, body = request(port, "/api/status", header)
        assert status == 401
        assert json.loads(body) == {"error": "Autenticación requerida"}
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_duplicate_authorization_headers_are_not_ambiguous(tmp_path, credentials):
    with serving(tmp_path) as port:
        status, _, _ = request(port, "/api/status", basic(), extra_headers=[("Authorization", basic())])
        assert status == 401


def test_valid_unicode_credentials_allow_read_only_panel_and_api(tmp_path, credentials):
    with serving(tmp_path) as port:
        for path in ("/", "/operations.js", "/operations.css", "/api/status", "/api/performance"):
            status, _, body = request(port, path, basic())
            assert status == 200, path
            assert body
        status, _, body = request(port, "/api/performance", basic())
        assert json.loads(body)["capital"]["target_usd"] == 1000
        assert request(port, "/api/status", basic().replace("Basic", "basic", 1))[0] == 200


@pytest.mark.parametrize("user,password", [(None, None), ("operator", None), (None, "secret"),
                                             ("operator", ""), ("", "secret"), ("user:name", "secret")])
def test_missing_or_invalid_config_fails_closed_except_generic_health(tmp_path, monkeypatch, user, password):
    for name, value in (("TRADING_DASHBOARD_USER", user), ("TRADING_DASHBOARD_PASSWORD", password)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    with serving(tmp_path) as port:
        for path in ("/", "/api/status", "/api/performance", "/readyz", "/unknown"):
            status, headers, body = request(port, path, basic())
            assert status == 503
            assert "WWW-Authenticate" not in headers
            assert json.loads(body) == {"error": "Servicio temporalmente no disponible"}
        status, _, body = request(port, "/healthz")
        assert status == 200
        assert json.loads(body) == {"status": "alive", "read_only": True}
        assert request(port, "/healthz", method="HEAD")[0] == 200
        assert request(port, "/api/status", basic(), method="POST")[0] == 503


def test_health_is_public_and_credentials_do_not_enable_mutations(tmp_path, credentials):
    with serving(tmp_path) as port:
        assert request(port, "/healthz?probe=1")[0] == 200
        assert request(port, "/healthz", "Basic invalid")[0] == 200
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert request(port, "/api/status", method=method)[0] == 401
            assert request(port, "/api/status", basic(), method=method)[0] == 405
        assert request(port, "/unknown", method="OPTIONS")[0] == 401
        assert request(port, "/healthz", method="POST")[0] == 401
        status, _, body = request(port, "/", method="HEAD")
        assert status == 401 and body == b""


def test_local_default_remains_accessible_without_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADING_DASHBOARD_USER", raising=False)
    monkeypatch.delenv("TRADING_DASHBOARD_PASSWORD", raising=False)
    with serving(tmp_path, require_auth=False) as port:
        assert request(port, "/")[0] == 200
        assert request(port, "/api/status")[0] == 200
        assert request(port, "/api/status", method="POST")[0] == 405


def test_cli_passes_explicit_auth_to_server(tmp_path, monkeypatch):
    captured = {}

    class FakeServer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def serve_forever(self):
            pass

    def fake_server(*args, **kwargs):
        captured.update(kwargs)
        return FakeServer()

    monkeypatch.setattr(service, "make_server", fake_server)
    service.main(["--data-dir", str(tmp_path), "--require-auth"])
    assert captured["require_auth"] is True
