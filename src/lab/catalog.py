"""Catálogo de estrategias para el barrido preregistrado «catalogo100» (solo investigación, bloque cripto).

Cada variante es una función que recibe el mercado (cierres, máximos, mínimos, volumen, elegibilidad,
SPY) y devuelve PESOS OBJETIVO por fecha, decididos al cierre de cada día; el motor
`lab.portfolio.simulate_portfolio` los aplica al día siguiente, con la misma banda, freno por caída y
kill switch que el control, salvo en las variantes que estudian precisamente esas piezas.

Nada de aquí corre en el bot. Una variante que pase la barra se reimplementa en `lab.portfolio`
con su propio preregistro (regla 6 de AGENTS.md). `python -m lab.catalog --describe` imprime las
variantes declaradas y el hash del plan, sin calcular nada.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .portfolio import (PortfolioParams, cap_weights, clean, listed_universe, signals,
                        target_weights)

ANN = 365
BASE = dict(top_k=5, vol_target=0.40, regime_asset="BTC", dd_brake=True, max_weight=0.40,
            mom_windows=(30, 90, 180), ann=ANN)
TOP_K, VOL_TARGET, MAX_W = 5, 0.40, 0.40


@dataclass
class Market:
    C: pd.DataFrame                 # cierres diarios (OKX), calendario diario completo
    H: pd.DataFrame
    L: pd.DataFrame
    V: pd.DataFrame                 # volumen en USD del día
    elig: pd.DataFrame              # listado con ≥250 días de historia
    spy: pd.Series | None = None    # cierre de SPY llevado al calendario diario (ffill)
    etf6040: pd.Series | None = None  # rendimiento diario del 60/40 SPY/IEF (ffill, 0 en fines de semana)
    cache: dict = field(default_factory=dict)

    def ctrl_params(self, **over) -> PortfolioParams:
        return PortfolioParams.from_dict({**BASE, **over})

    def control_weights(self, elig: pd.DataFrame | None = None, **over) -> pd.DataFrame:
        key = ("ctrl", json.dumps(over, sort_keys=True, default=str), id(elig) if elig is not None else None)
        if key not in self.cache:
            self.cache[key] = target_weights(self.C, self.elig if elig is None else elig, self.ctrl_params(**over))
        return self.cache[key]

    def control_signals(self) -> dict:
        if "sig" not in self.cache:
            self.cache["sig"] = signals(self.C, self.ctrl_params())
        return self.cache["sig"]


# ------------------------------------------------------------------ utilidades causales
def sma(C: pd.DataFrame, n: int) -> pd.DataFrame:
    return C.rolling(n, min_periods=n).mean()


def ema(C: pd.DataFrame, n: int) -> pd.DataFrame:
    return C.ewm(span=n, adjust=False, min_periods=n).mean()


def mom(C: pd.DataFrame, window: int, skip: int = 0) -> pd.DataFrame:
    return C.shift(skip) / C.shift(skip + window) - 1


def ewm_vol(C: pd.DataFrame, halflife: int = 20, ann: int = ANN) -> pd.DataFrame:
    return np.log(C).diff().ewm(halflife=halflife, min_periods=60).std() * np.sqrt(ann)


def btc_regime(M: Market, n: int = 200) -> pd.Series:
    """True cuando BTC está sobre su promedio de n días (el filtro de régimen del control, simplificado)."""
    c = M.C["BTC"]
    return (c > c.rolling(n, min_periods=n).mean()).fillna(False)


def risk_weights(mask: pd.DataFrame, C: pd.DataFrame, raw: pd.DataFrame | None = None,
                 vol_target: float | None = VOL_TARGET, max_weight: float = MAX_W,
                 cov_window: int = 90, ann: int = ANN) -> pd.DataFrame:
    """Pesos de los activos marcados en `mask`: proporcionales a `raw` (por omisión 1/volatilidad),
    con tope por activo y escalados para no pasar la volatilidad objetivo (misma mecánica que el control)."""
    C = clean(C)
    vol = ewm_vol(C, ann=ann).values
    rets = np.log(C).diff().values
    m = mask.reindex_like(C).fillna(False).astype(bool).values
    rawv = (raw.reindex_like(C).values if raw is not None else 1.0 / vol)
    n, k = C.shape
    W = np.zeros((n, k))
    for t in range(n):
        ok = m[t] & np.isfinite(vol[t]) & (vol[t] > 0) & np.isfinite(rawv[t]) & (rawv[t] > 0)
        idx = np.flatnonzero(ok)
        if not len(idx):
            continue
        w = cap_weights(rawv[t, idx] / rawv[t, idx].sum(), max_weight) if len(idx) > 1 else np.ones(1)
        if vol_target:
            if len(idx) == 1:
                w = w * min(1.0, vol_target / vol[t, idx[0]])
            else:
                window = rets[max(1, t - cov_window + 1): t + 1][:, idx]
                window = window[np.isfinite(window).all(axis=1)]
                if len(window) >= 30:
                    cov = np.atleast_2d(np.cov(window, rowvar=False) * ann)
                    sp = float(np.sqrt(max(w @ cov @ w, 1e-12)))
                    w = w * min(1.0, vol_target / sp)
        W[t, idx] = w
    return pd.DataFrame(W, index=C.index, columns=C.columns)


def top_k_mask(score: pd.DataFrame, eligible: pd.DataFrame, k: int, largest: bool = True) -> pd.DataFrame:
    s = score.where(eligible)
    if not largest:
        s = -s
    rank = s.rank(axis=1, ascending=False, method="first")
    return (rank <= k) & s.notna()


def vol_target_rows(W: pd.DataFrame, C: pd.DataFrame, vol_target: float = VOL_TARGET, cov_window: int = 90,
                    ann: int = ANN) -> pd.DataFrame:
    """Escala cada fila de pesos para que la volatilidad esperada del portafolio no pase el objetivo."""
    rets = np.log(clean(C)).diff().values
    Wv = W.values.copy()
    for t in range(len(Wv)):
        idx = np.flatnonzero(Wv[t] > 0)
        if len(idx) < 1:
            continue
        window = rets[max(1, t - cov_window + 1): t + 1][:, idx]
        window = window[np.isfinite(window).all(axis=1)]
        if len(window) >= 30:
            cov = np.atleast_2d(np.cov(window, rowvar=False) * ann)
            sp = float(np.sqrt(max(Wv[t, idx] @ cov @ Wv[t, idx], 1e-12)))
            Wv[t, idx] *= min(1.0, vol_target / sp)
    return pd.DataFrame(Wv, index=W.index, columns=W.columns)


# ------------------------------------------------------------------ familias
def f_xsmom(M: Market, window: int, skip: int) -> pd.DataFrame:
    """Momentum transversal: top 5 por momentum/volatilidad entre los de momentum > 0, con régimen BTC."""
    mo = mom(M.C, window, skip)
    score = mo / ewm_vol(M.C)
    elig = M.elig & (mo > 0) & btc_regime(M).values[:, None]
    return risk_weights(top_k_mask(score, elig, TOP_K), M.C)


def f_tsmom_all(M: Market, lookback: int, kind: str) -> pd.DataFrame:
    """Momentum temporal por activo: se tiene todo activo con señal positiva, con paridad de riesgo."""
    on = (mom(M.C, lookback) > 0) if kind == "ret" else (M.C > sma(M.C, lookback))
    return risk_weights(M.elig & on, M.C)


def f_ma_cross(M: Market, fast: int, slow: int, kind: str) -> pd.DataFrame:
    f = sma if kind == "sma" else ema
    return risk_weights(M.elig & (f(M.C, fast) > f(M.C, slow)), M.C)


def f_donchian(M: Market, entry: int, exit: int, scheme: str) -> pd.DataFrame:
    """Ruptura: entra sobre el máximo de `entry` días previos, sale bajo el mínimo de `exit` días previos."""
    C = clean(M.C)
    hi = C.shift(1).rolling(entry, min_periods=entry).max().values
    lo = C.shift(1).rolling(exit, min_periods=exit).min().values
    cv, el = C.values, M.elig.values
    n, k = C.shape
    state = np.zeros(k, bool)
    mask = np.zeros((n, k), bool)
    for t in range(n):
        enter = np.isfinite(hi[t]) & (cv[t] > hi[t])
        leave = ~np.isfinite(cv[t]) | (np.isfinite(lo[t]) & (cv[t] < lo[t])) | ~el[t]
        state = (state | enter) & ~leave
        mask[t] = state & el[t]
    mask = pd.DataFrame(mask, index=C.index, columns=C.columns)
    raw = pd.DataFrame(1.0, index=C.index, columns=C.columns) if scheme == "equal" else None
    return risk_weights(mask, M.C, raw=raw)


def f_lowvol(M: Market, window: int, k: int) -> pd.DataFrame:
    """Entre los activos en tendencia (sobre su promedio de 200 días), los k menos volátiles."""
    vol = np.log(clean(M.C)).diff().rolling(window, min_periods=window).std() * np.sqrt(ANN)
    elig = M.elig & (M.C > sma(M.C, 200)) & btc_regime(M).values[:, None]
    return risk_weights(top_k_mask(vol, elig, k, largest=False), M.C)


def f_control(M: Market, **over) -> pd.DataFrame:
    return M.control_weights(**over)


def f_atr_stop(M: Market, mult: float, wait: int | None) -> pd.DataFrame:
    """Control + stop de salida: si el cierre cae más de `mult` ATR(14) desde el máximo desde la entrada,
    el activo sale y no se recompra hasta que el control lo suelte y lo vuelva a elegir (o pasen `wait` días)."""
    W = M.control_weights().values.copy()
    C = clean(M.C)
    H, L = M.H.reindex_like(C).fillna(C), M.L.reindex_like(C).fillna(C)
    prev = C.shift(1)
    tr = np.maximum.reduce([(H - L).values, (H - prev).abs().values, (L - prev).abs().values])
    atr = pd.DataFrame(tr, index=C.index, columns=C.columns).rolling(14, min_periods=14).mean().values
    cv = C.values
    n, k = W.shape
    out = W.copy()
    peak = np.full(k, np.nan)
    stopped_at = np.full(k, -1)
    for t in range(n):
        for j in range(k):
            if W[t, j] <= 0:
                peak[j], stopped_at[j] = np.nan, -1   # el control soltó el activo: se reinicia
                continue
            if stopped_at[j] >= 0:
                if wait is not None and t - stopped_at[j] >= wait:
                    stopped_at[j], peak[j] = -1, cv[t, j]
                else:
                    out[t, j] = 0.0
                    continue
            peak[j] = cv[t, j] if not np.isfinite(peak[j]) else max(peak[j], cv[t, j])
            if np.isfinite(atr[t, j]) and cv[t, j] < peak[j] - mult * atr[t, j]:
                out[t, j], stopped_at[j] = 0.0, t
    return pd.DataFrame(out, index=M.C.index, columns=M.C.columns)


def dollar_volume_rank(M: Market, window: int = 30) -> pd.DataFrame:
    dv = (M.V * M.C).rolling(window, min_periods=window).median()
    return dv.where(M.elig).rank(axis=1, ascending=False, method="first")


def f_liquidity(M: Market, top_n: int, window: int = 30) -> pd.DataFrame:
    elig = M.elig & (dollar_volume_rank(M, window) <= top_n)
    return M.control_weights(elig=elig)


def f_subset(M: Market, assets: tuple) -> pd.DataFrame:
    elig = M.elig.copy()
    elig.loc[:, [c for c in elig.columns if c not in assets]] = False
    return M.control_weights(elig=elig)


def f_reweight(M: Market, scheme: str) -> pd.DataFrame:
    """Misma selección que el control; otro reparto: partes iguales o proporcional al momentum/vol."""
    W = M.control_weights()
    sel = W > 0
    if scheme == "equal":
        raw = pd.DataFrame(1.0, index=W.index, columns=W.columns)
    else:
        raw = M.control_signals()["score"].clip(lower=0)
    return risk_weights(sel, M.C, raw=raw)


def f_spy_regime(M: Market, with_btc: bool) -> pd.DataFrame:
    bull = (M.spy > M.spy.rolling(200, min_periods=200).mean()).reindex(M.C.index).fillna(False)
    elig = M.elig & bull.values[:, None]
    return M.control_weights(elig=elig, regime_asset="BTC" if with_btc else None)


def f_altseason(M: Market, n: int) -> pd.DataFrame:
    """Altcoins solo cuando ETH/BTC está sobre su promedio de n días; si no, solo BTC."""
    ratio = M.C["ETH"] / M.C["BTC"]
    alt_ok = (ratio > ratio.rolling(n, min_periods=n).mean()).fillna(False)
    elig = M.elig.copy()
    others = [c for c in elig.columns if c != "BTC"]
    elig.loc[~alt_ok, others] = False
    return M.control_weights(elig=elig)


def f_dominance(M: Market, lookback: int) -> pd.DataFrame:
    """Altcoins solo cuando su momentum promedio supera al de BTC (proxy de dominancia)."""
    mo = mom(M.C, lookback)
    others = [c for c in M.C.columns if c != "BTC"]
    alt_ok = (mo[others].where(M.elig[others]).mean(axis=1) > mo["BTC"]).fillna(False)
    elig = M.elig.copy()
    elig.loc[~alt_ok, others] = False
    return M.control_weights(elig=elig)


def f_calendar(M: Market, rule: str) -> pd.DataFrame:
    """Solo BTC, 100% invertido los días que la regla indica (la decisión de t se aplica a t+1)."""
    nxt = M.C.index + pd.Timedelta(days=1)
    if rule == "weekdays":
        hold = nxt.dayofweek < 5
    elif rule == "weekends":
        hold = nxt.dayofweek >= 5
    elif rule == "turn_of_month":
        hold = (nxt.day <= 3) | (nxt.day >= nxt.days_in_month - 2)
    else:  # mid_month
        hold = ~((nxt.day <= 3) | (nxt.day >= nxt.days_in_month - 2))
    W = pd.DataFrame(0.0, index=M.C.index, columns=M.C.columns)
    W.loc[hold & M.elig["BTC"].values, "BTC"] = 1.0
    return W


def f_weekly_reversion(M: Market, window: int, k: int) -> pd.DataFrame:
    """Los lunes compra los k activos en tendencia (sobre 200 días) que más cayeron en `window` días; mantiene la semana."""
    mo = mom(M.C, window)
    elig = M.elig & (M.C > sma(M.C, 200)) & btc_regime(M).values[:, None]
    mask = top_k_mask(mo, elig, k, largest=False)
    W = risk_weights(mask, M.C, raw=pd.DataFrame(1.0, index=M.C.index, columns=M.C.columns))
    monday = M.C.index.dayofweek == 0
    W.loc[~monday] = np.nan
    return W.ffill().fillna(0.0)


def f_ensemble_avg(M: Market, retarget: bool) -> pd.DataFrame:
    parts = [M.control_weights(), f_tsmom_all(M, 90, "sma"), f_donchian(M, 55, 20, "invvol"), f_ma_cross(M, 50, 200, "sma")]
    W = sum(parts) / len(parts)
    return vol_target_rows(W, M.C) if retarget else W


def f_ensemble_vote(M: Market, threshold: int) -> pd.DataFrame:
    votes = (M.C > sma(M.C, 200)).astype(int) + (M.C > sma(M.C, 50)).astype(int) + (mom(M.C, 90) > 0).astype(int)
    return risk_weights(M.elig & (votes >= threshold) & btc_regime(M).values[:, None], M.C)


def f_dual_momentum(M: Market, lookback: int) -> pd.DataFrame:
    """Momentum dual: si BTC tiene momentum positivo, 100% en el activo de mayor momentum (escalado a 40% de vol)."""
    mo = mom(M.C, lookback)
    abs_ok = (mo["BTC"] > 0).fillna(False)
    mask = top_k_mask(mo, M.elig & (mo > 0) & abs_ok.values[:, None], 1)
    return risk_weights(mask, M.C, max_weight=1.0)


def _ml_features(M: Market) -> pd.DataFrame:
    C = clean(M.C)
    sig = M.control_signals()
    feats = {"mom7": mom(C, 7), "mom30": mom(C, 30), "mom90": mom(C, 90), "mom180": mom(C, 180),
             "vol30": np.log(C).diff().rolling(30, min_periods=30).std() * np.sqrt(ANN),
             "trend": sig["trend"], "dist200": C / sma(C, 200) - 1}
    X = pd.concat(feats, axis=1)  # columnas (feature, asset)
    return X.stack(future_stack=True)  # índice (fecha, activo)


def f_ml(M: Market, model: str) -> pd.DataFrame:
    """Modelo reentrenado cada 1 de enero (desde 2021) solo con filas cuya etiqueta (7 días adelante) ya se
    conocía en esa fecha; predice el exceso de rendimiento a 7 días y se compran los 5 mejores entre los elegibles."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import LogisticRegression, Ridge

    C = clean(M.C)
    X = _ml_features(M)
    fwd = C.shift(-7) / C - 1
    y = fwd.sub(fwd.where(M.elig).mean(axis=1), axis=0).stack(future_stack=True).reindex(X.index)
    el = M.elig.stack(future_stack=True).reindex(X.index).fillna(False).astype(bool)
    dates = X.index.get_level_values(0)
    known = dates + pd.Timedelta(days=7)
    good = (X.notna().all(axis=1) & y.notna() & el).values
    pred = np.full(len(X), np.nan)
    for yr in range(2021, C.index[-1].year + 1):
        cutoff = pd.Timestamp(f"{yr}-01-01")
        train = good & (known <= cutoff) & (dates >= pd.Timestamp("2018-06-01"))
        Xt, yt = X.values[train], y.values[train]
        if len(yt) < 500:
            continue
        if model == "ridge":
            mdl = Ridge(alpha=1.0).fit(Xt, yt)
        elif model == "logistic":
            mdl = LogisticRegression(max_iter=500).fit(Xt, (yt > 0).astype(int))
        else:
            mdl = HistGradientBoostingRegressor(max_depth=3, max_iter=150, learning_rate=0.05, random_state=0).fit(Xt, yt)
        rows = ((dates >= cutoff) & (dates < pd.Timestamp(f"{yr + 1}-01-01"))) & X.notna().all(axis=1).values
        Xp = X.values[rows]
        pred[rows] = (mdl.predict_proba(Xp)[:, 1] - 0.5) if model == "logistic" else mdl.predict(Xp)
    P = pd.Series(pred, index=X.index).unstack().reindex_like(C)
    mask = top_k_mask(P, M.elig & (P > 0) & btc_regime(M).values[:, None], TOP_K)
    return risk_weights(mask, M.C)


