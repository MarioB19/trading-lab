"""Catálogo 3 (señales exógenas): pesos válidos, causalidad del rezago y sin mirar al futuro."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab import catalog, catalog_exog as cx
from lab.portfolio import listed_universe


def market(n=1200, seed=6):
    rng = np.random.default_rng(seed)
    assets = ["BTC", "ETH", "AAA", "BBB", "CCC", "DDD"]
    r = rng.normal(np.linspace(0.002, -0.001, 6), 0.04, size=(n, 6))
    idx = pd.date_range("2021-01-01", periods=n, freq="D")
    C = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=assets)
    M = catalog.Market(C=C, H=C, L=C, V=C, elig=listed_universe(C))
    fng = pd.DataFrame({"fng": rng.integers(5, 96, n).astype(float)}, index=idx)
    cm = pd.DataFrame({"btc_CapMVRVCur": rng.uniform(0.8, 4.0, n), "btc_AdrActCnt": rng.uniform(5e5, 1e6, n),
                       "btc_SplyExNtv": np.cumsum(rng.normal(0, 1000, n)) + 2e6, "btc_HashRate": np.cumsum(rng.normal(10, 50, n)) + 1e8}, index=idx)
    st = pd.DataFrame({"stables_usd": np.cumsum(rng.normal(1e8, 5e8, n)) + 1e11}, index=idx)
    X = cx.load_exog(idx, fng, cm, st, stables_from="2021-01-01")
    return M, X, (fng, cm, st)


CAT = cx.build_catalog()


@pytest.mark.parametrize("variant", CAT, ids=[c["id"] for c in CAT])
def test_weights_valid_and_never_above_control(variant):
    M, X, _ = market()
    W = variant["fn"](M, X)
    assert W.shape == M.C.shape and not W.isna().any().any()
    assert (W >= -1e-12).all().all() and (W.sum(axis=1) <= 1 + 1e-9).all()
    if not variant["id"].startswith("fngbtc"):
        assert (W <= M.control_weights() + 1e-12).all().all()  # las capas solo reducen exposición


def test_lag_is_causal():
    idx = pd.date_range("2021-01-01", periods=10, freq="D")
    s = pd.Series(np.arange(10.0), index=idx)
    assert cx.align(s, idx, 1).iloc[3] == 2.0 and np.isnan(cx.align(s, idx, 1).iloc[0])
    assert cx.align(s, idx, 0).iloc[3] == 3.0


@pytest.mark.parametrize("vid", ["fng-cut80", "mvrv-z2", "exsup-in30-half", "adr-mom30-half", "stab-linear", "hash-ribbon-half", "comp-linear", "fngbtc-20-80"])
def test_no_lookahead(vid):
    fn = next(c["fn"] for c in CAT if c["id"] == vid)
    M, X, (fng, cm, st) = market()
    full = fn(M, X)
    for k in (800, 1000):
        Ck = M.C.iloc[:k]
        Mk = catalog.Market(C=Ck, H=Ck, L=Ck, V=Ck, elig=listed_universe(Ck))
        Xk = cx.load_exog(Ck.index, fng.iloc[:k], cm.iloc[:k], st.iloc[:k], stables_from="2021-01-01")
        pd.testing.assert_frame_equal(full.iloc[:k], fn(Mk, Xk), check_exact=False, atol=1e-10)


def test_describe():
    d = cx.describe()
    assert d["n_variants"] >= 30 and len({v["id"] for v in d["variants"]}) == d["n_variants"]
