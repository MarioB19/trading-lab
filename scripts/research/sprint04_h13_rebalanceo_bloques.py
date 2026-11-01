"""Sprint 04 (H13): rebalancear entre el bloque cripto y el de ETFs. Ver reports/sprint04_h13_rebalanceo_bloques_preregistro.md.

    PYTHONPATH=src python scripts/research/sprint04_h13_rebalanceo_bloques.py

Escribe reports/sprint04_h13_rebalanceo_bloques_resultado.json. No cambia config.yaml ni el bot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalogo2_market import load_market  # noqa: E402
from lab.backtest import max_drawdown  # noqa: E402
from lab.catalog_etf import control_weights  # noqa: E402
from lab.data import load_crypto_panel  # noqa: E402
from lab.portfolio import (PortfolioParams, listed_universe, simulate_funded_portfolio,  # noqa: E402
                           simulate_portfolio, target_weights)
from lab.research_multi import BITSO_TRADABLE  # noqa: E402
from lab.sleeve_rebalance import combine_sleeves  # noqa: E402
from lab.validation import bootstrap_compare  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PREREG_COMMIT = "cbe82b5"
START, END = "2019-01-01", "2026-09-25"
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
ROLLING_STARTS = [2019, 2020, 2021, 2022, 2023, 2024]
ANN = 365
THRESHOLD = 1 - 0.10 / 3
# bloque cripto (control vigente, como sprint 03)
C_COST, C_KILL, C_MIN_ORDER, C_BAND = 0.0037, 0.45, 25.0, 0.02
C_BASE = dict(top_k=5, vol_target=0.40, regime_asset="BTC", dd_brake=True, max_weight=0.40,
              mom_windows=(30, 90, 180), ann=ANN)
# bloque ETFs (60/40, como catálogo 2, con el kill del piloto)
E_COST, E_KILL, E_BAND = 0.0005, 0.25, 0.05
E_BASE = dict(ann=252, dd_brake=False, cov_window=63, dd_peak_window=126, vol_target=None, regime_asset=None)
TRANSFER = 0.01
STRESS = 1.5
VARIANTS = {"control": {}, "h13-banda10": {"band": 0.10}, "h13-banda15": {"band": 0.15}, "h13-anual": {"annual": True}}


def crypto_block(start: str, cost: float) -> pd.Series:
    P, _ = load_crypto_panel(False)
    P = P[[a for a in BITSO_TRADABLE if a in P.columns]]
    p = PortfolioParams.from_dict(C_BASE)
    W = target_weights(P, listed_universe(P), p)
    bt = simulate_funded_portfolio(P, W, p, cost, C_BAND, kill_dd=C_KILL, initial_capital=500.0,
                                   min_order_value=C_MIN_ORDER, start=start)
    return bt["ret"].loc[start:END]


def etf_block(start: str, cost: float, cal_index: pd.DatetimeIndex) -> tuple[pd.Series, dict]:
    M, _ = load_market()
    p = PortfolioParams.from_dict(E_BASE)
    W = control_weights(M)
    bt = simulate_portfolio(M.C.loc[start:END], W.loc[start:END], p, cost, E_BAND, kill_dd=E_KILL)
    eq = (1 + bt["ret"]).cumprod()
    eq_cal = eq.reindex(cal_index).ffill().fillna(1.0)
    ret_cal = eq_cal / eq_cal.shift(1).fillna(1.0) - 1
    info = {"max_dd_trading_days": float(max_drawdown(bt["ret"])),
            "kill_hit": bool(max_drawdown(bt["ret"]) <= -E_KILL), "min_position": float(bt["position"].min())}
    return ret_cal, info


def summary(out: pd.DataFrame) -> dict:
    r = out["ret"]
    years = len(r) / ANN
    mult = float((1 + r).prod())
    sd = r.std(ddof=1)
    by_year = {str(y): float((1 + r.loc[str(y)]).prod() - 1) for y in YEARS if (r.index.year == y).any()}
    return {"cagr": mult ** (1 / years) - 1, "vol": float(sd * np.sqrt(ANN)), "sharpe": float(r.mean() / sd * np.sqrt(ANN)),
            "daily_sharpe": float(r.mean() / sd), "max_dd": float(max_drawdown(r)), "final_equity": float(out["equity"].iloc[-1]),
            "transfers": int((out["transfer"] != 0).sum()), "friction_usd": float(out["friction_usd"].sum()),
            "crypto_weight_mean": float(out["weight_a"].mean()), "crypto_weight_max": float(out["weight_a"].max()),
            "crypto_weight_min": float(out["weight_a"].min()), "crypto_weight_end": float(out["weight_a"].iloc[-1]),
            "years": by_year}


def run_set(rc: pd.Series, re: pd.Series, friction: float) -> dict[str, pd.DataFrame]:
    return {v: combine_sleeves(rc, re, friction=friction, **kw) for v, kw in VARIANTS.items()}


def main():
    rc = crypto_block(START, C_COST)
    rc_s = crypto_block(START, C_COST * STRESS)
    re, e_info = etf_block(START, E_COST, rc.index)
    re_s, _ = etf_block(START, E_COST * STRESS, rc.index)
    fr = C_COST + E_COST + TRANSFER
    fr_s = STRESS * fr
    base, stress, zero = run_set(rc, re, fr), run_set(rc_s, re_s, fr_s), run_set(rc, re, C_COST + E_COST)
    corr = float(pd.concat([rc, re], axis=1).loc[re != 0].corr().iloc[0, 1])
    res = {"experiment_id": "sprint04-h13-rebalanceo-bloques", "prereg_commit": PREREG_COMMIT, "window": [START, END],
           "friction": fr, "friction_stress": fr_s, "threshold_p_return_better": THRESHOLD,
           "blocks": {"crypto": {"cagr": float((1 + rc).prod() ** (ANN / len(rc)) - 1), "vol": float(rc.std() * np.sqrt(ANN)),
                                 "max_dd": float(max_drawdown(rc))},
                      "etf": {"cagr": float((1 + re).prod() ** (ANN / len(re)) - 1), "vol": float(re.std() * np.sqrt(ANN)),
                              "max_dd": float(max_drawdown(re)), **e_info},
                      "corr_trading_days": corr},
           "variants": {}}
    ctrl, ctrl_s = summary(base["control"]), summary(stress["control"])
    for v in VARIANTS:
        s, st, z = summary(base[v]), summary(stress[v]), summary(zero[v])
        entry = {"base": s, "stress": st, "zero_transfer_cost": {"cagr": z["cagr"], "max_dd": z["max_dd"]}}
        if v != "control":
            wins = sum(s["years"][y] > ctrl["years"][y] for y in s["years"])
            boot = bootstrap_compare(base[v]["ret"], base["control"]["ret"], n=2000, block=30, seed=11)
            crit = {"1_mayoria_de_anos": {"value": f"{wins}/{len(s['years'])}", "pass": wins >= 4},
                    "2_bootstrap": {"value": boot["p_return_better"], "pass": boot["p_return_better"] >= THRESHOLD},
                    "3_caida_maxima": {"value": s["max_dd"] - ctrl["max_dd"], "pass": s["max_dd"] >= ctrl["max_dd"] - 0.02},
                    "4_estres": {"value": st["cagr"] - ctrl_s["cagr"], "pass": st["cagr"] > ctrl_s["cagr"]}}
            entry.update({"bootstrap": boot, "criteria": crit, "approved": all(c["pass"] for c in crit.values())})
        res["variants"][v] = entry
    # informativo: inicio móvil
    rolling = {}
    for y in ROLLING_STARTS:
        st0 = f"{y}-01-01"
        rcy = crypto_block(st0, C_COST)
        rey, _ = etf_block(st0, E_COST, rcy.index)
        outs = run_set(rcy, rey, fr)
        rolling[str(y)] = {v: {k: summary(o)[k] for k in ("cagr", "max_dd", "sharpe", "transfers", "crypto_weight_end")}
                           for v, o in outs.items()}
    res["rolling_start"] = rolling
    approved = [v for v in VARIANTS if v != "control" and res["variants"][v]["approved"]]
    res["decision"] = max(approved, key=lambda v: res["variants"][v]["stress"]["cagr"]) if approved else None
    (ROOT / "reports" / "sprint04_h13_rebalanceo_bloques_resultado.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=float))
    b = res["blocks"]
    print(f"cripto {b['crypto']['cagr']:+.1%} vol {b['crypto']['vol']:.1%} DD {b['crypto']['max_dd']:.1%} | "
          f"ETF {b['etf']['cagr']:+.1%} vol {b['etf']['vol']:.1%} DD {b['etf']['max_dd']:.1%} kill {b['etf']['kill_hit']} | corr {corr:.2f}")
    for v, r in res["variants"].items():
        s = r["base"]
        print(f"{v:12s} CAGR {s['cagr']:+.1%} vol {s['vol']:.1%} Sharpe {s['sharpe']:.2f} DD {s['max_dd']:.1%} "
              f"tr {s['transfers']} fric ${s['friction_usd']:.0f} w̄ {s['crypto_weight_mean']:.0%} wmax {s['crypto_weight_max']:.0%} "
              f"final ${s['final_equity']:.0f} estrés {r['stress']['cagr']:+.1%} sin-fric {r['zero_transfer_cost']['cagr']:+.1%}")
        print("   años", {y: round(x * 100, 1) for y, x in s["years"].items()})
        if "criteria" in r:
            print("   ", {k: (c["value"], c["pass"]) for k, c in r["criteria"].items()}, "aprobada", r["approved"],
                  "| p_sharpe", r["bootstrap"]["p_sharpe_better"], "p_dd", r["bootstrap"]["p_drawdown_smaller"])
    for y, d in rolling.items():
        print("inicio", y, {v: (f"{x['cagr']:+.1%}", f"{x['max_dd']:.1%}") for v, x in d.items()})
    print("decisión", res["decision"])


if __name__ == "__main__":
    main()