def f_vol_regime(M: Market, scale: float) -> pd.DataFrame:
    """Control reducido (×scale) cuando la volatilidad de 30 días de BTC supera su mediana del último año."""
    v = np.log(clean(M.C)["BTC"]).diff().rolling(30, min_periods=30).std() * np.sqrt(ANN)
    high = (v > v.rolling(365, min_periods=200).median()).fillna(False)
    W = M.control_weights().copy()
    W.loc[high] *= scale
    return W


# ------------------------------------------------------------------ el catálogo (declarado antes de correr)
def build_catalog() -> list[dict]:
    cat: list[dict] = []

    def add(fam, vid, fn, note="", **sim):
        cat.append({"id": vid, "family": fam, "fn": fn, "note": note, "sim": sim})

    for w in (14, 30, 60, 90, 180, 365):
        for s in (0, 7):
            add("F1 momentum transversal", f"xsmom-w{w}-skip{s}", lambda M, w=w, s=s: f_xsmom(M, w, s))
    for lb in (30, 60, 90, 180, 365):
        for kind in ("ret", "sma"):
            add("F2 momentum temporal (todos los positivos)", f"tsmom-{kind}-{lb}", lambda M, lb=lb, kind=kind: f_tsmom_all(M, lb, kind))
    for f, s in ((10, 50), (20, 50), (20, 100), (50, 100), (50, 200), (100, 300)):
        for kind in ("sma", "ema"):
            add("F3 cruce de promedios", f"macross-{kind}-{f}-{s}", lambda M, f=f, s=s, kind=kind: f_ma_cross(M, f, s, kind))
    for e, x in ((20, 10), (55, 20), (100, 50), (200, 100)):
        for sch in ("invvol", "equal"):
            add("F4 ruptura Donchian", f"donchian-{e}-{x}-{sch}", lambda M, e=e, x=x, sch=sch: f_donchian(M, e, x, sch))
    for w in (30, 90):
        for k in (5, 8):
            add("F5 baja volatilidad", f"lowvol-w{w}-k{k}", lambda M, w=w, k=k: f_lowvol(M, w, k))
    for vt in (0.20, 0.30):
        add("F5 baja volatilidad", f"control-voltarget-{int(vt * 100)}", lambda M, vt=vt: f_control(M, vol_target=vt))
    for mlt in (2.0, 3.0, 4.0, 5.0):
        add("F6 stop ATR sobre el control", f"atrstop-{mlt:g}x", lambda M, mlt=mlt: f_atr_stop(M, mlt, None))
    for wt in (7, 14):
        add("F6 stop ATR sobre el control", f"atrstop-3x-wait{wt}", lambda M, wt=wt: f_atr_stop(M, 3.0, wt))
    for ds, df_ in ((0.05, 0.20), (0.15, 0.40)):
        add("F7 freno y kill switch", f"control-ddbrake-{int(ds * 100)}-{int(df_ * 100)}", lambda M: f_control(M),
            params={"dd_start": ds, "dd_full": df_})  # el freno vive en el motor, no en los pesos
    for fl in (0.0, 0.5):
        add("F7 freno y kill switch", f"control-ddfloor-{int(fl * 100)}", lambda M: f_control(M), params={"dd_floor": fl})
    for kd in (0.30, 0.35):
        add("F7 freno y kill switch", f"control-kill-{int(kd * 100)}", lambda M: f_control(M), kill_dd=kd)
    for n in (5, 8, 10, 12):
        add("F8 universo y liquidez", f"liquidity-top{n}", lambda M, n=n: f_liquidity(M, n))
    add("F8 universo y liquidez", "subset-btc-eth", lambda M: f_subset(M, ("BTC", "ETH")))
    add("F8 universo y liquidez", "subset-majors4", lambda M: f_subset(M, ("BTC", "ETH", "SOL", "XRP")))
    add("F8 universo y liquidez", "liquidity-top8-vol90", lambda M: f_liquidity(M, 8, 90), note="volumen mediano de 90 días en vez de 30")
    for sch in ("equal", "score"):
        add("F9 reparto y número de activos", f"control-reweight-{sch}", lambda M, sch=sch: f_reweight(M, sch))
    for k in (2, 4, 7, 8):
        add("F9 reparto y número de activos", f"control-topk-{k}", lambda M, k=k: f_control(M, top_k=k))
    add("F10 régimen macro (SPY)", "spy-regime-only", lambda M: f_spy_regime(M, False))
    add("F10 régimen macro (SPY)", "spy-and-btc-regime", lambda M: f_spy_regime(M, True))
    for n in (50, 100, 200):
        add("F11 temporada de altcoins", f"altseason-ethbtc-{n}", lambda M, n=n: f_altseason(M, n))
    for lb in (30, 90):
        add("F11 temporada de altcoins", f"dominance-mom{lb}", lambda M, lb=lb: f_dominance(M, lb))
    for rule in ("weekdays", "weekends", "turn_of_month", "mid_month"):
        add("F12 calendario (solo BTC)", f"calendar-{rule}", lambda M, rule=rule: f_calendar(M, rule))
    for w in (7, 14):
        for k in (3, 5):
            add("F13 reversión semanal en tendencia", f"weekrev-w{w}-k{k}", lambda M, w=w, k=k: f_weekly_reversion(M, w, k))
    add("F14 ensambles", "ensemble-avg4", lambda M: f_ensemble_avg(M, False))
    add("F14 ensambles", "ensemble-avg4-voltarget", lambda M: f_ensemble_avg(M, True))
    for th in (2, 3):
        add("F14 ensambles", f"ensemble-vote{th}of3", lambda M, th=th: f_ensemble_vote(M, th))
    for mdl in ("ridge", "logistic", "gbm"):
        add("F15 aprendizaje automático (walk-forward anual)", f"ml-{mdl}", lambda M, mdl=mdl: f_ml(M, mdl))
    for lb in (90, 180, 365):
        add("F16 momentum dual (un activo)", f"dualmom-{lb}", lambda M, lb=lb: f_dual_momentum(M, lb))
    for b in (0.06, 0.10):
        add("F17 banda de rebalanceo", f"control-band-{int(b * 100)}", lambda M: f_control(M), band=b)
    for sc in (0.5, 0.0):
        add("F18 régimen de volatilidad", f"control-volregime-x{int(sc * 100)}", lambda M, sc=sc: f_vol_regime(M, sc))
    add("F1 momentum transversal", "xsmom-w90-skip7-top3", lambda M: risk_weights(
        top_k_mask(mom(M.C, 90, 7) / ewm_vol(M.C), M.elig & (mom(M.C, 90, 7) > 0) & btc_regime(M).values[:, None], 3), M.C))
    return cat


