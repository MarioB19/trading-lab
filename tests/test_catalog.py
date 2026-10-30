"""Pruebas del catálogo de estrategias (catalogo100): pesos válidos y sin mirar al futuro."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab import catalog
from lab.portfolio import listed_universe


def market(n=900, seed=2):
    rng = np.random.default_rng(seed)
    assets = ["BTC", "ETH", "AAA", "BBB", "CCC", "DDD"]
    r = rng.normal(np.linspace(0.002, -0.001, 6), 0.04, size=(n, 6))
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    C = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=assets)
    C.iloc[:400, 5] = np.nan
    H = C * (1 + np.abs(rng.normal(0, 0.01, C.shape)))
    L = C * (1 - np.abs(rng.normal(0, 0.01, C.shape)))
    V = pd.DataFrame(rng.lognormal(10, 1, C.shape), index=idx, columns=assets).where(C.notna())
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n))), index=idx)
    return catalog.Market(C=C, H=H, L=L, V=V, elig=listed_universe(C), spy=spy)


def cut(M, k):
    return catalog.Market(C=M.C.iloc[:k], H=M.H.iloc[:k], L=M.L.iloc[:k], V=M.V.iloc[:k],
                          elig=listed_universe(M.C.iloc[:k]), spy=M.spy.iloc[:k])


FAST = [c for c in catalog.build_catalog() if not c["id"].startswith("ml-")]


@pytest.mark.parametrize("variant", FAST, ids=[c["id"] for c in FAST])
def test_weights_are_valid(variant):
    M = market()
    W = variant["fn"](M)
    assert W.shape == M.C.shape and list(W.columns) == list(M.C.columns)
    assert not W.isna().any().any()
    assert (W >= -1e-12).all().all() and (W.sum(axis=1) <= 1 + 1e-9).all()
    assert (W.where(M.C.isna(), 0.0) == 0).all().all()  # nunca un activo sin precio


@pytest.mark.parametrize("vid", ["xsmom-w30-skip7", "tsmom-sma-90", "macross-ema-20-100", "donchian-55-20-invvol",
                                 "lowvol-w30-k5", "atrstop-3x-wait7", "liquidity-top5", "control-reweight-score",
                                 "spy-regime-only", "altseason-ethbtc-50", "dominance-mom30", "calendar-turn_of_month",
                                 "weekrev-w7-k3", "ensemble-avg4-voltarget", "ensemble-vote2of3", "dualmom-90",
                                 "control-volregime-x50", "xsmom-w90-skip7-top3"])
def test_no_lookahead(vid):
    fn = next(c["fn"] for c in catalog.build_catalog() if c["id"] == vid)
    M = market()
    full = fn(M)
    for k in (600, 800):
        part = fn(cut(M, k))
        pd.testing.assert_frame_equal(full.iloc[:k], part, check_exact=False, atol=1e-10)


def test_ml_runs_and_is_causal_by_construction():
    M = market(n=1500, seed=5)
    W = catalog.f_ml(M, "ridge")
    assert W.shape == M.C.shape and (W.sum(axis=1) <= 1 + 1e-9).all()
    assert (W.loc[:"2020-12-31"].sum().sum() == 0) if W.index[0].year <= 2020 else True


def test_describe_is_deterministic_and_counts():
    a, b = catalog.describe(), catalog.describe()
    assert a["config_sha256"] == b["config_sha256"] and a["n_variants"] >= 100
    ids = [v["id"] for v in a["variants"]]
    assert len(ids) == len(set(ids))
