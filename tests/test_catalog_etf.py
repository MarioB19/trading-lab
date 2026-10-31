"""Catálogo 2 (ETFs): pesos válidos y sin mirar al futuro."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab import catalog_etf as ce
from lab.portfolio import listed_universe


def market(n=1500, seed=4):
    rng = np.random.default_rng(seed)
    assets = ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWW", "TLT", "IEF", "GLD", "DBC", "VNQ",
              "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB"]
    r = rng.normal(0.0003, 0.01, size=(n, len(assets)))
    idx = pd.bdate_range("2019-01-01", periods=n)
    C = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=assets)
    C.iloc[:300, assets.index("DBC")] = np.nan
    return ce.EtfMarket(C=C, elig=listed_universe(C))


CAT = ce.build_catalog()


@pytest.mark.parametrize("variant", CAT, ids=[c["id"] for c in CAT])
def test_weights_are_valid(variant):
    M = market()
    W = variant["fn"](M)
    assert W.shape == M.C.shape and not W.isna().any().any()
    assert (W >= -1e-12).all().all() and (W.sum(axis=1) <= 1 + 1e-9).all()
    assert (W.where(M.C.isna(), 0.0) == 0).all().all()


@pytest.mark.parametrize("vid", ["mix-permanente", "rp-spy-tlt-gld-w63", "trend-spy200-to-ief", "gem-12m",
                                 "sector-6m-top3-trend", "class-top3-abs-invvol", "voltarget-8", "control-mensual", "bondswitch-tlt200"])
def test_no_lookahead(vid):
    fn = next(c["fn"] for c in CAT if c["id"] == vid)
    M = market()
    full = fn(M)
    for k in (900, 1200):
        Mk = ce.EtfMarket(C=M.C.iloc[:k], elig=listed_universe(M.C.iloc[:k]))
        pd.testing.assert_frame_equal(full.iloc[:k], fn(Mk), check_exact=False, atol=1e-10)


def test_describe_counts():
    d = ce.describe()
    ids = [v["id"] for v in d["variants"]]
    assert len(ids) == len(set(ids)) and d["n_variants"] >= 40 and d["config_sha256"] == ce.describe()["config_sha256"]
