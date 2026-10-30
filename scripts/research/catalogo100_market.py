"""Carga el mercado del barrido catalogo100 (OKX OHLCV + SPY). Compartido por el smoke test y el runner."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from lab.catalog import Market
from lab.portfolio import listed_universe
from lab.research_multi import BITSO_TRADABLE

ROOT = Path(__file__).resolve().parents[2]


def load_market() -> tuple[Market, dict]:
    o = pd.read_csv(ROOT / "data" / "crypto_ohlc_okx.csv", parse_dates=["date"])
    o = o[o["asset"].isin(BITSO_TRADABLE)]
    bad = (o["high"] / o["close"] > 3) | (o["low"] / o["close"] < 1 / 3)
    o.loc[bad, ["high", "low"]] = np.nan
    piv = lambda col: o.pivot(index="date", columns="asset", values=col)[BITSO_TRADABLE]
    C, H, L, V = piv("close"), piv("high"), piv("low"), piv("volume")
    idx = pd.date_range(C.index.min(), C.index.max(), freq="D")
    C, H, L, V = (x.reindex(idx) for x in (C, H, L, V))
    E = pd.read_csv(ROOT / "data" / "etf_prices.csv", index_col=0, parse_dates=True)
    spy = E["SPY"].reindex(idx).ffill()
    notes = {"suspicious_candles": int(bad.sum()), "first_date": str(idx[0].date()), "last_date": str(idx[-1].date()),
             "spy_last": str(E["SPY"].dropna().index[-1].date())}
    return Market(C=C, H=H, L=L, V=V, elig=listed_universe(C), spy=spy), notes
