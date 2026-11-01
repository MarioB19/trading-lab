"""Semáforo de «ganadora»: el control vigente en M1–M5 y M7. Ver reports/semaforo_s02_medicion_preregistro.md.

    PYTHONPATH=src python scripts/research/semaforo_s02_medicion.py

Escribe reports/semaforo_s02_medicion_resultado.json. No cambia config.yaml ni el bot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sprint04_h13_rebalanceo_bloques import E_COST, END, START, YEARS, crypto_block, etf_block  # noqa: E402

from lab.backtest import max_drawdown  # noqa: E402
from lab.data import load_crypto_panel  # noqa: E402
from lab.fixed_costs import with_fixed_cost  # noqa: E402
from lab.portfolio import PortfolioParams, simulate_portfolio  # noqa: E402
from lab.sleeve_rebalance import combine_sleeves  # noqa: E402
from lab.validation import bootstrap_compare  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PREREG_COMMIT = "a52fc1e"
ANN, STRESS, RAILWAY, CAPITAL = 365, 1.5, 60.0, 1000.0
P_MIN = 0.90
SCENARIOS = {"bitso-medido": 0.0049, "bitso-modelo": 0.0037, "global-010": 0.0012}
BENCH_P = PortfolioParams.from_dict(dict(top_k=1, vol_target=None, regime_asset=None, dd_brake=False, max_weight=1.0))


def stats(r: pd.Series) -> dict:
    years = len(r) / ANN
    mult = float((1 + r).prod())
    sd = r.std(ddof=1)
    return {"cagr": mult ** (1 / years) - 1, "vol": float(sd * np.sqrt(ANN)), "sharpe": float(r.mean() / sd * np.sqrt(ANN)),
            "max_dd": float(max_drawdown(r)), "multiple": mult,
            "years": {str(y): float((1 + r.loc[str(y)]).prod() - 1) for y in YEARS if (r.index.year == y).any()}}


def btc_equal_risk(btc: pd.Series, w: float, cost: float) -> pd.Series:
    prices = btc.to_frame("BTC")
    W = pd.DataFrame({"BTC": w}, index=prices.index)
    return simulate_portfolio(prices, W, BENCH_P, cost, 0.05, kill_dd=None)["ret"]


def versus(a: pd.Series, b: pd.Series) -> dict:
    sa, sb = stats(a), stats(b)
    wins = sum(sa["years"][y] > sb["years"][y] for y in sa["years"])
    boot = bootstrap_compare(a, b, n=2000, block=30, seed=11)
    return {"wins": f"{wins}/{len(sa['years'])}", "wins_n": wins, "p_return_better": boot["p_return_better"],
            "p_sharpe_better": boot["p_sharpe_better"], "p_drawdown_smaller": boot["p_drawdown_smaller"]}


def measure(cost: float, stress: float, btc: pd.Series) -> dict:
    rc = crypto_block(START, cost * stress)
    re, _ = etf_block(START, E_COST * stress, rc.index)
    total = combine_sleeves(rc, re, capital=CAPITAL)["ret"]
    total_net = with_fixed_cost(total, CAPITAL, RAILWAY)
    b = btc.loc[rc.index]
    w = float(rc.std() / b.pct_change().fillna(0.0).std())
    bench = btc_equal_risk(b, w, cost * stress)
    btc_hold = b.pct_change().fillna(0.0)
    years = len(rc) / ANN
    # costo del bloque cripto (comisión + spread por rotación), como los sprints
    from sprint02_costo_ejecucion import BASE, CAPITAL as C0, KILL, summary  # noqa: E402
    from lab.portfolio import listed_universe, simulate_funded_portfolio, target_weights  # noqa: E402
    from lab.research_multi import BITSO_TRADABLE  # noqa: E402
    P, _ = load_crypto_panel(False)
    P = P[[a for a in BITSO_TRADABLE if a in P.columns]]
    p = PortfolioParams.from_dict(BASE)
    bt = simulate_funded_portfolio(P, target_weights(P, listed_universe(P), p), p, cost * stress, 0.02, kill_dd=KILL,
                                   initial_capital=C0, min_order_value=25.0, start=START)
    s_bt = summary(bt.loc[:END], cost * stress)
    fees = float(bt.loc[:END, "cost_usd"].sum()) if "cost_usd" in bt else None
    return {"crypto": stats(rc), "etf": stats(re), "total_gross_of_railway": stats(total), "total": stats(total_net),
            "sixty_forty": stats(re), "btc_equal_risk": {**stats(bench), "w": w}, "btc_hold": stats(btc_hold),
            "m1": versus(total_net, re), "m1_no_railway": versus(total, re), "m2": versus(rc, bench),
            "m2_vs_btc_hold": versus(rc, btc_hold),
            "crypto_cost_per_year": s_bt["cost_per_year"], "crypto_turnover": s_bt["turnover_per_year"],
            "crypto_fees_usd": fees, "railway_usd": RAILWAY * years, "years": years}


def main():
    P, _ = load_crypto_panel(False)
    btc = P["BTC"]
    res = {"experiment_id": "semaforo-s02-medicion", "prereg_commit": PREREG_COMMIT, "window": [START, END],
           "railway_usd_per_year": RAILWAY, "p_min": P_MIN, "scenarios": {}}
    for sid, cost in SCENARIOS.items():
        base, stress = measure(cost, 1.0, btc), measure(cost, STRESS, btc)
        m1 = base["m1"]["wins_n"] >= 4 and base["m1"]["p_return_better"] >= P_MIN
        m2 = base["m2"]["p_return_better"] >= P_MIN
        m3 = stress["total"]["max_dd"] >= -0.30 and stress["crypto"]["max_dd"] >= -0.40
        gross = base["crypto"]["cagr"] + base["crypto_cost_per_year"]
        m4 = base["crypto_cost_per_year"] <= 0.06 and base["crypto_cost_per_year"] <= gross / 3
        m5 = (stress["m1"]["wins_n"] >= 4 and stress["m1"]["p_return_better"] >= P_MIN
              and stress["m2"]["p_return_better"] >= P_MIN)
        res["scenarios"][sid] = {
            "cost_per_side": cost, "base": base, "stress": stress, "gross_crypto": gross,
            "verdict": {"M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "ganadora_en_backtest": all([m1, m2, m3, m4, m5])}}
    (ROOT / "reports" / "semaforo_s02_medicion_resultado.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=float))
    for sid, r in res["scenarios"].items():
        b, s = r["base"], r["stress"]
        print(f"== {sid} ({r['cost_per_side']*100:.2f}% por lado) veredicto {r['verdict']}")
        print(f"  total neto Railway {b['total']['cagr']:+.1%} DD {b['total']['max_dd']:.1%} | sin Railway {b['total_gross_of_railway']['cagr']:+.1%}"
              f" | 60/40 {b['sixty_forty']['cagr']:+.1%} DD {b['sixty_forty']['max_dd']:.1%}")
        print(f"  M1 {b['m1']} | sin Railway {b['m1_no_railway']['wins']} p {b['m1_no_railway']['p_return_better']:.3f}")
        print(f"  cripto {b['crypto']['cagr']:+.1%} vol {b['crypto']['vol']:.1%} DD {b['crypto']['max_dd']:.1%} Sharpe {b['crypto']['sharpe']:.2f}"
              f" | BTC igual riesgo (w {b['btc_equal_risk']['w']:.2f}) {b['btc_equal_risk']['cagr']:+.1%} vol {b['btc_equal_risk']['vol']:.1%}"
              f" DD {b['btc_equal_risk']['max_dd']:.1%} | BTC puro {b['btc_hold']['cagr']:+.1%} DD {b['btc_hold']['max_dd']:.1%}")
        print(f"  M2 {b['m2']} | vs BTC puro {b['m2_vs_btc_hold']['wins']} p {b['m2_vs_btc_hold']['p_return_better']:.3f}")
        print(f"  M3 estrés total {s['total']['max_dd']:.1%} cripto {s['crypto']['max_dd']:.1%} | M4 costo {b['crypto_cost_per_year']:.1%}"
              f" bruta {r['gross_crypto']:.1%} | M5 estrés M1 {s['m1']['wins']} p {s['m1']['p_return_better']:.3f} M2 p {s['m2']['p_return_better']:.3f}")
        print(f"  M7 comisiones US${b['crypto_fees_usd']:,.0f} Railway US${b['railway_usd']:,.0f} en {b['years']:.1f} años")
        print("  años total", {y: round(x * 100, 1) for y, x in b["total"]["years"].items()},
              "60/40", {y: round(x * 100, 1) for y, x in b["sixty_forty"]["years"].items()})
        print("  años cripto", {y: round(x * 100, 1) for y, x in b["crypto"]["years"].items()},
              "BTC igual riesgo", {y: round(x * 100, 1) for y, x in b["btc_equal_risk"]["years"].items()})


if __name__ == "__main__":
    main()
