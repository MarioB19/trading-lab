"""Pruebas de la operación en tiempo real: señal con cierre provisional, simulador por hora y vigía."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.data import hourly_to_daily
from lab.portfolio import (PortfolioParams, listed_universe, simulate_portfolio, target_weights,
                           with_provisional_close)
from lab.research_rt import hourly_params, masks, target_at, to_daily


def hourly_panel(days=330, seed=3, assets=("BTC", "ETH", "AAA", "BBB", "CCC")):
    rng = np.random.default_rng(seed)
    n = days * 24
    drift = np.linspace(0.0002, -0.0001, len(assets))
    r = rng.normal(drift, 0.008, size=(n, len(assets)))
    idx = pd.date_range("2023-01-01 01:00", periods=n, freq="h")
    return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=list(assets))


P = PortfolioParams(top_k=3, vol_target=0.4, regime_asset="BTC", dd_brake=True, max_weight=0.4)


def test_hourly_to_daily_uses_midnight_close():
    H = hourly_panel(days=5)
    D = hourly_to_daily(H)
    assert D.index[0] == pd.Timestamp("2023-01-01")
    assert (D.loc["2023-01-01"] == H.loc["2023-01-02 00:00"]).all()


def test_provisional_signal_no_lookahead():
    """La revisión de una hora solo usa datos hasta esa hora."""
    H = hourly_panel()
    D = hourly_to_daily(H)
    for t in (H.index[-200], H.index[-37], H.index[-1]):
        cut = H.loc[:t]
        a = target_at(H, D, t, P)
        b = target_at(cut, hourly_to_daily(cut), t, P)
        np.testing.assert_allclose(a, b)


def test_provisional_signal_at_midnight_equals_daily_signal():
    H = hourly_panel()
    D = hourly_to_daily(H)
    t = H.index[H.index.hour == 0][-1]
    day = t.normalize() - pd.Timedelta(days=1)
    full = target_weights(D.loc[:day], listed_universe(D.loc[:day], 250), P).iloc[-1].values
    np.testing.assert_allclose(target_at(H, D, t, P), full)


def test_with_provisional_close_replaces_only_today():
    D = hourly_to_daily(hourly_panel(days=20))
    day = D.index[-1] + pd.Timedelta(days=1)
    now = pd.Series(1.0, index=D.columns)
    X = with_provisional_close(D, now, day)
    assert X.index[-1] == day and (X.iloc[-1] == 1.0).all()
    pd.testing.assert_frame_equal(X.iloc[:-1], D, check_freq=False)


def _hourly_setup(days=330):
    H = hourly_panel(days)
    D = hourly_to_daily(H)
    times = H.index[H.index.hour == 0][-60:]
    T = pd.DataFrame(0.0, index=H.index, columns=H.columns)
    for t in times:
        T.loc[t] = target_at(H, D, t, P)
    T = T.loc[times[0]:]
    return H.loc[times[0]:], T


def test_default_check_equals_all_rows():
    H, T = _hourly_setup()
    a = simulate_portfolio(H, T, P, 0.004, 0.02)
    b = simulate_portfolio(H, T, P, 0.004, 0.02, check=np.ones(len(H), bool))
    pd.testing.assert_series_equal(a["ret"], b["ret"])


def test_trades_only_after_check_rows():
    H, T = _hourly_setup()
    check, _ = masks(H.index, "1d")
    bt = simulate_portfolio(H, T, hourly_params(P), 0.004, 0.02, check=check)
    traded = np.flatnonzero(bt["turnover"].values > 0)
    assert len(traded) and check[traded - 1].all()


def test_hourly_daily_check_matches_daily_engine():
    """Revisar a las 00:00 sobre la malla por hora = el simulador diario sobre los cierres."""
    H, T = _hourly_setup()
    check, _ = masks(H.index, "1d")
    hourly = to_daily(simulate_portfolio(H, T, hourly_params(P), 0.004, 0.02, kill_dd=0.45, check=check))
    D = hourly_to_daily(H)
    W = T[T.index.hour == 0].copy()
    W.index = W.index.normalize() - pd.Timedelta(days=1)
    daily = simulate_portfolio(D, W.reindex(D.index).fillna(0.0), P, 0.004, 0.02, kill_dd=0.45)
    common = hourly.index.intersection(daily.index)[1:]
    np.testing.assert_allclose(hourly.loc[common, "ret"], daily.loc[common, "ret"], atol=1e-12)


def test_watch_only_sells_between_daily_checks():
    H, T = _hourly_setup()
    H = H.copy()
    H.iloc[-300:] = H.iloc[-300:] * np.exp(-0.002 * np.arange(1, 301))[:, None]  # caída sostenida
    check, watch = masks(H.index, "vigia")
    bt = simulate_portfolio(H, T, hourly_params(P), 0.004, 0.02, kill_dd=0.45, check=check, watch=watch)
    held = bt.attrs["held"].values
    R = H.pct_change().fillna(0.0).values
    for t in np.flatnonzero(bt["turnover"].values > 0):
        if check[t - 1]:
            continue
        drift = held[t - 1] * (1 + R[t - 1]) / (1 + held[t - 1] @ R[t - 1])  # sin operar
        assert (held[t] <= drift + 1e-12).all()  # el vigía nunca compra
    assert (bt["turnover"].values[~np.r_[False, check[:-1]]] > 0).any()  # sí actuó a media sesión


def test_watch_without_drawdown_equals_daily():
    H, T = _hourly_setup()
    H = H.copy()
    H[:] = H.iloc[0].values * np.exp(np.linspace(0, 0.3, len(H)))[:, None]  # solo sube: el freno nunca se aprieta
    c1, _ = masks(H.index, "1d")
    c2, w2 = masks(H.index, "vigia")
    a = simulate_portfolio(H, T, hourly_params(P), 0.004, 0.02, check=c1)
    b = simulate_portfolio(H, T, hourly_params(P), 0.004, 0.02, check=c2, watch=w2)
    assert a["ret"].values == pytest.approx(b["ret"].values)


# ------------------------------------------------------------ motor en tiempo real (lab.realtime)
import copy  # noqa: E402

from lab import bot  # noqa: E402
from lab.brokers import SimBroker  # noqa: E402
from lab.realtime import REALTIME_DEFAULTS, check_sleeve  # noqa: E402


def _crypto_daily():
    rng = np.random.default_rng(2)
    idx = pd.date_range("2024-01-01", periods=400, freq="D")
    r = rng.normal(0.001, 0.03, size=(400, 4))
    return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=["BTC", "ETH", "SOL", "LTC"])


def _sc():
    sc = copy.deepcopy(bot.DEFAULT_CONFIG["sleeves"]["crypto"])
    sc["universe"] = ["BTC", "ETH", "SOL", "LTC"]
    return sc


def test_check_sleeve_values_at_live_prices_without_touching_state():
    D = _crypto_daily()
    st = {"ledger": {"cash": 100.0, "positions": {"ETH": 1.0}}, "peak": 250.0, "last_candle": "2025-02-03"}
    before = copy.deepcopy(st)
    live = D.iloc[-1] * 1.02
    now = D.index[-1] + pd.Timedelta(days=1, hours=5)
    br = SimBroker(st["ledger"], 0.0036, 0.001, 5.0)
    r = check_sleeve("crypto", _sc(), st, REALTIME_DEFAULTS, "paper", now, pd.Series(dtype=float),
                     broker=br, daily=D, live=live)
    assert r["status"] == "ok"
    assert r["equity"] == pytest.approx(100 + float(live["ETH"]), abs=0.01)
    assert r["positions"][0]["change_since_close"] == pytest.approx(0.02, abs=1e-4)
    assert st == before  # observar no opera ni cambia el estado
    assert {"asset", "target_now", "weight_now", "move"} <= set(r["signal_now"][0])


def test_check_sleeve_alerts_near_kill_switch():
    D = _crypto_daily()
    st = {"ledger": {"cash": 0.0, "positions": {"ETH": 1.0}}}
    eth = float(D.iloc[-1]["ETH"])
    st["peak"] = eth / (1 - 0.42)  # 42% abajo del máximo; kill switch a 45%
    br = SimBroker(st["ledger"], 0.0036, 0.001, 5.0)
    r = check_sleeve("crypto", _sc(), st, REALTIME_DEFAULTS, "paper", D.index[-1] + pd.Timedelta(days=1, hours=3),
                     pd.Series(dtype=float), broker=br, daily=D, live=D.iloc[-1])
    assert any("kill switch" in a for a in r["alerts"])


def test_check_sleeve_never_values_missing_price_at_zero():
    D = _crypto_daily()
    st = {"ledger": {"cash": 10.0, "positions": {"XYZ": 3.0}}}
    br = SimBroker(st["ledger"], 0.0036, 0.001, 5.0)
    r = check_sleeve("crypto", _sc(), st, REALTIME_DEFAULTS, "paper", D.index[-1] + pd.Timedelta(days=1),
                     pd.Series(dtype=float), broker=br, daily=D, live=D.iloc[-1])
    assert r["status"] == "blocked" and "equity" not in r


def test_is_due_crypto_and_stocks():
    sc_c = bot.DEFAULT_CONFIG["sleeves"]["crypto"]
    sc_s = bot.DEFAULT_CONFIG["sleeves"]["stocks"]
    now = pd.Timestamp("2026-09-26 05:07")          # sábado 01:07 en Nueva York
    assert bot.is_due(sc_c, {"last_candle": "2026-09-24"}, now)
    assert not bot.is_due(sc_c, {"last_candle": "2026-09-25"}, now)
    assert not bot.is_due(sc_s, {"last_candle": "2026-09-25"}, now)   # la sesión del viernes ya se operó
    assert bot.is_due(sc_s, {"last_candle": "2026-09-24"}, now)
    assert not bot.is_due(sc_s, {"last_candle": "2026-09-25"}, pd.Timestamp("2026-09-28 15:00"))  # lunes, sesión abierta
