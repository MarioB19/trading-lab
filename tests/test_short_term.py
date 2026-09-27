"""Estrategias de corto plazo: sin mirar al futuro y límites de peso."""
from __future__ import annotations

import numpy as np
import pandas as pd

from lab.portfolio import breakout_weights, reversal_weights


def hourly(n=24 * 60, seed=7, cols=("BTC", "ETH", "SOL", "XRP", "ADA", "LTC", "AVAX")):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.01, size=(n, len(cols)))
    idx = pd.date_range("2024-01-01 01:00", periods=n, freq="h")
    H = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=list(cols))
    H.iloc[:300, -1] = np.nan  # una cripto que aparece después
    return H


def test_reversal_no_lookahead_and_limits():
    H = hourly()
    for thr in (None, 0.05):
        W = reversal_weights(H, threshold=thr, min_history=100)
        for cut in (500, 1000):
            part = reversal_weights(H.iloc[:cut], threshold=thr, min_history=100)
            pd.testing.assert_frame_equal(W.iloc[:cut], part)
        assert (W.sum(axis=1) <= 1 + 1e-9).all() and ((W > 0).sum(axis=1) <= 3).all()
        assert (W.iloc[:300]["AVAX"] == 0).all()
        # solo cambia en las horas de revisión (cada 4)
        changed = W.diff().abs().sum(axis=1) > 0
        assert (np.asarray(W.index[changed].hour) % 4 == 0).all()


def test_reversal_buys_the_biggest_losers():
    H = hourly()
    t = H.index[H.index.hour == 0][-1]
    r = (H.loc[t] / H.shift(24).loc[t] - 1).dropna()
    W = reversal_weights(H, min_history=100)
    assert set(W.loc[t][W.loc[t] > 0].index) == set(r.nsmallest(3).index)


def test_breakout_no_lookahead_and_limits():
    H = hourly()
    W = breakout_weights(H, entry=24, exit=12, slots=5, min_history=100)
    for cut in (500, 1000):
        pd.testing.assert_frame_equal(W.iloc[:cut], breakout_weights(H.iloc[:cut], 24, 12, 5, 100))
    assert (W.sum(axis=1) <= 1 + 1e-9).all() and (W.max(axis=1) <= 0.2 + 1e-9).all()
    assert (W > 0).any().any()


def test_breakout_enters_on_new_high_and_exits_on_low():
    idx = pd.date_range("2024-01-01 01:00", periods=200, freq="h")
    px = np.r_[np.full(100, 100.0), np.linspace(101, 110, 50), np.linspace(109, 90, 50)]
    H = pd.DataFrame({"BTC": px}, index=idx)
    W = breakout_weights(H, entry=24, exit=12, slots=5, min_history=10)["BTC"]
    assert W.iloc[99] == 0 and W.iloc[100] == 0.2      # rompe el máximo de 24 h
    assert W.iloc[-1] == 0                              # bajó del mínimo de 12 h
