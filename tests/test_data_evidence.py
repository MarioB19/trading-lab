"""Synthetic-only evidence capture, isolation and unchanged price semantics."""
import copy
import hashlib
import io
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from lab import bot, data
from lab import data_evidence as evidence


NOW = pd.Timestamp("2026-10-04T12:00:00Z")
BOOKS = {"success": True, "payload": [{"book": "btc_usd", "minimum_value": "5", "tick_size": "0.01"}]}


def test_recorder_is_opt_in_nested_and_digest_detects_changes():
    evidence.record_data("outside")
    with evidence.market_observation(observed_at_utc=NOW) as outer:
        evidence.record_data("before", value=1)
        with evidence.market_observation(observed_at_utc=NOW) as inner:
            evidence.record_data("inside", value=2)
        evidence.record_data("after", value=3)
    assert [r["kind"] for r in outer.records] == ["before", "after"]
    assert [r["kind"] for r in inner.records] == ["inside"]
    original = outer.digest
    evidence.record_data("outside_again")
    assert outer.digest == original
    outer.records[0]["value"] = 9
    assert outer.digest != original


def test_capture_errors_do_not_leak_exception_text_or_change_flow():
    with evidence.market_observation(observed_at_utc=NOW) as observation:
        evidence.record_data("unsupported", value=object())
        evidence.record_provider_error("example", "BTC/USD", ValueError("sensitive-token"))
    serialized = json.dumps(observation.records, allow_nan=False)
    assert "sensitive-token" not in serialized
    assert observation.records[0]["kind"] == "capture_error"
    assert observation.records[1]["error_type"] == "ValueError"


def _yahoo_result(*, adjusted=True, null_last=False):
    result = {"timestamp": [1790856000, 1790942400],
        "indicators": {"quote": [{"close": [100., None if null_last else 102.]}]},
        "events": {"dividends": {"fixture": {"amount": 2., "date": 1790856000}}},
        "meta": {"symbol": "SPY", "currency": "USD", "regularMarketPrice": 102.,
                 "regularMarketTime": 1790956800,
                 "currentTradingPeriod": {"regular": {"start": 1790942400, "end": 1790956800}}}}
    if adjusted:
        result["indicators"]["adjclose"] = [{"adjclose": [98., None if null_last else 102.]}]
    return result


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return copy.deepcopy(self.payload)

    def raise_for_status(self):
        pass


@pytest.mark.parametrize("adjusted,expected,basis", [
    (True, 98., "provider_adjusted_close"), (False, 100., "provider_close_split_adjusted")])
def test_yahoo_preserves_price_basis_and_captures_both_series_and_events(monkeypatch, adjusted, expected, basis):
    result = _yahoo_result(adjusted=adjusted)
    monkeypatch.setattr("requests.get", lambda *args, **kw: Response({"chart": {"result": [result]}}))
    without_recorder = data.yahoo_daily("SPY")
    with evidence.market_observation(observed_at_utc=NOW) as observation:
        prices = data.yahoo_daily("SPY")
    pd.testing.assert_series_equal(prices, without_recorder)
    assert prices.iloc[0] == expected
    record = observation.records[0]
    assert record["selected_price_basis"] == basis
    assert record["rows"][0][1:] == [100., 98. if adjusted else None]
    assert record["events"] == result["events"]
    assert record["corporate_action_ledger_verified"] is False
    assert record["payload_sha256"] == evidence._digest(result)


def test_yahoo_meta_fallback_is_labelled_without_overwriting_captured_null(monkeypatch):
    result = _yahoo_result(null_last=True)
    monkeypatch.setattr("requests.get", lambda *args, **kw: Response({"chart": {"result": [result]}}))
    with evidence.market_observation(observed_at_utc=NOW) as observation:
        prices = data.yahoo_daily("SPY")
    assert prices.iloc[-1] == 102.
    assert observation.records[0]["last_bar_filled_from_meta"] is True
    assert observation.records[0]["rows"][-1][1:] == [None, None]


