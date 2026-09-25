"""Pruebas que protegen de los errores que hacen que un backtest mienta o un bot pierda dinero por un bug.

    python -m pytest -q
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.backtest import simulate
from lab.btc_bot import DEFAULT_CONFIG, PaperBroker, LiveBroker, decide_and_trade, main, replay
from lab.risk import RiskLimits, check_prices
from lab.strategies import PARAM_GRID, compute


def synthetic(n=1500, seed=0, drift=0.0005, vol=0.035):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.Series(100 * np.exp(np.cumsum(r)), index=idx, name="close")


def cfg(**over):
    import copy
    c = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in over.items():
        c[k] = {**c[k], **v} if isinstance(v, dict) else v
    return c


# ------------------------------------------------------------ sin mirar al futuro
@pytest.mark.parametrize("family", [f for f in PARAM_GRID if f != "ml_model"] + ["buy_hold"])
def test_no_lookahead(family):
    close = synthetic()
    params_list = PARAM_GRID.get(family, [{}])
    for params in params_list:
        full = compute(family, close, params)
        for cut in (500, 900, 1300):
            part = compute(family, close.iloc[:cut], params)
            pd.testing.assert_series_equal(full.iloc[:cut], part, check_names=False)


def test_no_lookahead_ml():
    close = synthetic(900)
    p = {"model": "logistic", "min_train": 300, "retrain_every": 40}
    full = compute("ml_model", close, p)
    part = compute("ml_model", close.iloc[:700], p)
    pd.testing.assert_series_equal(full.iloc[:700], part, check_names=False)


# ------------------------------------------------------------ motor de backtest
def test_decision_applies_next_day():
    idx = pd.date_range("2024-01-01", periods=20, freq="D")
    close = pd.Series(100.0, index=idx)
    close.iloc[10:] = 110.0  # +10% el día 10
    knows_jump = pd.Series(0.0, index=idx)
    knows_jump.iloc[10] = 1.0  # solo "sabe" del salto el mismo día
    bt = simulate(close, knows_jump, cost=0.0)
    assert bt["ret"].sum() == pytest.approx(0.0)  # no puede capturarlo
    before = pd.Series(0.0, index=idx)
    before.iloc[9] = 1.0  # decidido la víspera: sí lo captura
    assert simulate(close, before, cost=0.0)["ret"].sum() == pytest.approx(0.10)


def test_costs_charged_per_trade():
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    close = pd.Series(100.0, index=idx)
    tgt = pd.Series([0, 1, 1, 0, 0, 1, 1, 1, 0, 0], index=idx, dtype=float)
    bt = simulate(close, tgt, cost=0.002)
    assert bt["turnover"].sum() == pytest.approx(4.0)
    assert (1 + bt["ret"]).prod() == pytest.approx((1 - 0.002) ** 4, rel=1e-3)


def test_buy_hold_tracks_price_without_costs():
    close = synthetic(400)
    bt = simulate(close, compute("buy_hold", close), cost=0.0)
    eq = (1 + bt["ret"]).cumprod()
    assert eq.iloc[-1] == pytest.approx(close.iloc[-1] / close.iloc[0], rel=1e-9)


# ------------------------------------------------------------ bot == backtest
def test_bot_replay_matches_backtest():
    close = synthetic(1200, seed=3)
    c = cfg(risk={"max_order_value": 1e12, "max_drawdown_kill": 0.99})
    df = replay(c, 400, closes=close)
    gap = (df["equity_after"].astype(float) / df["backtest_equity"] - 1).abs().max()
    assert gap < 0.01, gap


# ------------------------------------------------------------ seguridad del bot
def _state(cash=10_000.0, base=0.0, peak=0.0):
    return {"last_candle": None, "peak_equity": peak, "kill_switch": False,
            "paper": {"cash": cash, "base": base}}


def _now(close):
    return close.index[-1] + pd.Timedelta(days=1, minutes=5)


def test_skips_same_candle_twice():
    close = synthetic(600)
    st = _state()
    c = cfg()
    b = PaperBroker(st, 0.001, 0.001)
    decide_and_trade(c, close, b, st, _now(close), float(close.iloc[-1]), "paper")
    row = decide_and_trade(c, close, b, st, _now(close), float(close.iloc[-1]), "paper")
    assert row["action"] == "skip"


def test_stale_data_blocks_trading():
    close = synthetic(600)
    st = _state()
    row = decide_and_trade(cfg(), close, PaperBroker(st, 0.001, 0.001), st,
                           close.index[-1] + pd.Timedelta(days=4), float(close.iloc[-1]), "paper")
    assert row["action"] == "no_trade" and "viejos" in row["notes"]
    assert st["paper"]["base"] == 0


def test_price_jump_only_allows_reducing():
    close = synthetic(600, drift=0.003, vol=0.01)
    close.iloc[-1] *= 1.4
    blocking, caution = check_prices(close, RiskLimits(), _now(close))
    assert not blocking and caution
    st = _state()
    row = decide_and_trade(cfg(), close, PaperBroker(st, 0.001, 0.001), st, _now(close),
                           float(close.iloc[-1]), "paper")
    assert row["action"] == "hold" and st["paper"]["base"] == 0  # no compra con un dato raro


def test_kill_switch_sells_everything():
    close = synthetic(600, drift=0.003, vol=0.01)  # tendencia alcista: la regla querría estar dentro
    px = float(close.iloc[-1])
    st = _state(cash=0.0, base=6_000 / px, peak=10_000.0)  # capital 6,000 vs máximo 10,000 (−40%)
    row = decide_and_trade(cfg(), close, PaperBroker(st, 0.001, 0.001), st, _now(close), px, "paper")
    assert row["action"] == "sell" and st["kill_switch"] and st["paper"]["base"] == pytest.approx(0)
    st["last_candle"] = None
    row = decide_and_trade(cfg(), close, PaperBroker(st, 0.001, 0.001), st, _now(close), px, "paper")
    assert row["target"] == 0 and st["paper"]["base"] == pytest.approx(0)  # sigue apagado


def test_live_requires_triple_confirmation(monkeypatch, tmp_path):
    monkeypatch.delenv("CONFIRMO_DINERO_REAL", raising=False)
    conf = tmp_path / "config.yaml"
    conf.write_text("mode: paper\n")
    assert main(["--config", str(conf), "--live"]) == 2
    conf.write_text("mode: live\n")
    assert main(["--config", str(conf), "--live"]) == 2  # falta CONFIRMO_DINERO_REAL=si


class FakeExchange:
    """Imita la interfaz de ccxt que usa LiveBroker."""

    def __init__(self, price, quote=20_000.0, base=0.0):
        self.price, self.quote, self.base, self.orders = price, quote, base, []

    def market(self, symbol):
        return {"base": "BTC", "quote": "MXN", "limits": {"cost": {"min": 10.0}}}

    def fetch_balance(self):
        return {"total": {"BTC": self.base, "MXN": self.quote}, "free": {"BTC": self.base, "MXN": self.quote}}

    def fetch_ticker(self, symbol):
        return {"last": self.price, "close": self.price, "bid": self.price * 0.999, "ask": self.price * 1.001}

    def amount_to_precision(self, symbol, a):
        return f"{a:.8f}"

    def price_to_precision(self, symbol, p):
        return f"{p:.2f}"

    def create_order(self, symbol, type_, side, amount, price):
        self.orders.append((type_, side, amount, price))
        if side == "buy":
            self.quote -= amount * price
            self.base += amount
        else:
            self.quote += amount * price
            self.base -= amount
        return {"id": str(len(self.orders)), "status": "closed", "filled": amount, "average": price,
                "fee": {"cost": amount * price * 0.001, "currency": "MXN"}}

    def fetch_order(self, oid, symbol):
        t, side, amount, price = self.orders[int(oid) - 1]
        return {"id": oid, "status": "closed", "filled": amount, "average": price}

    def cancel_order(self, oid, symbol):
        return {}


def test_live_broker_respects_capital_cap():
    close = synthetic(600, drift=0.003, vol=0.01)
    px = float(close.iloc[-1])
    ex = FakeExchange(px, quote=20_000.0)
    c = cfg(capital={"max_capital": 5_000}, risk={"max_order_value": 1e9})
    st = _state()
    broker = LiveBroker(ex, "BTC/MXN", 0.003, 1)
    row = decide_and_trade(c, close, broker, st, _now(close), px, "live")
    assert row["action"] == "buy"
    _, side, amount, limit = ex.orders[0]
    assert side == "buy" and limit > px  # orden límite con tope de precio
    assert amount * px <= 5_000 * 1.0001  # nunca más que el capital asignado
