"""Barrido catalogo2-etf: 53 estrategias del bloque de ETFs contra el 60/40. Ver reports/catalogo2_etf_preregistro.md.

    PYTHONPATH=src python scripts/research/catalogo2_etf.py

Escribe reports/catalogo2_etf_resultado.{json,md} y añade las variantes a reports/intentos.csv. No cambia el bot.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalogo2_market import load_market  # noqa: E402
from lab.backtest import max_drawdown, perf  # noqa: E402
from lab.catalog_etf import build_catalog, control_weights, describe, reference_weights  # noqa: E402
from lab.portfolio import PortfolioParams, simulate_portfolio  # noqa: E402
from lab.research_multi import placebo  # noqa: E402
from lab.research_statistics import familywise_block_test  # noqa: E402
from lab.validation import bootstrap_compare, deflated_sharpe  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
START, END, PLACEBO_START = "2008-01-01", "2026-09-25", "2010-01-01"
YEARS = list(range(2010, 2027))
COST, STRESS, KILL, BAND, ANN, BLOCK = 0.0005, 0.00075, None, 0.05, 252, 21  # kill: informativo (enmienda 31-oct)
KILL_INFO = 0.25
MAX_TURNOVER, P_ADJ_SCREEN, DD_SCREEN_PTS, DSR_MIN, EXTRA_TRIALS, YEARS_MIN = 20.0, 0.10, 0.05, 0.95, 43, 9
ALLOCATION_FAMILIES = ("E1", "E2", "E8")
BASE = dict(ann=ANN, dd_brake=False, cov_window=63, dd_peak_window=126, vol_target=None, regime_asset=None)


def params(**over) -> PortfolioParams:
    return PortfolioParams.from_dict({**BASE, **over})


def summary(bt: pd.DataFrame, cost: float) -> dict:
    s = perf(bt, ANN)
    years = len(bt) / ANN
    turnover = float(bt["turnover"].sum() / years)
    by_year = {str(y): float((1 + bt.loc[str(y), "ret"]).prod() - 1) for y in YEARS if (bt.index.year == y).any()}
    sd = bt["ret"].std(ddof=1)
    return {**{k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in s.items()},
            "max_dd": float(max_drawdown(bt["ret"])), "turnover_per_year": turnover, "cost_per_year": turnover * cost,
            "years": by_year, "daily_sharpe": float(bt["ret"].mean() / sd) if sd > 0 else 0.0,
            "exposure": float(bt["position"].mean()), "final_multiple": float((1 + bt["ret"]).prod())}


def simulate(M, W, p, cost, band=BAND):
    return simulate_portfolio(M.C.loc[START:END], W.loc[START:END], p, cost, band, kill_dd=KILL)


def previous_trials() -> list[float]:
    with open(ROOT / "reports" / "intentos.csv", newline="") as f:
        return [float(r["sharpe_diario"]) for r in csv.DictReader(f) if r.get("sharpe_diario")]


def main():
    t0 = time.time()
    M, data_notes = load_market()
    plan, cat = describe(), build_catalog()
    p0 = params()
    W0 = control_weights(M)
    ctrl, ctrl_s = simulate(M, W0, p0, COST), simulate(M, W0, p0, STRESS)
    c_sum, c_stress = summary(ctrl, COST), summary(ctrl_s, STRESS)
    c_sum["would_hit_kill_25"] = bool(c_sum["max_dd"] <= -KILL_INFO)
    cfg = {"cost": COST, "band": BAND, "ann": ANN}
    res = {"experiment_id": "catalogo2-etf", "config_sha256": plan["config_sha256"], "n_variants": len(cat),
           "window": [START, END], "cost": COST, "stress_cost": STRESS, "data": data_notes,
           "rules": {"max_turnover": MAX_TURNOVER, "p_adjusted_screen": P_ADJ_SCREEN, "dd_screen_pts": DD_SCREEN_PTS,
                     "dsr_min": DSR_MIN, "extra_trials": EXTRA_TRIALS, "years_min_wins": YEARS_MIN, "block": BLOCK},
           "control": {"base": c_sum, "stress": c_stress}, "variants": {}, "references": {}}
    runs = {}
    for c in cat:
        W = c["fn"](M)
        sim = c["sim"]
        p, band = params(**sim.get("params", {})), sim.get("band", BAND)
        bt, bt_s = simulate(M, W, p, COST, band), simulate(M, W, p, STRESS, band)
        s, st = summary(bt, COST), summary(bt_s, STRESS)
        runs[c["id"]] = {"bt": bt, "W": W, "p": p}
        kind = "asignación" if c["family"].split()[0] in ALLOCATION_FAMILIES else "señal"
        s["would_hit_kill_25"] = bool(s["max_dd"] <= -KILL_INFO)
        res["variants"][c["id"]] = {"family": c["family"], "kind": kind, "base": s, "stress": st,
                                    "gate_cost": {"turnover": s["turnover_per_year"], "pass": s["turnover_per_year"] <= MAX_TURNOVER},
                                    "stage": "descartada por costos" if s["turnover_per_year"] > MAX_TURNOVER else "barrido"}
        print(f"{c['id']:30s} CAGR {s['cagr']:+.1%} Sharpe {s['sharpe']:.2f} DD {s['max_dd']:.1%} rot {s['turnover_per_year']:.1f}"
              + ("  [costos]" if s["turnover_per_year"] > MAX_TURNOVER else ""), flush=True)
    for name, W in reference_weights(M).items():
        res["references"][name] = summary(simulate(M, W, p0, COST), COST)

    screened = [v for v, r in res["variants"].items() if r["gate_cost"]["pass"]]
    chal = pd.DataFrame({v: runs[v]["bt"]["ret"] for v in screened})
    fw = familywise_block_test(chal, ctrl["ret"], n=2000, block=BLOCK, seed=17)
    res["familywise"] = {k: v for k, v in fw.items() if k != "by_candidate"}
    fw = fw["by_candidate"]
    advancing = []
    for v in screened:
        r, s, st = res["variants"][v], res["variants"][v]["base"], res["variants"][v]["stress"]
        r["familywise"] = fw[v]
        crit = {"p_adjusted": {"value": fw[v]["p_adjusted"], "pass": fw[v]["p_adjusted"] < P_ADJ_SCREEN},
                "sharpe_gt_control": {"value": s["sharpe"] - c_sum["sharpe"], "pass": s["sharpe"] > c_sum["sharpe"]},
                "dd_not_worse_5pts": {"value": s["max_dd"] - c_sum["max_dd"], "pass": s["max_dd"] >= c_sum["max_dd"] - DD_SCREEN_PTS},
                "stress_gt_control": {"value": st["cagr"] - c_stress["cagr"], "pass": st["cagr"] > c_stress["cagr"]}}
        r["screen"] = crit
        if all(x["pass"] for x in crit.values()):
            advancing.append(v)
            r["stage"] = "avanza a confirmación"
        else:
            r["stage"] = "descartada en el barrido"
    res["advancing"] = advancing

    all_srs = previous_trials() + [res["variants"][v]["base"]["daily_sharpe"] for v in res["variants"]]
    res["n_trials_dsr"] = len(all_srs) + EXTRA_TRIALS
    k = max(3, len(advancing))
    thr = 1 - 0.10 / k
    winners = []
    for v in advancing:
        r, s, st = res["variants"][v], res["variants"][v]["base"], res["variants"][v]["stress"]
        bt = runs[v]["bt"]
        wins = sum(s["years"][y] > c_sum["years"][y] for y in s["years"])
        boot = bootstrap_compare(bt["ret"], ctrl["ret"], n=2000, block=BLOCK, seed=11)
        dsr = deflated_sharpe(bt["ret"], all_srs, ANN, extra_trials=EXTRA_TRIALS)
        crit = {"1_anos": {"value": f"{wins}/{len(s['years'])}", "pass": wins >= YEARS_MIN},
                "4_dsr": {"value": dsr["dsr"], "pass": dsr["dsr"] >= DSR_MIN},
                "5_estres": {"value": st["cagr"] - c_stress["cagr"], "pass": st["cagr"] > c_stress["cagr"]}}
        if r["kind"] == "señal":
            plc = placebo(M.C, runs[v]["W"], runs[v]["p"], cfg, PLACEBO_START, n=200, seed=5)
            crit["2_placebo"] = {"value": plc["p_value"], "pass": plc["p_value"] < 0.05}
            crit["3_bootstrap_sharpe"] = {"value": boot["p_sharpe_better"], "pass": boot["p_sharpe_better"] >= thr}
            r["placebo"] = {kk: vv for kk, vv in plc.items() if kk != "sims"}
        else:
            crit["3_bootstrap_return"] = {"value": boot["p_return_better"], "pass": boot["p_return_better"] >= thr}
            crit["6_dd_2pts"] = {"value": s["max_dd"] - c_sum["max_dd"], "pass": s["max_dd"] >= c_sum["max_dd"] - 0.02}
        r.update({"confirm": crit, "bootstrap": boot, "dsr": dsr, "bootstrap_threshold": thr})
        ok = all(x["pass"] for x in crit.values())
        r["stage"] = "GANADORA" if ok else "descartada en confirmación"
        if ok:
            winners.append(v)
    res["winners"] = winners
    res["decision"] = max(winners, key=lambda v: res["variants"][v]["stress"]["sharpe"]) if winners else None
    res["counts"] = {"total": len(cat), "descartadas_por_costos": len(cat) - len(screened), "barrido": len(screened),
                     "avanzan": len(advancing), "ganadoras": len(winners)}
    res["elapsed_s"] = time.time() - t0
    (ROOT / "reports" / "catalogo2_etf_resultado.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    with open(ROOT / "reports" / "intentos.csv", "a", newline="") as f:
        for v, r in res["variants"].items():
            f.write(f"2026-10-31,catalogo2-etf (intento 2 sin kill),{v},{'costo' if r['kind'] == 'asignación' else 'señal'},{r['base']['daily_sharpe']:.5f},{r['stage']}\n")
    print("\ncontrol 60/40:", {k: round(c_sum[k], 3) for k in ("cagr", "sharpe", "max_dd", "turnover_per_year")})
    print("conteos:", res["counts"], "| umbral bootstrap:", round(thr, 3), "| intentos DSR:", res["n_trials_dsr"], "| p global:", round(res["familywise"]["global_p"], 3))
    print("avanzan:", advancing)
    for v in advancing:
        print("  ", v, {k: (round(x["value"], 3) if isinstance(x["value"], float) else x["value"], x["pass"]) for k, x in res["variants"][v]["confirm"].items()})
    print("ganadoras:", winners, "| decisión:", res["decision"], f"| {res['elapsed_s']:.0f}s")


if __name__ == "__main__":
    main()
