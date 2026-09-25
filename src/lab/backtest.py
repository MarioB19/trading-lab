"""Motor de backtest diario, long/flat, con costos reales.

Cómo se simula un día D:
  1. Al cierre de D-1 la estrategia dio una exposición objetivo.
  2. Al inicio de D (≈ cierre de D-1, cripto no cierra) se rebalancea hacia ese
     objetivo si la diferencia supera la banda; se paga comisión + deslizamiento
     sobre lo operado.
  3. Durante D la cartera gana o pierde según el precio; la proporción en BTC
     "deriva" con el precio (no se asume rebalanceo gratis diario).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategies import ANN


@dataclass
class Costs:
    fee: float = 0.001        # comisión por lado (Bitso taker BTC/MXN ≈ 0.098%)
    slippage: float = 0.001   # diferencia entre el precio de referencia y el de ejecución

    @property
    def per_side(self) -> float:
        return self.fee + self.slippage


def simulate(close: pd.Series, target: pd.Series, cost: float = 0.002,
             band: float = 0.0) -> pd.DataFrame:
    r = close.pct_change().fillna(0.0).values
    tgt = target.reindex(close.index).fillna(0.0).clip(0, 1).values
    n = len(r)
    w_hold = np.zeros(n)
    turnover = np.zeros(n)
    strat = np.zeros(n)
    w = 0.0
    for t in range(1, n):
        desired = tgt[t - 1]
        diff = desired - w
        if abs(diff) > band or (desired == 0.0 and w > 0.0):
            turnover[t] = abs(diff)
            w = desired
        w_hold[t] = w
        # el costo reduce el capital al operar; luego el día corre con el peso elegido
        growth = (1.0 - turnover[t] * cost) * (1.0 + w * r[t])
        strat[t] = growth - 1.0
        w = w * (1.0 + r[t]) / (1.0 + w * r[t]) if (1.0 + w * r[t]) > 0 else 0.0
    return pd.DataFrame({"asset_ret": r, "position": w_hold, "turnover": turnover,
                         "ret": strat}, index=close.index)


def window(bt: pd.DataFrame, start=None, end=None, cost: float = 0.002) -> pd.DataFrame:
    """Recorta el backtest a un periodo. Si ya había posición al inicio, cobra la entrada."""
    out = bt.loc[start:end].copy()
    if len(out) and out["turnover"].iloc[0] < out["position"].iloc[0]:
        extra = out["position"].iloc[0] - out["turnover"].iloc[0]
        out.iloc[0, out.columns.get_loc("turnover")] += extra
        out.iloc[0, out.columns.get_loc("ret")] -= extra * cost
    return out


# ---------------------------------------------------------------- métricas
def max_drawdown(ret: pd.Series) -> float:
    eq = (1 + ret).cumprod()
    return float((eq / eq.cummax() - 1).min())


def longest_underwater_days(ret: pd.Series) -> int:
    eq = (1 + ret).cumprod()
    under = (eq < eq.cummax()).values
    best = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        best = max(best, cur)
    return int(best)


def sharpe(ret: pd.Series, ann: int = ANN) -> float:
    sd = ret.std(ddof=1)
    return float(ret.mean() / sd * np.sqrt(ann)) if sd > 0 else 0.0


def perf(bt: pd.DataFrame, ann: int = ANN) -> dict:
    r = bt["ret"]
    years = len(r) / ann
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1.0
    downside = np.sqrt((np.minimum(r, 0) ** 2).mean())
    mdd = max_drawdown(r)
    monthly = (1 + r).resample("ME").prod() - 1
    return {
        "cagr": float(cagr),
        "vol": float(r.std(ddof=1) * np.sqrt(ann)),
        "sharpe": sharpe(r, ann),
        "sortino": float(r.mean() / downside * np.sqrt(ann)) if downside > 0 else 0.0,
        "max_dd": mdd,
        "calmar": float(cagr / abs(mdd)) if mdd < 0 else float("nan"),
        "longest_dd_days": longest_underwater_days(r),
        "total_mult": float(eq.iloc[-1]),
        "worst_day": float(r.min()),
        "worst_month": float(monthly.min()),
        "pct_months_up": float((monthly > 0).mean()),
        "exposure": float(bt["position"].mean()),
        "trades_per_year": float((bt["turnover"] > 1e-9).sum() / years),
        "turnover_per_year": float(bt["turnover"].sum() / years),
        "days": int(len(r)),
    }
