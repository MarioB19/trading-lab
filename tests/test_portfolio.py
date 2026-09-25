"""Pruebas del portafolio multi-activo y del bot diario."""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from lab import bot
from lab.brokers import AlpacaBroker, SimBroker
from lab.portfolio import (PortfolioParams, cap_weights, listed_universe, simulate_portfolio,
                           target_weights)


def panel(n=900, seed=1, assets=("BTC", "ETH", "AAA", "BBB", "CCC", "DDD")):
    rng = np.random.default_rng(seed)
    drift = np.linspace(0.002, -0.001, len(assets))
    r = rng.normal(drift, 0.04, size=(n, len(assets)))
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    P = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=list(assets))
    P.iloc[:400, 5] = np.nan  # un activo que "sale a la venta" después
    return P


def crypto_cfg(**over):
    c = copy.deepcopy(bot.DEFAULT_CONFIG["sleeves"]["crypto"])
    c["universe"] = ["BTC", "ETH", "AAA", "BBB", "CCC", "DDD"]
    c.update(over)
    return c


# ------------------------------------------------------------ estrategia
def test_target_weights_no_lookahead():
    P = panel()
    p = PortfolioParams()
    full = target_weights(P, listed_universe(P), p)
    for cut in (450, 700):
        part = target_weights(P.iloc[:cut], listed_universe(P.iloc[:cut]), p)
        pd.testing.assert_frame_equal(full.iloc[:cut], part)


def test_weights_respect_limits():
    P = panel()
    p = PortfolioParams(top_k=3, max_weight=0.4)
    W = target_weights(P, listed_universe(P), p)
    assert (W >= 0).all().all()
    assert (W.sum(axis=1) <= 1 + 1e-9).all()
    assert (W.max(axis=1) <= 0.4 + 1e-9).all()
    assert ((W > 0).sum(axis=1) <= 3).all()
    assert (W.iloc[:400]["DDD"] == 0).all()  # no se compra lo que no existía


def test_cap_weights_redistributes():
    w = cap_weights(np.array([0.7, 0.2, 0.1]), 0.4)
    assert w.max() <= 0.4 + 1e-12 and w.sum() == pytest.approx(1.0)


def test_regime_filter_blocks_altcoins():
    P = panel()
    P["BTC"] = 100 * np.exp(np.linspace(0, -1.5, len(P)))  # BTC en caída permanente
    W = target_weights(P, listed_universe(P), PortfolioParams(regime_asset="BTC"))
    assert (W.iloc[250:] == 0).all().all()


def test_portfolio_costs_per_trade():
    idx = pd.date_range("2024-01-01", periods=6, freq="D")
    P = pd.DataFrame(100.0, index=idx, columns=["A", "B"])
    W = pd.DataFrame([[0.5, 0.5], [0.5, 0.5], [0, 0], [0, 0], [1, 0], [1, 0]], index=idx, columns=["A", "B"], dtype=float)
    bt = simulate_portfolio(P, W, PortfolioParams(dd_brake=False), cost=0.01, band=0.0)
    assert bt["turnover"].sum() == pytest.approx(3.0)
    assert (1 + bt["ret"]).prod() == pytest.approx((1 - 0.01) * (1 - 0.01) * (1 - 0.01))


# ------------------------------------------------------------ bot = backtest
def test_bot_replay_matches_backtest():
    P = panel(seed=4)
    cfg = copy.deepcopy(bot.DEFAULT_CONFIG)
    cfg["sleeves"]["crypto"] = crypto_cfg(kill_drawdown=0.99)
    df = bot.replay(cfg, "crypto", 300, prices=P)
    gap = (df["equity"] / df["backtest_equity"] - 1).abs().max()
    assert gap < 0.02, gap


# ------------------------------------------------------------ candados
def _run(P, st, sc=None, now=None, eq=None, broker=None):
    sc = sc or crypto_cfg()
    broker = broker or SimBroker(st.setdefault("ledger", {"cash": 300.0, "positions": {}}), 0.001, 0.002, 1.0)
    now = now or P.index[-1] + pd.Timedelta(days=1, minutes=10)
    return bot.run_sleeve("crypto", sc, P, broker, st, now, "paper",
                          eq if eq is not None else pd.Series(dtype=float), 0.40)


def test_same_candle_is_not_traded_twice():
    P = panel()
    st = {}
    _run(P, st)
    assert _run(P, st)["status"] == "skip"


