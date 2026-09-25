"""Estrategias: cada una convierte precios en una EXPOSICIÓN OBJETIVO entre 0 y 1.

Reglas del contrato (las verifica tests/test_no_lookahead.py):
  * El valor en la fecha D usa SOLO precios hasta el cierre de D.
  * 0 = todo en efectivo, 1 = todo en BTC. Sin apalancamiento ni cortos
    (en un exchange spot como Bitso no se puede de forma simple y multiplica el riesgo).
  * El motor de backtest aplica la decisión de D al día D+1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANN = 365  # cripto opera todos los días


# ---------------------------------------------------------------- indicadores
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / down)


def realized_vol(close: pd.Series, window: int = 30) -> pd.Series:
    return np.log(close).diff().rolling(window).std() * np.sqrt(ANN)


def _binary(cond: pd.Series, valid: pd.Series) -> pd.Series:
    return cond.astype(float).where(valid, 0.0)


# ---------------------------------------------------------------- estrategias
def buy_hold(close: pd.Series) -> pd.Series:
    """Referencia: comprar y no hacer nada."""
    return pd.Series(1.0, index=close.index)


def sma_trend(close: pd.Series, n: int = 200) -> pd.Series:
    """Dentro si el precio está arriba de su promedio móvil de n días."""
    sma = close.rolling(n).mean()
    return _binary(close > sma, sma.notna())


def sma_cross(close: pd.Series, fast: int = 50, slow: int = 200) -> pd.Series:
    """Dentro si el promedio rápido está arriba del lento ("golden cross")."""
    f, s = close.rolling(fast).mean(), close.rolling(slow).mean()
    return _binary(f > s, s.notna())


def tsmom(close: pd.Series, lookback: int = 90) -> pd.Series:
    """Momentum de serie de tiempo: dentro si el rendimiento de los últimos n días es positivo."""
    ret = close.pct_change(lookback, fill_method=None)
    return _binary(ret > 0, ret.notna())


def donchian(close: pd.Series, entry: int = 55, exit: int = 20) -> pd.Series:
    """Ruptura de canal: entra al romper el máximo de `entry` días, sale al perder el mínimo de `exit`."""
    hi = close.rolling(entry).max().shift(1).values
    lo = close.rolling(exit).min().shift(1).values
    c = close.values
    pos = np.zeros(len(c))
    state = 0.0
    for i in range(len(c)):
        if state == 0 and not np.isnan(hi[i]) and c[i] > hi[i]:
            state = 1.0
        elif state == 1 and not np.isnan(lo[i]) and c[i] < lo[i]:
            state = 0.0
        pos[i] = state
    return pd.Series(pos, index=close.index)


def rsi_reversion(close: pd.Series, n: int = 14, buy_below: float = 30,
                  sell_above: float = 70) -> pd.Series:
    """Reversión a la media: compra cuando el RSI está "sobrevendido", vende cuando está "sobrecomprado"."""
    r = rsi(close, n).values
    pos = np.zeros(len(r))
    state = 0.0
    for i in range(len(r)):
        if np.isnan(r[i]):
            pos[i] = state
            continue
        if state == 0 and r[i] < buy_below:
            state = 1.0
        elif state == 1 and r[i] > sell_above:
            state = 0.0
        pos[i] = state
    return pd.Series(pos, index=close.index)


def trend_ensemble(close: pd.Series, lookbacks=(20, 50, 100, 200)) -> pd.Series:
    """Promedio de varios filtros de tendencia: exposición 0, 25, 50, 75 o 100%.

    No depende de UN parámetro "mágico": si una ventana falla, las demás amortiguan.
    """
    votes = [sma_trend(close, int(n)) for n in lookbacks]
    return sum(votes) / len(votes)


def vol_targeted(exposure: pd.Series, close: pd.Series, target_vol: float = 0.5,
                 window: int = 30, cap: float = 1.0) -> pd.Series:
    """Reduce la posición cuando el mercado está más volátil de lo tolerado."""
    vol = realized_vol(close, window)
    scale = (target_vol / vol).clip(upper=cap).fillna(0.0)
    return (exposure * scale).clip(0, cap)


def trend_ensemble_vt(close: pd.Series, lookbacks=(20, 50, 100, 200),
                      target_vol: float = 0.5) -> pd.Series:
    return vol_targeted(trend_ensemble(close, lookbacks), close, target_vol)


# ---------------------------------------------------------------- machine learning
def ml_features(close: pd.Series) -> pd.DataFrame:
    lr = np.log(close).diff()
    f = pd.DataFrame(index=close.index)
    for n in (1, 5, 20, 60, 120):
        f[f"ret_{n}"] = np.log(close).diff(n)
    f["vol_20"] = lr.rolling(20).std()
    f["vol_60"] = lr.rolling(60).std()
    for n in (50, 200):
        f[f"dist_sma_{n}"] = close / close.rolling(n).mean() - 1
    f["rsi_14"] = rsi(close, 14) / 100
    return f


def ml_model(close: pd.Series, model: str = "logistic", horizon: int = 5,
             retrain_every: int = 30, min_train: int = 730) -> pd.Series:
    """Clasificador que estima P(precio sube en los próximos `horizon` días).

    Walk-forward estricto: en la fecha D solo entrena con ejemplos cuya etiqueta
    ya se conocía en D (es decir, hasta D - horizon). Entra solo si la probabilidad
    supera la frecuencia histórica de subidas (debe ser MÁS optimista que el promedio).
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = ml_features(close)
    y = (close.shift(-horizon) / close - 1 > 0).astype(float)
    y[close.shift(-horizon).isna()] = np.nan
    valid = X.notna().all(axis=1).values
    Xv, yv = X.values, y.values
    out = np.zeros(len(close))
    proba = np.full(len(close), np.nan)
    clf, threshold, last_fit = None, 0.5, -10**9
    for t in range(len(close)):
        if not valid[t]:
            continue
        if t - last_fit >= retrain_every:
            train_idx = np.arange(0, t - horizon + 1)
            train_idx = train_idx[valid[train_idx] & ~np.isnan(yv[train_idx])]
            if len(train_idx) >= min_train:
                if model == "logistic":
                    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=500))
                else:
                    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
                                                         max_iter=150, random_state=0)
                clf.fit(Xv[train_idx], yv[train_idx])
                threshold = float(yv[train_idx].mean())
                last_fit = t
        if clf is not None:
            p = clf.predict_proba(Xv[t:t + 1])[0, 1]
            proba[t] = p
            out[t] = 1.0 if p > threshold else 0.0
    s = pd.Series(out, index=close.index)
    s.attrs["proba"] = pd.Series(proba, index=close.index)
    return s