def test_yahoo_failure_keeps_original_exception_and_records_only_type(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("sensitive-token")
    monkeypatch.setattr("requests.get", fail)
    with evidence.market_observation(observed_at_utc=NOW) as observation:
        with pytest.raises(TimeoutError, match="sensitive-token"):
            data.yahoo_daily("SPY")
    assert observation.records[0]["error_type"] == "TimeoutError"
    assert "sensitive-token" not in json.dumps(observation.records)


def test_crypto_records_winning_fallback_and_metadata_once_without_extra_requests(monkeypatch):
    calls = []

    class Exchange:
        def __init__(self, name):
            self.id = name
            self.markets = {"BTC/USD": {"id": "btc_usd", "quote": "USD", "active": None}}

        def fetch_ohlcv(self, symbol, timeframe, limit):
            calls.append((self.id, symbol))
            if self.id == "kraken":
                raise TimeoutError("fixture")
            return [[int(pd.Timestamp("2026-10-03").timestamp()*1000), 100, 101, 99, 100, 1]]

        def milliseconds(self):
            return int(NOW.timestamp()*1000)

    monkeypatch.setattr(bot, "make_exchange", Exchange)
    sc = {"data": {"source": "ccxt", "exchange": "kraken", "fallback_exchange": "bitso"},
          "universe": ["BTC", "ETH"], "quote": "USD"}
    with evidence.market_observation(observed_at_utc=NOW) as observation:
        prices = bot.fetch_prices("crypto", sc, NOW, [])
    assert len(calls) == 4
    assert prices.iloc[0].tolist() == [100., 100.]
    chosen = [r for r in observation.records if r["kind"] == "crypto_prices"]
    assert [r["source"] for r in chosen] == ["bitso", "bitso"]
    assert sum(r["kind"] == "provider_error" for r in observation.records) == 2
    listings = [r for r in observation.records if r["kind"] == "cached_markets"]
    assert len(listings) == 1
    assert listings[0]["books"][0]["active"] is None
    assert listings[0]["fresh_response_verified"] is False


def test_invalid_candles_are_recorded_before_source_fallback():
    exchange = SimpleNamespace(id="bitso", fetch_ohlcv=lambda *a, **kw: [[1, 2]], milliseconds=lambda: 100)
    with evidence.market_observation(observed_at_utc=NOW) as observation:
        with pytest.raises(ValueError):
            data.fetch_daily_closes(exchange, "BTC/USD")
    assert observation.records[0]["error_type"] == "ValueError"


def test_fresh_books_record_presence_without_inventing_listing_dates():
    with evidence.market_observation(observed_at_utc=NOW) as observation:
        evidence.record_bitso_available_books(BOOKS, received_at_utc=NOW)
        evidence.record_bitso_available_books({"success": False}, received_at_utc=NOW)
    record = observation.records[0]
    assert record["books"] == BOOKS["payload"]
    assert record["received_at_utc"] == NOW.isoformat()
    assert record["historical_listing_verified"] is False
    assert record["account_tradability_verified"] is False
    assert observation.records[1]["kind"] == "capture_error"


def _config():
    return {"mode": "paper", "sleeves": {
        "crypto": {"enabled": True, "strategy": "passive", "mix": {"BTC": 1.},
                   "universe": ["BTC"], "data": {"source": "ccxt"}},
        "stocks": {"enabled": True, "strategy": "passive", "mix": {"SPY": .6, "IEF": .4},
                   "universe": ["SPY", "IEF"], "data": {"source": "yahoo"}},
        "disabled": {"enabled": False}}}


def _frame(name):
    dates = pd.date_range("2026-10-01", periods=3 if name == "crypto" else 2)
    if name == "crypto":
        return pd.DataFrame({"BTC": [100.12345678901234, 101.00000000000001, 102.]}, index=dates)
    return pd.DataFrame({"SPY": [700.0000000000001, 701.], "IEF": [90., 91.]}, index=dates)


def _mock_collector(monkeypatch):
    requests = []
    monkeypatch.setattr("requests.get", lambda url, **kw: requests.append(url) or Response(BOOKS))

    def fetch(name, *args):
        frame = _frame(name)
        for asset in frame:
            evidence.record_data("crypto_prices", source="synthetic", symbol=asset + "/USD",
                                 price_basis="synthetic")
        return frame

    monkeypatch.setattr(bot, "fetch_prices", fetch)
    monkeypatch.setattr(bot, "make_broker", lambda *args, **kwargs: pytest.fail("must not construct a broker"))
    return requests


def test_daily_collector_replays_exact_inputs_without_brokers_and_hashes_full_payload(monkeypatch):
    calls = _mock_collector(monkeypatch)
    cfg = _config()
    original_cfg = copy.deepcopy(cfg)
    payload = evidence.collect_market_observation(cfg, now=NOW)
    assert calls == [evidence.BITSO_BOOKS_URL]
    assert cfg == original_cfg
    assert payload["status"] == "ok"
    assert payload["errors"] == []
    assert set(payload["panels"]) == {"crypto", "stocks"}
    for name, panel in payload["panels"].items():
        assert all(source["source"] == "synthetic" for source in panel["sources"].values())
        assert hashlib.sha256(panel["csv"].encode()).hexdigest() == panel["sha256"]
        restored = pd.read_csv(io.StringIO(panel["csv"]), index_col=0, parse_dates=True,
                               float_precision="round_trip", dtype=panel["dtypes"])
        assert restored.equals(_frame(name))
        assert payload["signal_replay"][name]["passed"] is True
        assert payload["signal_replay"][name]["execution_equivalence_verified"] is False
    without_digest = {key: value for key, value in payload.items() if key != "digest"}
    assert payload["digest"] == evidence._digest(without_digest)
    json.dumps(payload, allow_nan=False)


def test_provider_failure_and_missing_asset_return_partial_without_hiding_errors(monkeypatch):
    _mock_collector(monkeypatch)

    def fetch(name, sc, now, notes):
        if name == "crypto":
            evidence.record_provider_error("kraken", "BTC/USD", TimeoutError("secret"))
            return _frame(name)
        return _frame(name).drop(columns="IEF")

    monkeypatch.setattr(bot, "fetch_prices", fetch)
    payload = evidence.collect_market_observation(_config(), now=NOW)
    assert payload["status"] == "partial"
    assert payload["panels"]["stocks"]["missing_assets"] == ["IEF"]
    assert any(error["kind"] == "provider_error" for error in payload["errors"])
    assert "secret" not in json.dumps(payload)


def test_unavailable_sources_return_error_not_fake_empty_success(monkeypatch):
    _mock_collector(monkeypatch)

    def unavailable(*args, **kwargs):
        raise TimeoutError("secret")

    monkeypatch.setattr("requests.get", unavailable)
    monkeypatch.setattr(bot, "fetch_prices", unavailable)
    payload = evidence.collect_market_observation(_config(), now=NOW)
    assert payload["status"] == "error"
    assert payload["panels"] == {}
    assert len(payload["errors"]) == 3
    assert "secret" not in json.dumps(payload)


def test_stale_latest_bar_is_partial_and_holidays_are_explicitly_unverified(monkeypatch):
    _mock_collector(monkeypatch)
    monkeypatch.setattr(bot, "fetch_prices", lambda name, *args: _frame(name).iloc[:1])
    payload = evidence.collect_market_observation(_config(), now=NOW)
    assert payload["status"] == "partial"
    assert payload["panels"]["stocks"]["exchange_holiday_calendar_verified"] is False
    assert any(e.get("possible_exchange_holiday") for e in payload["errors"])


def test_signal_change_is_reported_as_mismatch(monkeypatch):
    _mock_collector(monkeypatch)
    real = bot.compute_targets
    calls = 0

    def differing(sc, frame):
        nonlocal calls
        target, table = real(sc, frame)
        calls += 1
        if calls % 2 == 0:
            target.iloc[0] += .01
        return target, table

    monkeypatch.setattr(bot, "compute_targets", differing)
    payload = evidence.collect_market_observation(_config(), now=NOW)
    assert payload["status"] == "partial"
    assert all(not value["passed"] for value in payload["signal_replay"].values())


def test_absent_source_records_are_never_presented_as_fully_captured(monkeypatch):
    _mock_collector(monkeypatch)
    monkeypatch.setattr(bot, "fetch_prices", lambda name, *args: _frame(name))
    payload = evidence.collect_market_observation(_config(), now=NOW)
    assert payload["status"] == "partial"
    assert all(e["kind"] == "source_evidence_missing" for e in payload["errors"])
    assert payload["panels"]["crypto"]["sources"]["BTC"]["source"] is None
