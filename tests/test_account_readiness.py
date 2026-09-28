"""Offline account fixtures only; no real credentials or private network calls."""
from __future__ import annotations

import hashlib
import hmac
import json
import re

import pytest
import requests

from lab import account_readiness as readiness
from lab import brokers, data
from lab.journal import JournalBroker
from lab.storage import SQLiteStore


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.text = "synthetic"
    def json(self):
        return self.body


def credentials(broker):
    return dict(zip(readiness.CREDENTIALS[broker], ("synthetic-key", "synthetic-secret")))


def alpaca_account(**overrides):
    return {"id": "11111111-2222-3333-4444-555555555555", "status": "ACTIVE", "cash": "500.10",
            "currency": "USD", "multiplier": "1", "trading_blocked": False, "account_blocked": False,
            "trade_suspended_by_user": False, "shorting_enabled": False,
            "account_number": "PRIVATE-ACCOUNT-NUMBER", "email": "private@example.invalid", **overrides}


def test_offline_never_calls_network_or_loads_operational_credentials(monkeypatch):
    monkeypatch.setattr(requests, "Session", lambda: pytest.fail("network session in offline mode"))
    for broker in ("alpaca", "bitso"):
        report = readiness.inspect_account(broker, "real", environ={"ALPACA_KEY_ID": "operational", "BITSO_API_KEY": "operational"})
        assert report["status"] == "not_connected"
        assert not report["authentication"]["credentials_present"]
        assert not report["requests"] and not report["live_authorized"]
        assert report["missing_credentials"] == list(readiness.CREDENTIALS[broker])


def test_connect_missing_credentials_never_sends_a_request():
    report = readiness.inspect_account("alpaca", "paper", connect=True, environ={},
                                      transport=lambda *a, **k: pytest.fail("missing credentials request"))
    assert report["status"] == "missing_credentials"
    assert not report["read_only_connection_ready"]


def test_bitso_paper_is_not_silently_production():
    report = readiness.inspect_account("bitso", "paper", connect=True, environ=credentials("bitso"),
                                      transport=lambda *a, **k: pytest.fail("wrong environment"))
    assert report["status"] == "unsupported_environment" and not report["requests"]


def test_alpaca_only_gets_fixed_endpoints_and_filters_personal_fields():
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/account"):
            return Response(alpaca_account())
        return Response([{"symbol": "SPY", "qty": "2.5", "market_value": "1250", "qty_available": "2.5",
                          "asset_id": "PRIVATE-ASSET-ID", "email": "private@example.invalid"}])
    report = readiness.inspect_account("alpaca", "real", connect=True, environ=credentials("alpaca"), transport=get)
    assert [url for url, _ in calls] == ["https://api.alpaca.markets/v2/account", "https://api.alpaca.markets/v2/positions"]
    assert all(kw["allow_redirects"] is False and kw["timeout"] == 20 for _, kw in calls)
    assert report["status"] == "connected_read_only"
    assert report["holdings"]["nonzero_count"] == 1
    assert report["holdings"]["items"][0]["owned_by_bot"] is False
    assert not report["capabilities"]["can_send_orders"] and not report["ready_for_trading"]
    assert not report["capabilities"]["credential_read_only_verified"]
    encoded = json.dumps(report)
    for secret in ("synthetic-key", "synthetic-secret", "PRIVATE-ACCOUNT-NUMBER", "private@example.invalid", alpaca_account()["id"]):
        assert secret not in encoded
    assert all(request["method"] == "GET" and "orders" not in request["path"] for request in report["requests"])


