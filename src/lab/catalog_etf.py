"""Catálogo 2: estrategias para el bloque de ETFs (investigación, preregistrado como «catalogo2-etf»).

El bloque de ETFs es la mitad del capital y hoy corre un 60/40 SPY/IEF pasivo con banda de 5 puntos. Su costo es
≈0.05% por lado, así que —a diferencia de cripto— una ventaja pequeña puede sobrevivir a los costos. Cada variante
devuelve PESOS OBJETIVO por día de bolsa, decididos al cierre; el motor `lab.portfolio.simulate_portfolio` los
aplica al día siguiente. Las decisiones «mensuales» se toman el primer día de bolsa de cada mes y se mantienen.

Nada de aquí corre en el bot. `python -m lab.catalog_etf --describe` imprime las variantes y el hash del plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .catalog import ewm_vol, mom, risk_weights, sma, top_k_mask, vol_target_rows
from .portfolio import clean, listed_universe, rebalance_days

ANN = 252
CONTROL_MIX = {"SPY": 0.6, "IEF": 0.4}
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB"]
CLASSES = ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]


@dataclass
class EtfMarket:
    C: pd.DataFrame            # cierres ajustados, días de bolsa
    elig: pd.DataFrame         # listado con ≥250 días
    cache: dict = field(default_factory=dict)


def fixed_mix(M: EtfMarket, mix: dict[str, float]) -> pd.DataFrame:
    """Mezcla fija; si un ETF aún no cotiza, su parte se reparte entre los demás disponibles."""
    W = pd.DataFrame(0.0, index=M.C.index, columns=M.C.columns)
    for k, v in mix.items():
        W[k] = v
    W = W.where(M.elig, 0.0)
    tot = W.sum(axis=1).replace(0, np.nan)
    return W.div(tot, axis=0).fillna(0.0)


def monthly(W: pd.DataFrame) -> pd.DataFrame:
    """Decisión el primer día de bolsa del mes; se mantiene el resto (el motor deja derivar los pesos)."""
    out = W.copy()
    out.loc[~rebalance_days(W.index)] = np.nan
    return out.ffill().fillna(0.0)


def f_fixed(M, mix, freq="daily"):
    W = fixed_mix(M, mix)
    return monthly(W) if freq == "monthly" else W


def f_risk_parity(M, assets, window):
    vol = np.log(clean(M.C[assets])).diff().rolling(window, min_periods=window).std() * np.sqrt(ANN)
    raw = (1.0 / vol).where(M.elig[assets])
    W = raw.div(raw.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    full = pd.DataFrame(0.0, index=M.C.index, columns=M.C.columns)
    full[assets] = W
    return monthly(full)


def f_trend_overlay(M, n, risk_off):
    """60/40 cuando SPY está sobre su promedio de n días; si no, 100% en `risk_off` (IEF) o en efectivo."""
    base = fixed_mix(M, CONTROL_MIX)
    on = (M.C["SPY"] > sma(M.C[["SPY"]], n)["SPY"]).fillna(False)
    W = base.copy()
    W.loc[~on] = 0.0
    if risk_off:
        W.loc[~on, risk_off] = 1.0
    return W


def f_gem(M, months):
    """Momentum dual (Antonacci): SPY vs EFA por rendimiento de `months` meses; si el ganador no supera a IEF, IEF."""
    n = 21 * months
    r = mom(M.C, n)
    W = pd.DataFrame(0.0, index=M.C.index, columns=M.C.columns)
    pick_spy = (r["SPY"] >= r["EFA"].fillna(-np.inf))
    winner = np.where(pick_spy, "SPY", "EFA")
    win_r = np.where(pick_spy, r["SPY"], r["EFA"])
    bond_ok = ((win_r > r["IEF"].fillna(-np.inf).values) & np.isfinite(win_r))
    choice = np.where(bond_ok, winner, "IEF")
    valid = np.isfinite(win_r)
    for asset in ("SPY", "EFA", "IEF"):
        W.loc[valid & (choice == asset), asset] = 1.0
    return monthly(W.where(M.elig, 0.0))


def f_sector_momentum(M, months, k, bond_share, trend_filter):
    n = 21 * months
    r = mom(M.C[SECTORS], n)
    mask = top_k_mask(r, M.elig[SECTORS], k)
    eq = mask.astype(float).div(mask.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) * (1 - bond_share)
    W = pd.DataFrame(0.0, index=M.C.index, columns=M.C.columns)
    W[SECTORS] = eq
    if trend_filter:
        on = (M.C["SPY"] > sma(M.C[["SPY"]], 200)["SPY"]).fillna(False)
        W.loc[~on, SECTORS] = 0.0
        W.loc[~on, "IEF"] = 1.0
    if bond_share:
        W.loc[W["IEF"] == 0, "IEF"] = bond_share
    return monthly(W.where(M.elig, 0.0))


def f_class_momentum(M, k, absolute, scheme):
    r = mom(M.C[CLASSES], 252, 21)  # 12 meses menos el último
    elig = M.elig[CLASSES] & ((r > 0) if absolute else True)
    mask = top_k_mask(r, elig, k)
    if scheme == "equal":
        W = mask.astype(float).div(mask.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    else:
        vol = np.log(clean(M.C[CLASSES])).diff().rolling(63, min_periods=63).std() * np.sqrt(ANN)
        raw = (1.0 / vol).where(mask)
        W = raw.div(raw.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    full = pd.DataFrame(0.0, index=M.C.index, columns=M.C.columns)
    full[CLASSES] = W
    if absolute:
        full["IEF"] = full["IEF"] + (1.0 - full.sum(axis=1)).clip(lower=0)  # lo que no está en riesgo, en IEF
    return monthly(full)


def f_vol_target(M, target):
    base = fixed_mix(M, CONTROL_MIX)
    return vol_target_rows(base, M.C, vol_target=target, cov_window=63, ann=ANN)


def f_bond_switch(M, n):
    """60/40 cuyo 40% va a TLT cuando TLT está sobre su promedio de n días; si no, a IEF."""
    base = fixed_mix(M, CONTROL_MIX)
    long_ok = (M.C["TLT"] > sma(M.C[["TLT"]], n)["TLT"]).fillna(False) & M.elig["TLT"]
    W = base.copy()
    W.loc[long_ok, "TLT"] = W.loc[long_ok, "IEF"]
    W.loc[long_ok, "IEF"] = 0.0
    return W


def build_catalog() -> list[dict]:
    cat: list[dict] = []

    def add(fam, vid, fn, note="", **sim):
        cat.append({"id": vid, "family": fam, "fn": fn, "note": note, "sim": sim})

    mixes = {
        "mix-50-50": {"SPY": 0.5, "IEF": 0.5}, "mix-70-30": {"SPY": 0.7, "IEF": 0.3}, "mix-40-60": {"SPY": 0.4, "IEF": 0.6},
        "mix-60-40-tlt": {"SPY": 0.6, "TLT": 0.4}, "mix-permanente": {"SPY": 0.25, "TLT": 0.25, "GLD": 0.25, "IEF": 0.25},
        "mix-todo-clima": {"SPY": 0.30, "TLT": 0.40, "IEF": 0.15, "GLD": 0.075, "DBC": 0.075},
        "mix-60-40-oro10": {"SPY": 0.55, "IEF": 0.35, "GLD": 0.10}, "mix-global-4": {"SPY": 0.25, "EFA": 0.25, "IEF": 0.25, "GLD": 0.25},
    }
    for vid, mix in mixes.items():
        add("E1 mezclas fijas", vid, lambda M, mix=mix: f_fixed(M, mix))
    for assets in (("SPY", "IEF"), ("SPY", "TLT", "GLD"), ("SPY", "IEF", "GLD", "DBC"), ("SPY", "EFA", "EEM", "IEF", "TLT", "GLD")):
        for w in (63, 126):
            add("E2 paridad de riesgo (mensual)", f"rp-{'-'.join(a.lower() for a in assets)}-w{w}",
                lambda M, assets=list(assets), w=w: f_risk_parity(M, assets, w))
    for n in (100, 200, 300):
        add("E3 tendencia sobre el 60/40", f"trend-spy{n}-to-ief", lambda M, n=n: f_trend_overlay(M, n, "IEF"))
        add("E3 tendencia sobre el 60/40", f"trend-spy{n}-to-cash", lambda M, n=n: f_trend_overlay(M, n, None))
    for m in (3, 6, 12):
        add("E4 momentum dual (GEM)", f"gem-{m}m", lambda M, m=m: f_gem(M, m))
    for m in (6, 12):
        for k in (3, 5):
            add("E5 momentum de sectores", f"sector-{m}m-top{k}", lambda M, m=m, k=k: f_sector_momentum(M, m, k, 0.0, False))
        add("E5 momentum de sectores", f"sector-{m}m-top3-ief40", lambda M, m=m: f_sector_momentum(M, m, 3, 0.4, False))
        add("E5 momentum de sectores", f"sector-{m}m-top3-trend", lambda M, m=m: f_sector_momentum(M, m, 3, 0.0, True))
    for k in (2, 3, 4):
        for absolute in (False, True):
            add("E6 momentum entre clases de activo", f"class-top{k}{'-abs' if absolute else ''}-equal",
                lambda M, k=k, a=absolute: f_class_momentum(M, k, a, "equal"))
        add("E6 momentum entre clases de activo", f"class-top{k}-abs-invvol", lambda M, k=k: f_class_momentum(M, k, True, "invvol"))
    for vt in (0.06, 0.08, 0.10, 0.12):
        add("E7 volatilidad objetivo sobre el 60/40", f"voltarget-{int(vt * 100)}", lambda M, vt=vt: f_vol_target(M, vt))
    add("E8 rebalanceo del 60/40", "control-mensual", lambda M: f_fixed(M, CONTROL_MIX, "monthly"))
    for b in (0.02, 0.10):
        add("E8 rebalanceo del 60/40", f"control-band-{int(b * 100)}", lambda M: f_fixed(M, CONTROL_MIX), band=b)
    for n in (100, 200):
        add("E9 duración del bono (IEF/TLT)", f"bondswitch-tlt{n}", lambda M, n=n: f_bond_switch(M, n))
    for ds, df_ in ((0.05, 0.20), (0.10, 0.30)):
        add("E10 freno por caída sobre el 60/40", f"control-ddbrake-{int(ds * 100)}-{int(df_ * 100)}",
            lambda M: f_fixed(M, CONTROL_MIX), params={"dd_brake": True, "dd_start": ds, "dd_full": df_})
    return cat


def control_weights(M: EtfMarket) -> pd.DataFrame:
    return fixed_mix(M, CONTROL_MIX)


def reference_weights(M: EtfMarket) -> dict[str, pd.DataFrame]:
    return {"ref-spy-hold": fixed_mix(M, {"SPY": 1.0}), "ref-ief-hold": fixed_mix(M, {"IEF": 1.0})}


def describe() -> dict:
    cat = build_catalog()
    spec = [{"id": c["id"], "family": c["family"], "sim": c["sim"], "note": c["note"]} for c in cat]
    fams: dict[str, int] = {}
    for c in cat:
        fams[c["family"]] = fams.get(c["family"], 0) + 1
    payload = {"engine": "catalogo2-etf-v1", "control": CONTROL_MIX, "cost": 0.0005, "stress": 0.00075, "band": 0.05,
               "kill_dd": 0.25, "ann": ANN, "variants": spec, "references": ["ref-spy-hold", "ref-ief-hold"]}
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
