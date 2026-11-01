"""Costos fijos en dólares (hosting) sobre una serie de rendimientos: M1 y M7 del semáforo.

El bot paga Railway (≈US$60 al año) aunque no opere. Con US$1,000 eso es 6% al año; con más capital pesa menos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def with_fixed_cost(ret: pd.Series, capital: float, annual_usd: float, ann: int = 365) -> pd.Series:
    """Rendimientos de la misma cartera si cada día se le restan annual_usd/ann dólares al cierre.

    Si el patrimonio llega a cero, se queda en cero (rendimiento −100% ese día y 0 después).
    """
    if capital <= 0 or annual_usd < 0 or ann <= 0:
        raise ValueError("capital > 0, annual_usd ≥ 0 y ann > 0")
    r = ret.to_numpy(dtype=float)
    if not np.isfinite(r).all():
        raise ValueError("rendimientos no finitos")
    daily = annual_usd / ann
    out = np.zeros(len(r))
    eq = capital
    for t in range(len(r)):
        if eq <= 0:
            out[t] = 0.0
            continue
        new = max(eq * (1 + r[t]) - daily, 0.0)
        out[t] = new / eq - 1
        eq = new
    return pd.Series(out, index=ret.index, name=ret.name)
