"""Sombra de ejecución H7c: cotiza sin tocar la ejecución y aplica la regla preregistrada."""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

from lab import bot, exchange_shadow as xs
from lab.brokers import SimBroker
from lab.storage import SQLiteStore


BOOK = {"bids": [(99.0, 1.0), (98.0, 10.0)], "asks": [(101.0, 1.0), (102.0, 10.0)]}


def test_walk_measures_cost_against_own_mid_for_both_sides():
    small = xs.walk(BOOK, "buy", 50.0)
    assert small["mid"] == 100.0 and small["spread_bps"] == pytest.approx(200.0)
    assert small["impact_bps"] == pytest.approx(100.0) and small["depth_ok"]
    deep = xs.walk(BOOK, "buy", 305.0)  # 101 del primer nivel y 204 del segundo
    avg = 305.0 / (1 + 204.0 / 102.0)
    assert deep["impact_bps"] == pytest.approx((avg / 100 - 1) * 1e4)
    sell = xs.walk(BOOK, "sell", 50.0)
    assert sell["impact_bps"] == pytest.approx(100.0)
    thin = xs.walk({"bids": [(99.0, 0.1)], "asks": [(101.0, 0.1)]}, "buy", 100.0)
    assert not thin["depth_ok"]
    with pytest.raises(ValueError):
        xs.walk({"bids": [(101.0, 1)], "asks": [(100.0, 1)]}, "buy", 10.0)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, blocked=()):
        self.blocked, self.calls = set(blocked), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), timeout))
        assert timeout and timeout <= 10
        if "binance" in url:
            if "binance" in self.blocked:
                return FakeResponse({}, 451)
            return FakeResponse({"bids": [["99", "5"]], "asks": [["101", "5"]]})
        if "okx" in url:
            return FakeResponse({"code": "0", "data": [{"bids": [["99.5", "5", "0", "1"]],
                                                        "asks": [["100.5", "5", "0", "1"]]}]})
        if "bitso" in url:
            return FakeResponse({"payload": {"bids": [{"price": "98", "amount": "5"}],
                                             "asks": [{"price": "102", "amount": "5"}]}})
        raise AssertionError(url)


def test_quotes_parse_each_venue_and_never_raise():
    s = FakeSession(blocked={"binance"})
    ok = xs.quote("okx", "BTC", "buy", 50.0, session=s, ref_price=100.0)
    assert ok["status"] == "ok" and ok["impact_bps"] == pytest.approx(50.0)
    assert ok["cost_bps"]["taker"] == pytest.approx(60.0) and ok["mid_gap_bps"] == pytest.approx(0.0)
    assert s.calls[-1][1] == {"instId": "BTC-USDT", "sz": 100}
    blocked = xs.quote("binance", "BTC", "buy", 50.0, session=s)
    assert blocked["status"] == "error" and blocked["error"] == "http 451"
    bitso = xs.quote("bitso", "ETH", "sell", 50.0, session=s)
    assert bitso["status"] == "ok" and s.calls[-1][1]["book"] == "eth_usd"


def test_panel_respects_budget_and_records_every_venue():
    sh = xs.ExchangeShadow({"enabled": True, "venues": ["binance", "okx"]}, session=FakeSession())
    p = sh.panel("2026-11-03 00:00", ["BTC", "ETH"])
    venues = {(r["venue"], r["asset"], r.get("side")) for r in p["rows"]}
    assert ("bitso", "ETH", "sell") in venues and ("binance", "BTC", "buy") in venues and ("okx", "ETH", "buy") in venues
    import threading
    lock, t = threading.Lock(), [-100]

    def clock():
        with lock:
            t[0] += 100
            return t[0]
    sh2 = xs.ExchangeShadow({"enabled": True, "venues": ["okx"], "panel_budget_s": 50}, session=FakeSession())
    late = sh2.panel("x", ["BTC", "ETH"], clock=clock)
    assert any(r["status"] == "skipped" for r in late["rows"])


def panel(n=900, seed=1, assets=("BTC", "ETH", "AAA", "BBB", "CCC", "DDD")):
    rng = np.random.default_rng(seed)
    r = rng.normal(np.linspace(0.002, -0.001, len(assets)), 0.04, size=(n, len(assets)))
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=list(assets))


def _run(shadow):
    sc = copy.deepcopy(bot.DEFAULT_CONFIG["sleeves"]["crypto"])
    sc["universe"] = ["BTC", "ETH", "AAA", "BBB", "CCC", "DDD"]
    P = panel()
    st = {}
    broker = SimBroker(st.setdefault("ledger", {"cash": 300.0, "positions": {}}), 0.001, 0.002, 1.0)
    r = bot.run_sleeve("crypto", sc, P, broker, st, P.index[-1] + pd.Timedelta(days=1, minutes=10), "paper",
                       pd.Series(dtype=float), 0.40, shadow=shadow)
    return r, st


