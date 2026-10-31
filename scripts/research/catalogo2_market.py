"""Mercado del barrido catalogo2-etf: cierres ajustados de data/etf_prices.csv (Yahoo), días de bolsa."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from lab.catalog_etf import EtfMarket
from lab.portfolio import listed_universe

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWW", "TLT", "IEF", "GLD", "DBC", "VNQ",
            "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB"]


def load_market() -> tuple[EtfMarket, dict]:
    E = pd.read_csv(ROOT / "data" / "etf_prices.csv", index_col=0, parse_dates=True)[UNIVERSE].sort_index()
    E = E.where(E > 0)
    notes = {"first_date": str(E.index.min().date()), "last_date": str(E.index.max().date()), "rows": len(E),
             "listing": {k: str(v.date()) for k, v in E.notna().idxmax().items()}}
    return EtfMarket(C=E, elig=listed_universe(E)), notes
