"""Sprint 01: menos rotación en el bloque cripto. Ver reports/sprint01_costo_cripto_preregistro.md.

    python scripts/research/sprint01_costo_cripto.py

Escribe reports/sprint01_costo_cripto_resultado.{json,md}. No cambia config.yaml ni el bot.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from lab.backtest import max_drawdown, perf
from lab.data import load_crypto_panel
from lab.portfolio import PortfolioParams, listed_universe, simulate_portfolio, target_weights
from lab.research_multi import BITSO_TRADABLE
from lab.validation import bootstrap_compare

ROOT = Path(__file__).resolve().parents[2]
START, END = "2019-01-01", "2026-09-26"
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
COST, STRESS, KILL, ANN = 0.0037, 0.0037 * 1.5, 0.45, 365
THRESHOLD = 1 - 0.10 / 3
BASE = dict(top_k=5, vol_target=0.40, regime_asset="BTC", dd_brake=True, max_weight=0.40,
            mom_windows=(30, 90, 180), ann=ANN)
VARIANTS = {
    "control": dict(band=0.02, buffer=0.0, weekly=False),
    "v1-banda4-margen15": dict(band=0.04, buffer=0.15, weekly=False),
    "v2-semanal": dict(band=0.02, buffer=0.0, weekly=True),
    "v3-semanal-banda4-margen15": dict(band=0.04, buffer=0.15, weekly=True),
}


def run(P, elig, spec, cost):
    p = PortfolioParams.from_dict({**BASE, "rotation_buffer": spec["buffer"]})
    W = target_weights(P, elig, p)
    Ps, Ws = P.loc[START:END], W.loc[START:END]
    check = watch = None
    if spec["weekly"]:
        check = np.asarray(Ps.index.dayofweek == 0)  # lunes UTC
        watch = np.ones(len(Ps), bool)               # freno y kill switch diarios, solo venden
    return simulate_portfolio(Ps, Ws, p, cost, spec["band"], kill_dd=KILL, check=check, watch=watch)


def summary(bt: pd.DataFrame, cost: float) -> dict:
    s = perf(bt, ANN)
    years = len(bt) / ANN
    turnover = float(bt["turnover"].sum() / years)
    by_year = {str(y): float((1 + bt.loc[str(y), "ret"]).prod() - 1) for y in YEARS if str(y) in bt.index.year.astype(str)}
    return {**{k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in s.items()},
            "max_dd": float(max_drawdown(bt["ret"])), "turnover_per_year": turnover,
            "cost_per_year": turnover * cost, "years": by_year,
            "final_multiple": float((1 + bt["ret"]).prod())}


def references(P):
    btc = P[["BTC"]].loc[START:END]
    hold = btc.pct_change().fillna(0.0)["BTC"]
    sma = P["BTC"].rolling(200).mean()
    on = (P["BTC"] > sma).astype(float).loc[START:END]
    mondays = on.index.dayofweek == 0
    pos = on.where(mondays).ffill().fillna(0.0)
    r = btc["BTC"].pct_change().fillna(0.0)
    trades = pos.diff().abs().fillna(0.0)
    sma_ret = pos.shift(1).fillna(0.0) * r - trades * COST
    out = {}
    for name, ret, position, turn in (("BTC comprar y mantener", hold, 1.0, 0.0),
                                      ("BTC con filtro de 200 días (lunes)", sma_ret, pos.shift(1).fillna(0.0), trades)):
        bt = pd.DataFrame({"ret": ret, "turnover": turn, "position": position})
        out[name] = summary(bt, COST)
    return out


def main():
    P, _ = load_crypto_panel(False)
    P = P[[a for a in BITSO_TRADABLE if a in P.columns]]
    elig = listed_universe(P)
    base, stress = {}, {}
    for vid, spec in VARIANTS.items():
        base[vid] = run(P, elig, spec, COST)
        stress[vid] = run(P, elig, spec, STRESS)
    res = {"experiment_id": "sprint01-costo-cripto", "window": [START, END], "cost": COST, "stress_cost": STRESS,
           "threshold_p_return_better": THRESHOLD, "variants": {}, "references": references(P)}
    c = base["control"]
    c_sum = summary(c, COST)
    c_stress = summary(stress["control"], STRESS)
    for vid in VARIANTS:
        s = summary(base[vid], COST)
        st = summary(stress[vid], STRESS)
        row = {"base": s, "stress": st}
        if vid != "control":
            wins = sum(s["years"][y] > c_sum["years"][y] for y in s["years"])
            boot = bootstrap_compare(base[vid]["ret"], c["ret"], n=2000, block=30, seed=11)
            crit = {
                "1_mayoria_de_anos": {"value": f"{wins}/{len(s['years'])}", "pass": wins >= 4},
                "2_bootstrap": {"value": boot["p_return_better"], "pass": boot["p_return_better"] >= THRESHOLD},
                "3_caida_maxima": {"value": s["max_dd"] - c_sum["max_dd"], "pass": s["max_dd"] >= c_sum["max_dd"] - 0.02},
                "4_estres": {"value": st["cagr"] - c_stress["cagr"],
                             "pass": st["cagr"] > c_stress["cagr"]},
            }
            row.update({"bootstrap": boot, "criteria": crit, "approved": all(v["pass"] for v in crit.values())})
        res["variants"][vid] = row
    approved = [v for v, r in res["variants"].items() if r.get("approved")]
    res["decision"] = (max(approved, key=lambda v: res["variants"][v]["stress"]["cagr"]) if approved else None)
    out = ROOT / "reports" / "sprint01_costo_cripto_resultado.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print(json.dumps({v: {"CAGR": r["base"]["cagr"], "Sharpe": r["base"]["sharpe"], "maxDD": r["base"]["max_dd"],
                          "rot": r["base"]["turnover_per_year"], "costo": r["base"]["cost_per_year"],
                          "CAGR_estres": r["stress"]["cagr"], "aprobada": r.get("approved")}
                      for v, r in res["variants"].items()}, indent=1, default=float))
    print("referencias:", json.dumps({k: {"CAGR": v["cagr"], "maxDD": v["max_dd"]} for k, v in res["references"].items()}, default=float))
    print("decisión:", res["decision"])


if __name__ == "__main__":
    main()