def test_stale_data_blocks():
    P = panel()
    r = _run(P, {}, now=P.index[-1] + pd.Timedelta(days=4))
    assert r["status"] == "blocked" and not r["trades"]


def test_missing_price_for_holding_blocks_instead_of_false_kill():
    P = panel()
    st = {"ledger": {"cash": 0.0, "positions": {"ETH": 1.0}}, "peak": 100.0}
    P.loc[P.index[-8]:, "ETH"] = np.nan  # sin precio más de 5 días
    r = _run(P, st)
    assert r["status"] == "blocked" and not st.get("kill_switch")


def test_kill_switch_sells_everything():
    P = panel()
    px = P.iloc[-1]
    st = {"ledger": {"cash": 0.0, "positions": {"ETH": 50 / px["ETH"]}}, "peak": 100.0}  # -50%
    r = _run(P, st)
    assert st["kill_switch"] and st["ledger"]["positions"] == {}
    assert all(t["side"] == "sell" for t in r["trades"])
    st["last_candle"] = None
    r = _run(P, st)
    assert not [t for t in r["trades"] if t["side"] == "buy"]  # sigue apagado


def test_price_jump_never_buys_that_asset():
    P = panel()
    P.iloc[-1, P.columns.get_loc("ETH")] *= 1.8
    st = {}
    r = _run(P, st)
    assert not [t for t in r["trades"] if t["asset"] == "ETH" and t["side"] == "buy"]


def test_live_requires_confirmation(monkeypatch, tmp_path):
    monkeypatch.delenv("CONFIRMO_DINERO_REAL", raising=False)
    conf = tmp_path / "c.yaml"
    conf.write_text("mode: live\n")
    assert bot.main(["--config", str(conf), "--live"]) == 2


def test_passive_mix_targets():
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    P = pd.DataFrame({"SPY": np.linspace(100, 120, 300), "IEF": np.linspace(90, 95, 300), "QQQ": 1.0}, index=idx)
    sc = copy.deepcopy(bot.DEFAULT_CONFIG["sleeves"]["stocks"])
    t, _ = bot.compute_targets(sc, P)
    assert t["SPY"] == pytest.approx(0.6) and t["IEF"] == pytest.approx(0.4) and t["QQQ"] == 0


def test_alpaca_order_payload(monkeypatch):
    monkeypatch.setenv("ALPACA_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    sent = {}

    class R:
        status_code, text = 200, "{}"

        def json(self):
            return {"id": "abc12345xyz", "status": "accepted"}

    def fake(method, url, headers=None, timeout=None, **kw):
        sent.update(method=method, url=url, body=kw.get("json"), headers=headers)
        return R()

    monkeypatch.setattr("lab.brokers.requests.request", fake)
    f = AlpacaBroker(paper=True).execute("SPY", "buy", 1.5, 500.0)
    assert sent["url"].startswith("https://paper-api.alpaca.markets")
    assert sent["body"] == {"symbol": "SPY", "qty": "1.500000", "side": "buy", "type": "market", "time_in_force": "day"}
    assert f.status == "submitted"


def test_external_paper_account_respects_capital(monkeypatch):
    """Una cuenta paper de Alpaca trae $100k virtuales: el bot solo debe usar `capital`."""
    class FakeAlpaca(SimBroker):
        pass
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    P = pd.DataFrame({"SPY": np.linspace(100, 120, 300), "IEF": np.linspace(90, 95, 300)}, index=idx)
    sc = copy.deepcopy(bot.DEFAULT_CONFIG["sleeves"]["stocks"])
    sc["universe"] = ["SPY", "IEF"]
    st = {}
    broker = FakeAlpaca({"cash": 100_000.0, "positions": {}}, 0.0, 0.0, 1.0)
    monkeypatch.setattr(bot, "SimBroker", type("Otro", (), {}))  # que no se reconozca como simulado interno
    r = bot.run_sleeve("stocks", sc, P, broker, st, idx[-1] + pd.Timedelta(days=1, hours=2), "paper",
                       pd.Series(dtype=float), 0.4)
    spent = sum(t["value"] for t in r["trades"] if t["side"] == "buy")
    assert spent <= sc["capital"] * 1.001
    assert r["snapshot"]["equity"] <= sc["capital"] * 1.001