def test_alpaca_oauth_read_token_does_not_use_key_headers():
    def get(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer synthetic-token"
        assert "APCA-API-KEY-ID" not in kwargs["headers"]
        return Response(alpaca_account() if url.endswith("/account") else [])
    report = readiness.inspect_account("alpaca", "paper", connect=True,
        environ={readiness.ALPACA_OAUTH: "synthetic-token"}, transport=get)
    assert report["authentication"]["method"] == "oauth_token" and report["read_only_connection_ready"]
    assert "synthetic-token" not in json.dumps(report)


def test_bitso_v2_signature_and_stable_client_id():
    calls = []
    def get(url, **kwargs):
        header = kwargs["headers"]["Authorization"]
        key, nonce, signature = header.removeprefix("Bitso ").split(":")
        assert key == "synthetic-key" and re.fullmatch(r"\d{19}", nonce)
        path = url.removeprefix("https://bitso.com")
        expected = hmac.new(b"synthetic-secret", (nonce + "GET" + path).encode(), hashlib.sha256).hexdigest()
        assert signature == expected
        calls.append(url)
        payload = ({"client_id": "12345678", "status": "active", "preferred_currency": "mxn",
                    "first_name": "PRIVATE_NAME", "cellphone_number_stored": "PRIVATE_PHONE"}
                   if "account_status" in url else {"balances": [
                       {"currency": "usd", "total": "100", "available": "90", "locked": "10"},
                       {"currency": "btc", "total": "0.5", "available": "0.5", "locked": "0"},
                       {"currency": "eth", "total": "0", "available": "0", "locked": "0"}]})
        return Response({"success": True, "payload": payload})
    report = readiness.inspect_account("bitso", "real", connect=True, environ=credentials("bitso"), transport=get)
    assert len(calls) == 2 and report["status"] == "connected_read_only"
    assert report["account"]["identity"]["key"] == readiness.stable_account_key("bitso real", "12345678")
    assert report["holdings"]["nonzero_count"] == 2 and report["account"]["available_usd"] == "90"
    assert not report["holdings"]["adopted_by_bot"]
    assert all(value not in json.dumps(report) for value in ("12345678", "PRIVATE_NAME", "PRIVATE_PHONE", "synthetic-secret"))


def test_bitso_balance_only_permission_reports_unknown_identity():
    def get(url, **kwargs):
        if "account_status" in url:
            return Response({"message": "secret synthetic-key"}, status=403)
        return Response({"success": True, "payload": {"balances": [
            {"currency": "mxn", "total": "100", "available": "100", "locked": "0"}]}})
    report = readiness.inspect_account("bitso", "real", connect=True, environ=credentials("bitso"), transport=get)
    assert report["authentication"]["verified"]
    assert report["capabilities"]["holdings_read"]
    assert not report["account"]["identity"]["verified"] and not report["read_only_connection_ready"]
    assert report["account"]["available_usd"] is None
    assert "synthetic-key" not in json.dumps(report)


@pytest.mark.parametrize("kind", ("redirect", "unauthorized", "ratelimit", "timeout", "invalid_json", "malformed"))
def test_failures_cannot_be_reported_as_readiness_or_leak_payload(kind):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if kind == "timeout":
            raise requests.Timeout("LEAK_SYNTHETIC_SECRET")
        if kind == "invalid_json":
            class Broken(Response):
                def json(self):
                    raise ValueError("LEAK_SYNTHETIC_SECRET")
            return Broken(None)
        if kind == "malformed":
            return Response({"id": "LEAK_SYNTHETIC_SECRET", "cash": "NaN"})
        return Response({"message": "LEAK_SYNTHETIC_SECRET"}, {"redirect": 302, "unauthorized": 401, "ratelimit": 429}[kind])
    report = readiness.inspect_account("alpaca", "real", connect=True, environ=credentials("alpaca"), transport=get)
    assert report["status"] == "partial_or_failed_connection" and not report["ready_for_trading"]
    assert "LEAK_SYNTHETIC_SECRET" not in json.dumps(report)
    if kind in ("unauthorized", "ratelimit"):
        assert len(calls) == 1


def test_short_and_margin_capability_never_authorize_trading():
    def get(url, **kwargs):
        return Response(alpaca_account(multiplier="2", cash="-20") if url.endswith("/account") else [{"symbol": "SPY", "qty": "-1"}])
    report = readiness.inspect_account("alpaca", "paper", connect=True, environ=credentials("alpaca"), transport=get)
    assert report["read_only_connection_ready"] and not report["ready_for_trading"]
    assert any("cortas" in reason for reason in report["blockers"])
    assert any("margen" in reason for reason in report["blockers"])


def test_invalid_quantities_and_missing_identity_fail_closed():
    def get(url, **kwargs):
        return Response(alpaca_account(id=None) if url.endswith("/account") else [{"symbol": "SPY", "qty": "Infinity"}])
    report = readiness.inspect_account("alpaca", "paper", connect=True, environ=credentials("alpaca"), transport=get)
    assert not report["read_only_connection_ready"] and not report["account"]["identity"]["verified"]
    assert report["holdings"]["items"] == []


@pytest.mark.parametrize("bad_quantity", ("1e999999999", "1e-999999999", "sNaN", "Infinity"))
def test_extreme_numeric_response_is_sanitized(bad_quantity):
    def get(url, **kwargs):
        return Response(alpaca_account() if url.endswith("/account") else [{"symbol": "SPY", "qty": bad_quantity}])
    report = readiness.inspect_account("alpaca", "paper", connect=True, environ=credentials("alpaca"), transport=get)
    assert not report["read_only_connection_ready"]
    assert report["errors"] == [{"endpoint": "positions", "kind": "invalid_position_row"}]
    assert bad_quantity not in json.dumps(report)


@pytest.mark.parametrize("broker", ("alpaca", "bitso"))
def test_null_holdings_response_never_counts_as_verified_empty(broker):
    def get(url, **kwargs):
        if broker == "alpaca":
            return Response(alpaca_account() if url.endswith("/account") else None)
        return Response({"success": True, "payload": {"client_id": "12345", "status": "active"}
                         if "account_status" in url else None})
    report = readiness.inspect_account(broker, "real", connect=True, environ=credentials(broker), transport=get)
    assert report["account"]["identity"]["verified"]
    assert not report["capabilities"]["holdings_read"] and not report["read_only_connection_ready"]


def test_default_session_disables_implicit_credentials_and_closes(monkeypatch):
    class Session:
        trust_env, closed = True, False
        def get(self, url, **kwargs):
            assert self.trust_env is False and kwargs["allow_redirects"] is False
            return Response(alpaca_account() if url.endswith("/account") else [])
        def close(self):
            self.closed = True
    session = Session()
    monkeypatch.setattr(requests, "Session", lambda: session)
    report = readiness.inspect_account("alpaca", "paper", connect=True, environ=credentials("alpaca"))
    assert report["read_only_connection_ready"] and session.closed


def test_broker_identity_survives_key_rotation_and_separates_environments(monkeypatch):
    monkeypatch.setenv("ALPACA_KEY_ID", "old-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "synthetic")
    monkeypatch.setattr(brokers.AlpacaBroker, "_req", lambda *a, **k: alpaca_account())
    old = brokers.AlpacaBroker(paper=True)
    monkeypatch.setenv("ALPACA_KEY_ID", "rotated-key")
    current = brokers.AlpacaBroker(paper=True)
    real = brokers.AlpacaBroker(paper=False)
    assert old.account_key == current.account_key != real.account_key
    assert "old-key" not in old.account_key and "rotated-key" not in current.account_key
    monkeypatch.setattr(brokers.AlpacaBroker, "_req", lambda *a, **k: {})
    with pytest.raises(ValueError, match="identificador"):
        brokers.AlpacaBroker(paper=True)


def test_bitso_broker_overrides_v1_nonce_and_requires_provider_identity(monkeypatch):
    class Exchange:
        apiKey, secret = "synthetic-key", "synthetic-secret"
        client_id = "12345"
        def load_markets(self):
            pass
        def private_get_account_status(self):
            assert re.fullmatch(r"\d{19}", self.nonce())
            return {"success": True, "payload": {"client_id": self.client_id}}
    exchange = Exchange()
    monkeypatch.setattr(data, "make_exchange", lambda *a: exchange)
    first = brokers.BitsoBroker()
    exchange.apiKey = "rotated-key"
    assert brokers.BitsoBroker().account_key == first.account_key
    exchange.client_id = None
    with pytest.raises(RuntimeError, match="identidad estable"):
        brokers.BitsoBroker()


def test_legacy_ledger_without_state_cannot_allocate_again(tmp_path):
    class Broker:
        name, min_order_value, account_identity_version = "alpaca paper", 1, 1
        account_key = readiness.stable_account_key(name, "account-123")
        def cash(self):
            pytest.fail("cash read before rejecting legacy identity")
    store = SQLiteStore(tmp_path / "test.sqlite3")
    legacy = "ledger:alpaca paper:abcdef1234567890:paper:stocks"
    store.write_document(legacy, {"cash": 500, "positions": {}, "capital_base": 500})
    with pytest.raises(RuntimeError, match="legacy"):
        JournalBroker(Broker(), store, "stocks", "paper", {"capital": 500}, {})
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


def test_legacy_guard_is_scoped_to_provider_environment(tmp_path):
    class Broker:
        name, min_order_value, account_identity_version = "alpaca paper", 1, 1
        account_key = readiness.stable_account_key(name, "account-123")
        def cash(self):
            return 500
    store = SQLiteStore(tmp_path / "test.sqlite3")
    store.write_document("ledger:alpaca real:oldhash:live:stocks", {"cash": 500, "positions": {}, "capital_base": 500})
    result = JournalBroker(Broker(), store, "stocks", "paper", {"capital": 500}, {})
    assert result.cash() == 500


def test_two_keys_same_account_share_cash_allocation_and_do_not_adopt_positions(tmp_path):
    class Broker:
        name, min_order_value, account_identity_version = "alpaca paper", 1, 1
        account_key = readiness.stable_account_key(name, "same-account")
        def cash(self): return 500
        def positions(self): return {"SPY": 100}
    store = SQLiteStore(tmp_path / "test.sqlite3")
    a = JournalBroker(Broker(), store, "one", "paper", {"capital": 400}, {})
    b = JournalBroker(Broker(), store, "two", "paper", {"capital": 400}, {})
    assert a.cash() == 400 and b.cash() == 100
    assert a.positions() == b.positions() == {}


def test_cli_has_no_live_switch_and_does_not_write_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for names in readiness.CREDENTIALS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(readiness.ALPACA_OAUTH, raising=False)
    monkeypatch.setattr(requests, "Session", lambda: pytest.fail("offline CLI connected"))
    assert readiness.main(["--broker", "alpaca", "--environment", "paper"]) == 0
    assert readiness.main(["--broker", "bitso", "--environment", "real", "--connect"]) == 2
    with pytest.raises(SystemExit):
        readiness.main(["--broker", "alpaca", "--environment", "paper", "--live"])
    assert list(tmp_path.iterdir()) == []
    assert "missing_credentials" in capsys.readouterr().out
