"""Catálogo 3: señales EXÓGENAS (sentimiento, on-chain, stablecoins) como capas sobre el control de cripto.

Cada variante multiplica los pesos del control por un factor diario m(t) ∈ [0, 1] que depende de una serie que no
está en los precios: índice de miedo/codicia (alternative.me), MVRV, direcciones activas, BTC en exchanges y hash
rate (CoinMetrics community) y oferta total de stablecoins (DefiLlama). Dos variantes usan el miedo/codicia como
regla autónoma sobre BTC. Causalidad: las series on-chain y de stablecoins del día D se publican al cierre de D y se
usan con un día de rezago; el miedo/codicia del día D se publica al abrir D y se usa sin rezago. Donde la serie no
existe todavía, m = 1 (la variante es el control). Solo investigación; `--describe` imprime el plan y su hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .catalog import Market


@dataclass
class Exog:
    fng: pd.Series            # 0–100, sin rezago
    mvrv: pd.Series           # CapMVRVCur de BTC, con 1 día de rezago
    adr: pd.Series            # direcciones activas de BTC, rezago 1
    exsup: pd.Series          # BTC en exchanges (SplyExNtv), rezago 1
    hashrate: pd.Series       # rezago 1
    stables: pd.Series        # oferta total de stablecoins en USD, rezago 1; fiable desde mediados de 2020
    cache: dict = field(default_factory=dict)


def align(series: pd.Series, index: pd.DatetimeIndex, lag: int) -> pd.Series:
    """Lleva la serie al calendario diario, propaga el último valor conocido y aplica el rezago."""
    s = series.sort_index()
    s = s[~s.index.duplicated()]
    return s.reindex(index.union(s.index)).ffill().reindex(index).shift(lag)


def load_exog(index: pd.DatetimeIndex, fng: pd.DataFrame, cm: pd.DataFrame, stables: pd.DataFrame,
              stables_from: str = "2020-07-01") -> Exog:
    st = stables["stables_usd"].copy()
    st.loc[:pd.Timestamp(stables_from) - pd.Timedelta(days=1)] = np.nan  # cobertura incompleta antes
    return Exog(fng=align(fng["fng"], index, 0), mvrv=align(cm["btc_CapMVRVCur"], index, 1),
                adr=align(cm["btc_AdrActCnt"], index, 1), exsup=align(cm["btc_SplyExNtv"], index, 1),
                hashrate=align(cm["btc_HashRate"], index, 1), stables=align(st, index, 1))


def scale(M: Market, m: pd.Series) -> pd.DataFrame:
    """Pesos del control × m(t); donde m es NaN, el control tal cual."""
    W = M.control_weights()
    return W.mul(m.reindex(W.index).fillna(1.0).clip(0.0, 1.0), axis=0)


def step(series: pd.Series, cond: pd.Series, value: float) -> pd.Series:
    """m = value donde cond es True (y la serie existe), 1 en el resto; NaN donde la serie no existe."""
    m = pd.Series(1.0, index=series.index)
    m[cond.fillna(False)] = value
    m[series.isna()] = np.nan
    return m


def zscore(series: pd.Series, window: int = 365) -> pd.Series:
    return (series - series.rolling(window, min_periods=window // 2).mean()) / series.rolling(window, min_periods=window // 2).std()


def pct(series: pd.Series, n: int) -> pd.Series:
    return series / series.shift(n) - 1


# ------------------------------------------------------------------ familias
def x_fng_cut(M, X, thr, value=0.0, smooth=1):
    f = X.fng.rolling(smooth).mean() if smooth > 1 else X.fng
    return scale(M, step(f, f >= thr, value))


def x_fng_linear(M, X):
    return scale(M, ((100 - X.fng) / 60).clip(0.25, 1.0))


def x_fng_follow(M, X):
    return scale(M, step(X.fng, X.fng < 50, 0.5))


def x_mvrv_cut(M, X, thr, value=0.0):
    return scale(M, step(X.mvrv, X.mvrv >= thr, value))


def x_mvrv_linear(M, X):
    return scale(M, ((4.0 - X.mvrv) / 2.0).clip(0.25, 1.0))


def x_mvrv_z(M, X, z=2.0):
    zs = zscore(X.mvrv)
    return scale(M, step(zs, zs > z, 0.0))


def x_exsup(M, X, n, value=0.5):
    ch = pct(X.exsup, n)
    return scale(M, step(ch, ch > 0, value))  # entradas netas a exchanges = presión de venta


def x_exsup_cut(M, X, n=30, thr=0.02):
    ch = pct(X.exsup, n)
    return scale(M, step(ch, ch > thr, 0.0))


def x_adr(M, X, n, value=0.5):
    sm = X.adr.rolling(7).mean()
    ch = pct(sm, n)
    return scale(M, step(ch, ch <= 0, value))


def x_adr_cut(M, X, n=30, thr=-0.10):
    ch = pct(X.adr.rolling(7).mean(), n)
    return scale(M, step(ch, ch < thr, 0.0))


def x_stab(M, X, n, value=0.5):
    g = pct(X.stables, n)
    return scale(M, step(g, g <= 0, value))


def x_stab_cut(M, X, n=30, thr=-0.01):
    g = pct(X.stables, n)
    return scale(M, step(g, g < thr, 0.0))


def x_stab_linear(M, X):
    g = pct(X.stables, 30)
    return scale(M, (0.5 + g * 10).clip(0.25, 1.0).where(g.notna()))


def x_hash_ribbon(M, X, value=0.5):
    fast, slow = X.hashrate.rolling(30).mean(), X.hashrate.rolling(60).mean()
    return scale(M, step(fast, fast < slow, value))


def composite(X) -> pd.Series:
    parts = [-zscore(X.fng), -zscore(X.mvrv), zscore(pct(X.stables, 30)), -zscore(pct(X.exsup, 30))]
    return pd.concat(parts, axis=1).mean(axis=1, skipna=True).where(pd.concat(parts, axis=1).notna().sum(axis=1) >= 2)


def x_comp_cut(M, X, thr=-1.0):
    c = composite(X)
    return scale(M, step(c, c < thr, 0.0))


def x_comp_half(M, X, thr=-0.5):
    c = composite(X)
    return scale(M, step(c, c < thr, 0.5))


def x_comp_linear(M, X):
    c = composite(X)
    return scale(M, (0.75 + 0.25 * c).clip(0.25, 1.0).where(c.notna()))


def x_fng_btc(M, X, lo, hi):
    """Regla autónoma: 100% BTC desde que el índice baja de `lo` hasta que supera `hi`; si no, efectivo."""
    f = X.fng
    state = np.zeros(len(f), bool)
    on = False
    vals = f.values
    for i, v in enumerate(vals):
        if np.isnan(v):
            state[i] = False
            continue
        if not on and v < lo:
            on = True
        elif on and v > hi:
            on = False
        state[i] = on
    W = pd.DataFrame(0.0, index=M.C.index, columns=M.C.columns)
    W.loc[state & M.elig["BTC"].values, "BTC"] = 1.0
    return W


def build_catalog() -> list[dict]:
    cat: list[dict] = []

    def add(fam, vid, fn, note=""):
        cat.append({"id": vid, "family": fam, "fn": fn, "note": note, "sim": {}})

    for thr in (75, 80, 90):
        add("X1 miedo y codicia", f"fng-cut{thr}", lambda M, X, thr=thr: x_fng_cut(M, X, thr))
    add("X1 miedo y codicia", "fng-half75", lambda M, X: x_fng_cut(M, X, 75, 0.5))
    for thr in (75, 80):
        add("X1 miedo y codicia", f"fng-sma7-cut{thr}", lambda M, X, thr=thr: x_fng_cut(M, X, thr, 0.0, 7))
    add("X1 miedo y codicia", "fng-linear", x_fng_linear)
    add("X1 miedo y codicia", "fng-follow50", x_fng_follow)
    for thr in (2.5, 3.0, 3.5):
        add("X2 MVRV de BTC", f"mvrv-cut{thr:g}", lambda M, X, thr=thr: x_mvrv_cut(M, X, thr))
    for thr in (3.0, 3.5):
        add("X2 MVRV de BTC", f"mvrv-half{thr:g}", lambda M, X, thr=thr: x_mvrv_cut(M, X, thr, 0.5))
    add("X2 MVRV de BTC", "mvrv-linear", x_mvrv_linear)
    add("X2 MVRV de BTC", "mvrv-z2", x_mvrv_z)
    for n in (30, 90):
        add("X3 BTC en exchanges", f"exsup-in{n}-half", lambda M, X, n=n: x_exsup(M, X, n))
    add("X3 BTC en exchanges", "exsup-in30-cut2pct", x_exsup_cut)
    add("X3 BTC en exchanges", "exsup-z2-cut", lambda M, X: scale(M, step(zscore(pct(X.exsup, 30)), zscore(pct(X.exsup, 30)) > 2, 0.0)))
    for n in (30, 90):
        add("X4 direcciones activas", f"adr-mom{n}-half", lambda M, X, n=n: x_adr(M, X, n))
    add("X4 direcciones activas", "adr-drop10-cut", x_adr_cut)
    for n in (30, 90):
        add("X5 oferta de stablecoins", f"stab-g{n}-half", lambda M, X, n=n: x_stab(M, X, n))
    add("X5 oferta de stablecoins", "stab-shrink1pct-cut", x_stab_cut)
    add("X5 oferta de stablecoins", "stab-linear", x_stab_linear)
    add("X6 hash ribbon", "hash-ribbon-half", x_hash_ribbon)
    add("X6 hash ribbon", "hash-ribbon-cut", lambda M, X: x_hash_ribbon(M, X, 0.0))
    add("X7 compuesto (4 señales)", "comp-cut-1", x_comp_cut)
    add("X7 compuesto (4 señales)", "comp-half-05", x_comp_half)
    add("X7 compuesto (4 señales)", "comp-linear", x_comp_linear)
    add("X8 miedo y codicia como regla sobre BTC", "fngbtc-20-80", lambda M, X: x_fng_btc(M, X, 20, 80))
    add("X8 miedo y codicia como regla sobre BTC", "fngbtc-25-75", lambda M, X: x_fng_btc(M, X, 25, 75))
    return cat


def describe() -> dict:
    cat = build_catalog()
    spec = [{"id": c["id"], "family": c["family"], "sim": c["sim"], "note": c["note"]} for c in cat]
    fams: dict[str, int] = {}
    for c in cat:
        fams[c["family"]] = fams.get(c["family"], 0) + 1
    payload = {"engine": "catalogo3-exog-v1", "base_control": "catalogo100 control (tendencia + momentum)", "cost": 0.0042,
               "stress": 0.0063, "band": 0.02, "kill_dd": 0.45, "lags": {"fng": 0, "coinmetrics": 1, "stables": 1},
               "stables_from": "2020-07-01", "variants": spec}
    payload["config_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    payload["n_variants"], payload["families"] = len(cat), fams
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--describe", action="store_true")
    if ap.parse_args().describe:
        print(json.dumps(describe(), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
