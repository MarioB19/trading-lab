"""Sprint 03 (H1b): bloquear la recompra 2 o 3 días tras una salida total. Ver reports/sprint03_h1b_recompra_preregistro.md.

    python scripts/research/sprint03_h1b_recompra.py

Escribe reports/sprint03_h1b_recompra_resultado.{json,md}. No cambia config.yaml ni el bot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprint02_costo_ejecucion import BASE, CAPITAL, COST, KILL, START, END, STRESS, YEARS, pct, summary  # noqa: E402

from lab.data import load_crypto_panel  # noqa: E402
from lab.portfolio import PortfolioParams, listed_universe, simulate_funded_portfolio, target_weights  # noqa: E402
from lab.reentry import apply_reentry_cooldown  # noqa: E402
from lab.research_multi import BITSO_TRADABLE  # noqa: E402
from lab.validation import bootstrap_compare  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MIN_ORDER = 25.0
THRESHOLD = 1 - 0.10 / 2
VARIANTS = {"control": 0, "h1b-espera2": 2, "h1b-espera3": 3}
PREREG_COMMIT = "7b48a6b"


def funded_yearly(P, W, p, cost):
    parts = []
    for y in YEARS:
        end = f"{y}-12-31" if y < YEARS[-1] else END
        bt = simulate_funded_portfolio(P.loc[:end], W.loc[:end], p, cost, 0.02, kill_dd=KILL, initial_capital=CAPITAL,
                                       min_order_value=MIN_ORDER, start=f"{y}-01-01")
        bt.attrs = {}
        parts.append(bt)
    return pd.concat(parts)


def criteria(var, ctrl, vr, cr):
    wins = sum(var["base"]["years"][y] > ctrl["base"]["years"][y] for y in var["base"]["years"])
    boot = bootstrap_compare(vr, cr, n=2000, block=30, seed=11)
    crit = {
        "1_mayoria_de_anos": {"value": f"{wins}/{len(var['base']['years'])}", "pass": wins >= 4},
        "2_bootstrap": {"value": boot["p_return_better"], "pass": boot["p_return_better"] >= THRESHOLD},
        "3_caida_maxima": {"value": var["base"]["max_dd"] - ctrl["base"]["max_dd"],
                           "pass": var["base"]["max_dd"] >= ctrl["base"]["max_dd"] - 0.02},
        "4_estres": {"value": var["stress"]["cagr"] - ctrl["stress"]["cagr"],
                     "pass": var["stress"]["cagr"] > ctrl["stress"]["cagr"]},
    }
    return {"bootstrap": boot, "criteria": crit, "approved": all(c["pass"] for c in crit.values())}


def main():
    P, _ = load_crypto_panel(False)
    P = P[[a for a in BITSO_TRADABLE if a in P.columns]]
    elig = listed_universe(P)
    p = PortfolioParams.from_dict(BASE)
    W0 = target_weights(P, elig, p)
    res = {"experiment_id": "sprint03-h1b-recompra", "window": [START, END], "cost": COST, "stress_cost": STRESS,
           "min_order_value": MIN_ORDER, "threshold_p_return_better": THRESHOLD, "prereg_commit": PREREG_COMMIT,
           "mode_a": {}, "mode_b": {}}
    rets_a, rets_b = {}, {}
    for vid, n in VARIANTS.items():
        W = apply_reentry_cooldown(W0, n)
        a, a_s = funded_yearly(P, W, p, COST), funded_yearly(P, W, p, STRESS)
        b = simulate_funded_portfolio(P, W, p, COST, 0.02, kill_dd=KILL, initial_capital=CAPITAL,
                                      min_order_value=MIN_ORDER, start=START)
        b_s = simulate_funded_portfolio(P, W, p, STRESS, 0.02, kill_dd=KILL, initial_capital=CAPITAL,
                                        min_order_value=MIN_ORDER, start=START)
        res["mode_a"][vid] = {"base": summary(a, COST), "stress": summary(a_s, STRESS),
                              "trades_per_year": float((a["turnover"] > 0).sum() / (len(a) / 365)),
                              "sharpe_daily": float(a["ret"].mean() / a["ret"].std())}
        res["mode_b"][vid] = {"base": summary(b, COST), "stress": summary(b_s, STRESS)}
        rets_a[vid], rets_b[vid] = a["ret"], b["ret"]
    for vid in VARIANTS:
        if vid == "control":
            continue
        res["mode_a"][vid].update(criteria(res["mode_a"][vid], res["mode_a"]["control"], rets_a[vid], rets_a["control"]))
        res["mode_b"][vid]["bootstrap"] = bootstrap_compare(rets_b[vid], rets_b["control"], n=2000, block=30, seed=11)
    approved = [v for v in VARIANTS if v != "control" and res["mode_a"][v]["approved"]]
    res["decision"] = max(approved, key=lambda v: res["mode_a"][v]["stress"]["cagr"]) if approved else None
    (ROOT / "reports" / "sprint03_h1b_recompra_resultado.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=float))
    for mode in ("mode_a", "mode_b"):
        print(mode)
        for v, r in res[mode].items():
            print(f"  {v:12s} CAGR {pct(r['base']['cagr'])} Sharpe {r['base']['sharpe']:.2f} DD {pct(r['base']['max_dd'])} "
                  f"rot {r['base']['turnover_per_year']:.1f} costo {r['base']['cost_per_year']*100:.1f}% estrés {pct(r['stress']['cagr'])} "
                  f"años {[round(x*100,1) for x in r['base']['years'].values()]}")
            if "criteria" in r:
                print("    ", {k: (c["value"], c["pass"]) for k, c in r["criteria"].items()}, "aprobada", r["approved"])
            if mode == "mode_b" and "bootstrap" in r:
                print("     boot B", r["bootstrap"]["p_return_better"])
    print("decisión", res["decision"])


if __name__ == "__main__":
    main()
