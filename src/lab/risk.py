"""Gestión de riesgo: lo que decide cuánto puedes perder, no cuánto vas a ganar."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategies import ANN


@dataclass
class RiskLimits:
    max_position: float = 1.0        # fracción máxima del capital del bot en BTC
    rebalance_band: float = 0.10     # no operar por diferencias menores a esto (ahorra comisiones)
    max_drawdown_kill: float = 0.35  # si el capital cae 35% desde su máximo: vender todo y detenerse
    max_order_value: float = 5_000   # tope por orden, en moneda de cotización
    max_price_jump: float = 0.25     # un cierre que se mueve >25% en un día se trata como dato sospechoso
    max_data_age_hours: float = 36   # si la última vela cerrada es más vieja, no operar


def kelly_fraction(ret: pd.Series) -> float:
    """Fracción de Kelly continua (μ/σ²) sobre rendimientos diarios.

    Úsala como TECHO, nunca como objetivo: con μ estimado de pocos años de datos
    el error es enorme, y apostar Kelly completo con un μ sobreestimado lleva a la ruina.
    En la práctica se usa 1/4 a 1/2 Kelly.
    """
    r = ret.dropna()
    return float(r.mean() / r.var(ddof=1)) if r.var() > 0 else 0.0


def kelly_uncertainty(ret: pd.Series) -> dict:
    """Kelly con su intervalo: muestra lo poco que sabemos de μ."""
    r = ret.dropna()
    mu, var, n = r.mean(), r.var(ddof=1), len(r)
    se_mu = r.std(ddof=1) / np.sqrt(n)
    return {"kelly": float(mu / var), "kelly_low": float((mu - 2 * se_mu) / var),
            "kelly_high": float((mu + 2 * se_mu) / var),
            "mu_annual": float(mu * ANN), "mu_annual_low": float((mu - 2 * se_mu) * ANN),
            "mu_annual_high": float((mu + 2 * se_mu) * ANN)}


def check_prices(close: pd.Series, limits: RiskLimits, now: pd.Timestamp) -> tuple[list[str], list[str]]:
    """Revisa los datos antes de operar.

    Devuelve (bloqueos, precauciones):
      * bloqueos: no se opera nada (datos viejos, incompletos o insuficientes).
      * precauciones: solo se permite REDUCIR exposición. Un dato raro nunca debe
        hacerte comprar, pero tampoco debe impedirte salir en un desplome real.
    """
    blocking, caution = [], []
    if len(close) < 300:
        blocking.append(f"historia insuficiente ({len(close)} días; se necesitan ≥300)")
    if close.isna().any() or (close <= 0).any():
        blocking.append("hay precios faltantes o no positivos")
    candle_close = close.index[-1] + pd.Timedelta(days=1)
    now = now.tz_localize(None) if now.tzinfo else now
    age_h = (now - candle_close).total_seconds() / 3600
    if age_h > limits.max_data_age_hours:
        blocking.append(f"datos viejos: la última vela cerró hace {age_h:.0f} h")
    jump = close.pct_change().abs().iloc[-5:].max()
    if jump > limits.max_price_jump:
        caution.append(f"salto de precio de {jump:.0%} en los últimos días: solo se permite reducir")
    return blocking, caution


def drawdown_kill(equity: float, peak: float, limits: RiskLimits) -> bool:
    return peak > 0 and equity <= peak * (1 - limits.max_drawdown_kill)