# Referencias informativas: no compiten ni cuentan como intentos.
def reference_weights(M: Market) -> dict[str, pd.DataFrame]:
    C = M.C
    zero = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    btc = zero.copy()
    btc.loc[M.elig["BTC"], "BTC"] = 1.0
    bh = zero.copy()
    bh.loc[M.elig["BTC"], "BTC"] = 0.5
    bh.loc[M.elig["ETH"], "ETH"] = 0.5
    ew = (M.elig.astype(float).div(M.elig.sum(axis=1).replace(0, np.nan), axis=0)).fillna(0.0)
    first = pd.Series(np.r_[True, C.index.month[1:] != C.index.month[:-1]], index=C.index)
    ew_m = ew.where(first).ffill().fillna(0.0)
    on = (C["BTC"] > C["BTC"].rolling(200, min_periods=200).mean()).astype(float)
    on = on.where(C.index.dayofweek == 0).ffill().fillna(0.0)
    f200 = zero.copy()
    f200["BTC"] = on * M.elig["BTC"]
    return {"ref-btc-hold": btc, "ref-btc-eth-5050": bh, "ref-equal-weight-monthly": ew_m, "ref-btc-sma200-monday": f200}


def describe() -> dict:
    cat = build_catalog()
    spec = [{"id": c["id"], "family": c["family"], "sim": c["sim"], "note": c["note"]} for c in cat]
    fams: dict[str, int] = {}
    for c in cat:
        fams[c["family"]] = fams.get(c["family"], 0) + 1
    payload = {"engine": "catalogo100-v1", "base": {k: (list(v) if isinstance(v, tuple) else v) for k, v in BASE.items()},
               "cost": 0.0042, "stress": 0.0063, "band": 0.02, "kill_dd": 0.45, "variants": spec,
               "references": ["ref-btc-hold", "ref-btc-eth-5050", "ref-equal-weight-monthly", "ref-btc-sma200-monday"]}
    payload["config_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    payload["n_variants"], payload["families"] = len(cat), fams
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--describe", action="store_true")
    a = ap.parse_args()
    if a.describe:
        print(json.dumps(describe(), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