# ---------------------------------------------------------------- registro
STRATEGIES = {
    "buy_hold": buy_hold,
    "sma_trend": sma_trend,
    "sma_cross": sma_cross,
    "tsmom": tsmom,
    "donchian": donchian,
    "rsi_reversion": rsi_reversion,
    "trend_ensemble": trend_ensemble,
    "trend_ensemble_vt": trend_ensemble_vt,
    "ml_model": ml_model,
}

# Todas las variantes que se prueban. Cada una cuenta como un "intento" al
# corregir por pruebas múltiples: probar 30 cosas y quedarte con la mejor
# infla los resultados, y eso hay que descontarlo.
PARAM_GRID: dict[str, list[dict]] = {
    "sma_trend": [{"n": n} for n in (20, 50, 100, 150, 200)],
    "sma_cross": [{"fast": f, "slow": s} for f, s in ((10, 50), (20, 100), (50, 200))],
    "tsmom": [{"lookback": n} for n in (30, 60, 90, 180, 365)],
    "donchian": [{"entry": e, "exit": x} for e, x in ((20, 10), (55, 20), (100, 50))],
    "rsi_reversion": [{"n": 14, "buy_below": b, "sell_above": s}
                      for b in (25, 30, 35) for s in (55, 70)],
    "trend_ensemble": [{"lookbacks": (20, 50, 100, 200)}, {"lookbacks": (50, 100, 200, 300)}],
    "trend_ensemble_vt": [{"lookbacks": (20, 50, 100, 200), "target_vol": v} for v in (0.4, 0.6)],
    "ml_model": [{"model": "logistic"}, {"model": "gbm"}],
}


def label(name: str, params: dict | None) -> str:
    if not params:
        return name
    parts = []
    for k, v in params.items():
        v = "-".join(str(x) for x in v) if isinstance(v, (list, tuple)) else v
        parts.append(f"{k}={v}")
    return f"{name}({', '.join(parts)})"


def compute(name: str, close: pd.Series, params: dict | None = None) -> pd.Series:
    params = dict(params or {})
    if "lookbacks" in params:
        params["lookbacks"] = tuple(params["lookbacks"])
    return STRATEGIES[name](close, **params).clip(0, 1)