class Exploding:
    def __init__(self):
        self.calls = []

    def before_order(self, *args):
        self.calls.append(args)
        raise RuntimeError("la sombra falla")


def test_shadow_never_changes_or_stops_execution():
    base, st0 = _run(None)
    boom = Exploding()
    shadowed, st1 = _run(boom)
    assert base["trades"] and len(boom.calls) == len(base["trades"])
    strip = lambda rows: [{k: v for k, v in t.items()} for t in rows]  # noqa: E731
    assert strip(shadowed["trades"]) == strip(base["trades"])
    assert st0["ledger"] == st1["ledger"]
    sh = xs.ExchangeShadow({"enabled": True, "venues": ["okx"]}, session=FakeSession())
    quoted, st2 = _run(sh)
    assert st2["ledger"] == st0["ledger"] and len(sh.orders) == len(base["trades"])
    first = sh.orders[0]
    assert first["run_at_utc"] == base["trades"][0]["run_at_utc"] and first["quotes"][0]["status"] == "ok"


def _trade(run_at, asset, side, value, cost):
    return {"run_at_utc": run_at, "sleeve": "crypto", "asset": asset, "side": side, "value": value,
            "cost_bps": cost, "status": "filled"}


def _order(run_at, asset, side, cost_venue, status="ok"):
    q = {"venue": "okx", "status": status, "depth_ok": True, "cost_bps": {"taker": cost_venue}}
    return {"run_at_utc": run_at, "asset": asset, "side": side, "quotes": [q]}


def test_summary_applies_preregistered_rule():
    days = [f"2026-11-{d:02d} 00:00" for d in range(3, 28)]
    trades = [_trade(d, "BTC", "buy", 40.0, 60.0) for d in days]
    orders = [_order(d, "BTC", "buy", 15.0) for d in days]
    early = xs.summarize(orders, trades, now_utc="2026-11-20 00:00", reps=500)
    assert early["venues"]["okx"]["verdict"] == "en curso"
    f = early["venues"]["okx"]["by_fee"]["taker"]
    assert f["mean_diff_bps"] == pytest.approx(45.0) and f["n_orders"] == len(days)
    done = xs.summarize(orders, trades, now_utc="2026-12-02 01:00", reps=500)
    assert done["venues"]["okx"]["verdict"] == "ventaja medida"
    close = [_order(d, "BTC", "buy", 50.0) for d in days]
    assert xs.summarize(close, trades, now_utc="2026-12-02 01:00", reps=500)["venues"]["okx"]["verdict"] == "sin ventaja clara"
    flaky = orders + [_order("2026-11-28 00:00", "ETH", "buy", 15.0, status="error")] * 3
    assert xs.summarize(flaky, trades, now_utc="2026-12-02 01:00", reps=500)["venues"]["okx"]["verdict"] == \
        "no medible desde el servidor"
    few = xs.summarize(orders[:5], trades, now_utc="2026-12-02 01:00", reps=500)
    assert few["venues"]["okx"]["verdict"] == "en curso"
    assert xs.summarize(orders[:5], trades, now_utc="2026-12-31 00:00", reps=500)["venues"]["okx"]["verdict"] == "falta dato"


def test_events_round_trip_and_probe_runs_once(tmp_path):
    store = SQLiteStore(tmp_path / "trading.sqlite3")
    assert not store.has_event("venue_panel")
    sh = xs.ExchangeShadow({"enabled": True, "venues": ["okx"]}, session=FakeSession())
    sh.before_order("crypto", "2026-11-03 00:00", "BTC", "buy", 0.5, 100.0)
    bot.record_shadow(store, sh, run_at="2026-11-03 00:00", panel_universe=["BTC"], trigger="probe")
    assert store.has_event("venue_panel") and sh.orders == [] and sh.panels == []
    rows = store.events_of_kind("exchange_shadow")
    assert rows[0]["payload"]["quotes"][0]["venue"] == "okx"
    assert store.events_of_kind("venue_panel")[0]["payload"]["trigger"] == "probe"
    json.dumps(store.events_of_kind("venue_panel"))


def test_service_reader_serves_shadow_with_summary(tmp_path):
    from lab.service import DATABASE_NAME, Reader
    store = SQLiteStore(tmp_path / DATABASE_NAME)
    store.commit_run({"sleeves": {}}, [_trade("2026-11-03 00:00", "BTC", "buy", 40.0, 60.0)], [], {"sleeves": {}})
    store.record_event("exchange_shadow", _order("2026-11-03 00:00", "BTC", "buy", 15.0))
    store.record_event("venue_panel", {"run_at_utc": "2026-11-03 00:00", "trigger": "probe", "usd": 100, "rows": []})
    out = Reader(tmp_path).exchange_shadow()
    okx = out["summary"]["venues"]["okx"]
    assert okx["by_fee"]["taker"]["mean_diff_bps"] == pytest.approx(45.0) and okx["verdict"] == "en curso"
    assert out["panels"][0]["trigger"] == "probe" and len(out["orders"]) == 1
