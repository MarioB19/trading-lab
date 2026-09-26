"""Estrategia de PORTAFOLIO multi-activo (criptos o acciones/ETF).

Cada día, al cierre, para cada activo del universo:
  1. Tendencia: fracción de 4 promedios móviles (20/50/100/200) que el precio supera (0 a 1).
  2. Momentum ajustado por riesgo: promedio de rendimientos a 1, 3 y 6 meses dividido
     entre su volatilidad.
  3. Solo son candidatos los activos con tendencia >= 0.5 y momentum > 0.
     Se eligen los `top_k` de mayor momentum.
  4. Peso proporcional a tendencia / volatilidad (paridad de riesgo: un activo el doble de
     volátil recibe la mitad de dinero), con tope por activo.
  5. Filtro de régimen (cripto): si BTC no está en tendencia, no se compran altcoins.
  6. Volatilidad objetivo: con la matriz de covarianzas reciente se escala el portafolio
     para que su volatilidad anual esperada no pase de `vol_target`. El resto queda en efectivo.
  7. Freno por caída (en la simulación y en el bot): si el portafolio cae más de 10% desde su
     máximo de los últimos 6 meses, la exposición baja gradualmente hasta 25% a -30%.

Todo usa solo información hasta el cierre del día; el motor aplica los pesos al día siguiente.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


@dataclass
class PortfolioParams:
    top_k: int = 5
    vol_target: float | None = 0.40
    regime_asset: str | None = "BTC"
    dd_brake: bool = True
    max_weight: float = 0.40
    lookbacks: tuple = (20, 50, 100, 200)
    mom_windows: tuple = (30, 90, 180)
    vol_halflife: int = 20
    cov_window: int = 90
    min_trend: float = 0.5
    ann: int = 365
    dd_start: float = 0.10
    dd_full: float = 0.30
    dd_floor: float = 0.25
    dd_peak_window: int = 180
    cash_asset: str | None = None   # p. ej. "BIL": el efectivo no usado se estaciona en bonos del Tesoro
    rebalance: str = "daily"        # "monthly": solo se rebalancea el primer día hábil de cada mes

    @classmethod
    def from_dict(cls, d: dict | None) -> "PortfolioParams":
        d = dict(d or {})
        for k in ("lookbacks", "mom_windows"):
            if k in d:
                d[k] = tuple(d[k])
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ señales por activo
def clean(prices: pd.DataFrame) -> pd.DataFrame:
    """Precios <= 0 se tratan como faltantes; un hueco de hasta 5 días usa el último precio.

    Sin esto, un solo dato faltante borra el promedio de 200 días durante 200 días
    y pierde el rendimiento del día del hueco.
    """
    return prices.where(prices > 0).ffill(limit=5)


def signals(prices: pd.DataFrame, p: PortfolioParams) -> dict[str, pd.DataFrame]:
    prices = clean(prices)
    trend = sum((prices > prices.rolling(n, min_periods=n).mean()).astype(float)
                .where(prices.rolling(n, min_periods=n).mean().notna())
                for n in p.lookbacks) / len(p.lookbacks)
    logret = np.log(prices).diff()
    vol = logret.ewm(halflife=p.vol_halflife, min_periods=60).std() * np.sqrt(p.ann)
    mom = sum(prices.pct_change(w, fill_method=None) for w in p.mom_windows) / len(p.mom_windows)
    score = mom / vol
    return {"trend": trend, "vol": vol, "mom": mom, "score": score}


def cap_weights(w: np.ndarray, cap: float) -> np.ndarray:
    """Recorta pesos al tope y reparte el excedente entre los demás (si caben)."""
    w = w.copy()
    for _ in range(len(w) + 1):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        free = ~over & (w < cap - 1e-12)
        if not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    return w


def target_weights(prices: pd.DataFrame, eligible: pd.DataFrame | None,
                   p: PortfolioParams, return_signals: bool = False):
    """Pesos objetivo por fecha (antes del freno por caída, que depende del capital)."""
    prices = clean(prices)
    sig = signals(prices, p)
    cols = list(prices.columns)
    elig = (eligible.reindex_like(prices).fillna(False).astype(bool).values
            if eligible is not None else np.ones(prices.shape, bool))
    trend, vol, score = sig["trend"].values, sig["vol"].values, sig["score"].values
    rets = np.log(prices).diff().values
    has_regime = p.regime_asset is not None and p.regime_asset in cols
    ci = cols.index(p.cash_asset) if p.cash_asset and p.cash_asset in cols else -1
    cash_ok = np.isfinite(clean(prices).values[:, ci]) if ci >= 0 else None
    ri = cols.index(p.regime_asset) if has_regime else -1
    W = np.zeros(prices.shape)
    for t in range(len(prices)):
        tr, vo, sc = trend[t], vol[t], score[t]
        ok = elig[t] & (tr >= p.min_trend) & (sc > 0) & np.isfinite(vo) & (vo > 0) & np.isfinite(sc)
        if ci >= 0:
            ok[ci] = False  # el activo de efectivo nunca compite por tendencia
        if has_regime and not (np.isfinite(tr[ri]) and tr[ri] >= p.min_trend):
            mask = np.zeros(len(cols), bool)
            mask[ri] = True
            ok &= mask
        idx = np.flatnonzero(ok)
        if not len(idx):
            continue
        idx = idx[np.argsort(-sc[idx], kind="stable")][: p.top_k]
        raw = tr[idx] / vo[idx]
        w = cap_weights(raw / raw.sum(), p.max_weight)
        if p.vol_target:
            window = rets[max(1, t - p.cov_window + 1): t + 1][:, idx]
            window = window[np.isfinite(window).all(axis=1)]
            if len(window) >= 30:
                cov = np.cov(window, rowvar=False) * p.ann
                cov = np.atleast_2d(cov)
                sp = float(np.sqrt(max(w @ cov @ w, 1e-12)))
                w = w * min(1.0, p.vol_target / sp)
        W[t, idx] = w
    if ci >= 0:
        W[:, ci] = np.where(cash_ok, np.clip(1.0 - W.sum(axis=1), 0.0, 1.0), 0.0)
    out = pd.DataFrame(W, index=prices.index, columns=cols)
    if p.rebalance == "monthly":
        # la cartera se decide el primer día hábil del mes y se mantiene hasta el siguiente
        out.loc[~rebalance_days(prices.index)] = np.nan
        out = out.ffill().fillna(0.0)
    return (out, sig) if return_signals else out


def rebalance_days(index: pd.DatetimeIndex) -> np.ndarray:
    """True el primer día con datos de cada mes (se sabe sin mirar al futuro)."""
    m = np.asarray(index.month)
    out = np.zeros(len(index), bool)
    out[1:] = m[1:] != m[:-1]
    return out


def drawdown_multiplier(dd: float, p: PortfolioParams) -> float:
    """1.0 sin caída; baja linealmente de -dd_start a -dd_full hasta dd_floor."""
    if not p.dd_brake or dd > -p.dd_start:
        return 1.0
    frac = min(1.0, (-dd - p.dd_start) / (p.dd_full - p.dd_start))
    return 1.0 - frac * (1.0 - p.dd_floor)


# ------------------------------------------------------------------ simulación
def simulate_portfolio(prices: pd.DataFrame, weights: pd.DataFrame, p: PortfolioParams,
                       cost: float = 0.003, band: float = 0.02,
                       kill_dd: float | None = None) -> pd.DataFrame:
    """Backtest diario multi-activo con costos, banda de rebalanceo, deriva y freno por caída."""
    R = clean(prices).pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0).values
    cols = list(prices.columns)
    ci = cols.index(p.cash_asset) if p.cash_asset and p.cash_asset in cols else -1
    cash_ok = np.isfinite(clean(prices).values[:, ci]) if ci >= 0 else None
    Wt = weights.reindex_like(prices).fillna(0.0).values
    n, m = R.shape
    w = np.zeros(m)
    eq_hist = np.ones(n)
    out_ret, gross, turn, mult_arr = np.zeros(n), np.zeros(n), np.zeros(n), np.ones(n)
    held = np.zeros((n, m))
    equity, killed = 1.0, False
    monthly = p.rebalance == "monthly"
    rdays = rebalance_days(prices.index) if monthly else None
    prev_mult = 1.0
    for t in range(1, n):
        lo = max(0, t - p.dd_peak_window)
        peak = eq_hist[lo:t].max()
        dd = equity / peak - 1
        if kill_dd is not None and equity / eq_hist[:t].max() - 1 <= -kill_dd:
            killed = True
        mult = 0.0 if killed else drawdown_multiplier(dd, p)
        desired = Wt[t - 1] * mult
        if ci >= 0 and not killed and cash_ok[t - 1]:
            # el freno reduce solo lo riesgoso; lo liberado se estaciona en el activo de efectivo
            desired[ci] = max(0.0, 1.0 - (desired.sum() - desired[ci]))
        diff = desired - w
        trade = (np.abs(diff) > band) | ((desired == 0) & (w > 0))
        if monthly and not (rdays[t - 1] or killed or mult != prev_mult or w.sum() == 0):
            trade[:] = False  # fuera del día de rebalanceo solo actúan el freno y el kill switch
        prev_mult = mult
        tv = np.abs(diff[trade]).sum()
        w = np.where(trade, desired, w)
        port = float(w @ R[t])
        growth = (1 - tv * cost) * (1 + port)
        out_ret[t], gross[t], turn[t], mult_arr[t] = growth - 1, w.sum(), tv, mult
        held[t] = w
        equity *= growth
        eq_hist[t] = equity
        w = w * (1 + R[t]) / (1 + port) if (1 + port) > 0 else np.zeros(m)
    df = pd.DataFrame({"ret": out_ret, "position": gross, "turnover": turn, "brake": mult_arr},
                      index=prices.index)
    df.attrs["held"] = pd.DataFrame(held, index=prices.index, columns=prices.columns)
    return df


# ------------------------------------------------------------------ universos
def crypto_universe(mcap: pd.DataFrame, prices: pd.DataFrame, top_n: int = 15,
                    min_history: int = 250) -> pd.DataFrame:
    """Elegibles en cada fecha: top N por capitalización DE ESE DÍA y con historia suficiente.

    Así el backtest solo "conoce" las criptos que en ese momento eran grandes,
    incluidas las que después se desplomaron.
    """
    hist = prices.notna().cumsum() >= min_history
    ranks = mcap.where(prices.notna()).rank(axis=1, ascending=False, method="first")
    return (ranks <= top_n) & hist & prices.notna()


def listed_universe(prices: pd.DataFrame, min_history: int = 250) -> pd.DataFrame:
    return (prices.notna().cumsum() >= min_history) & prices.notna()


# ------------------------------------------------------------------ referencias
def equal_weight_buy_hold(prices: pd.DataFrame, eligible: pd.DataFrame,
                          rebalance: str = "ME") -> pd.DataFrame:
    """Referencia pasiva: pesos iguales entre los elegibles, rebalanceo mensual."""
    W = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    month_end = prices.index.to_series().groupby(prices.index.to_period("M")).transform("max")
    current = None
    for d in prices.index:
        if current is None or d == month_end[d]:
            e = eligible.loc[d]
            current = e.astype(float) / max(1, e.sum())
        W.loc[d] = current.values
    return W


def fixed_weights(prices: pd.DataFrame, mix: dict[str, float]) -> pd.DataFrame:
    W = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    for k, v in mix.items():
        W[k] = v
    return W.where(prices.notna(), 0.0)
