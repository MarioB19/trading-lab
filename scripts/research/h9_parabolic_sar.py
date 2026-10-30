"""H9: Parabolic SAR como capa de salida y como señal en el bloque cripto.
Ver reports/h9_parabolic_sar_preregistro.md (criterios fijados antes de correr).

    python scripts/research/h9_parabolic_sar.py

Escribe reports/h9_parabolic_sar_resultado.{json,md}. No cambia config.yaml ni el bot.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd

from lab.backtest import max_drawdown, perf, sharpe
from lab.data import load_crypto_panel
from lab.portfolio import PortfolioParams, listed_universe, parabolic_sar, simulate_portfolio, target_weights
from lab.research_multi import BITSO_TRADABLE, placebo
from lab.research_statistics import chronological_folds
from lab.validation import bootstrap_compare, deflated_sharpe

ROOT = Path(__file__).resolve().parents[2]
START, END = "2019-01-01", "2026-10-30"
PLACEBO_START = "2021-01-01"
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
COST, STRESS, KILL, ANN, BAND = 0.0042, 0.0042 * 1.5, 0.45, 365, 0.02
THRESHOLD_BOOT, THRESHOLD_PLACEBO, THRESHOLD_DSR = 1 - 0.10 / 3, 0.05, 0.95
EXTRA_TRIALS = 43
BASE = dict(top_k=5, vol_target=0.40, regime_asset="BTC", dd_brake=True, max_weight=0.40,
            mom_windows=(30, 90, 180), ann=ANN)
VARIANTS = {
    "control": dict(),
    "v1-sar-filtro": dict(psar_mode="filter", psar_af=0.02, psar_step=0.02, psar_max=0.20),
    "v2-sar-filtro-lento": dict(psar_mode="filter", psar_af=0.01, psar_step=0.01, psar_max=0.10),
    "v3-sar-tendencia": dict(psar_mode="trend", psar_af=0.02, psar_step=0.02, psar_max=0.20),
}
LABELS = {"control": "Control (tendencia + momentum)", "v1-sar-filtro": "V1: SAR como filtro de salida (0.02/0.02/0.20)",
          "v2-sar-filtro-lento": "V2: SAR filtro lento (0.01/0.01/0.10)", "v3-sar-tendencia": "V3: SAR en lugar de la tendencia"}


def load_okx() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    o = pd.read_csv(ROOT / "data" / "crypto_ohlc_okx.csv", parse_dates=["date"])
    o = o[o["asset"].isin(BITSO_TRADABLE)]
    bad = (o["high"] / o["close"] > 3) | (o["low"] / o["close"] < 1 / 3)
    o.loc[bad, ["high", "low"]] = np.nan  # dato sospechoso: ese día cierre = alto = bajo
    C = o.pivot(index="date", columns="asset", values="close")[BITSO_TRADABLE]
    H = o.pivot(index="date", columns="asset", values="high")[BITSO_TRADABLE]
    L = o.pivot(index="date", columns="asset", values="low")[BITSO_TRADABLE]
    idx = pd.date_range(C.index.min(), C.index.max(), freq="D")
    C, H, L = C.reindex(idx), H.reindex(idx), L.reindex(idx)
    filled = int(((H.isna() | L.isna()) & C.notna()).sum().sum())
    return C, H, L, {"suspicious_candles": int(bad.sum()), "filled_close_as_high_low": filled,
                     "first_date": str(C.index.min().date()), "last_date": str(C.index.max().date())}


def run(C, H, L, elig, spec, cost):
    p = PortfolioParams.from_dict({**BASE, **spec})
    W = target_weights(C, elig, p, highs=H, lows=L)
    Cs, Ws = C.loc[START:END], W.loc[START:END]
    return simulate_portfolio(Cs, Ws, p, cost, BAND, kill_dd=KILL), W, p


def summary(bt: pd.DataFrame, cost: float) -> dict:
    s = perf(bt, ANN)
    years = len(bt) / ANN
    turnover = float(bt["turnover"].sum() / years)
    by_year = {str(y): float((1 + bt.loc[str(y), "ret"]).prod() - 1) for y in YEARS if (bt.index.year == y).any()}
    return {**{k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in s.items()},
            "max_dd": float(max_drawdown(bt["ret"])), "turnover_per_year": turnover,
            "cost_per_year": turnover * cost, "years": by_year,
            "daily_sharpe": float(bt["ret"].mean() / bt["ret"].std(ddof=1)),
            "final_multiple": float((1 + bt["ret"]).prod())}


def flips_per_year(C, H, L, af, step, mx) -> dict:
    bull = parabolic_sar(C, H, L, af, step, mx)["bull"].loc[START:END]
    flips = bull.diff().abs().fillna(0.0)
    per_asset = flips.groupby(flips.index.year).sum()
    return {"mean_flips_per_asset_year": float(per_asset.replace(0, np.nan).stack().mean()),
            "by_year_mean": {str(y): float(r.replace(0, np.nan).mean()) for y, r in per_asset.iterrows()}}


def previous_trials() -> list[float]:
    srs = []
    with open(ROOT / "reports" / "intentos.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("sharpe_diario"):
                srs.append(float(row["sharpe_diario"]))
    return srs


def control_on_coinmetrics() -> dict:
    P, _ = load_crypto_panel(False)
    P = P[[a for a in BITSO_TRADABLE if a in P.columns]]
    p = PortfolioParams.from_dict(BASE)
    W = target_weights(P, listed_universe(P), p)
    bt = simulate_portfolio(P.loc[START:"2026-09-26"], W.loc[START:"2026-09-26"], p, COST, BAND, kill_dd=KILL)
    return summary(bt, COST)


def main():
    C, H, L, data_notes = load_okx()
    elig = listed_universe(C)
    base, stress, weights, params = {}, {}, {}, {}
    for vid, spec in VARIANTS.items():
        base[vid], weights[vid], params[vid] = run(C, H, L, elig, spec, COST)
        stress[vid], _, _ = run(C, H, L, elig, spec, STRESS)
    cfg = {"cost": COST, "band": BAND, "ann": ANN}
    c = base["control"]
    c_sum, c_stress = summary(c, COST), summary(stress["control"], STRESS)
    prev_srs = previous_trials()
    new_srs = {vid: summary(base[vid], COST)["daily_sharpe"] for vid in VARIANTS if vid != "control"}
    all_srs = prev_srs + list(new_srs.values())
    res = {"experiment_id": "h9-parabolic-sar", "window": [START, END], "cost": COST, "stress_cost": STRESS,
           "thresholds": {"bootstrap_p_sharpe_better": THRESHOLD_BOOT, "placebo_p": THRESHOLD_PLACEBO, "dsr": THRESHOLD_DSR,
                          "years_min_wins": 4},
           "data": data_notes, "n_trials_for_dsr": len(all_srs) + EXTRA_TRIALS, "variants": {},
           "control_on_coinmetrics_panel": control_on_coinmetrics()}
    for vid, spec in VARIANTS.items():
        s, st = summary(base[vid], COST), summary(stress[vid], STRESS)
        row = {"base": s, "stress": st}
        if vid != "control":
            wins = sum(s["years"][y] > c_sum["years"][y] for y in s["years"])
            folds = chronological_folds(base[vid]["ret"], c["ret"], first_year=2021)
            boot = bootstrap_compare(base[vid]["ret"], c["ret"], n=2000, block=30, seed=11)
            plc = placebo(C, weights[vid], params[vid], cfg, PLACEBO_START, n=200, seed=5)
            dsr = deflated_sharpe(base[vid]["ret"], all_srs, ANN, extra_trials=EXTRA_TRIALS)
            crit = {
                "1_anos_fuera_de_muestra": {"value": f"{wins}/{len(s['years'])}", "pass": wins >= 4},
                "2_placebo": {"value": plc["p_value"], "pass": plc["p_value"] < THRESHOLD_PLACEBO},
                "3_bootstrap_sharpe": {"value": boot["p_sharpe_better"], "pass": boot["p_sharpe_better"] >= THRESHOLD_BOOT},
                "4_sharpe_deflactado": {"value": dsr["dsr"], "pass": dsr["dsr"] >= THRESHOLD_DSR},
                "5_estres": {"value": st["cagr"] - c_stress["cagr"], "pass": st["cagr"] > c_stress["cagr"]},
            }
            row.update({"folds": {k: v for k, v in folds.items() if k != "folds"}, "bootstrap": boot,
                        "placebo": {k: v for k, v in plc.items() if k != "sims"}, "dsr": dsr,
                        "flips": flips_per_year(C, H, L, spec["psar_af"], spec["psar_step"], spec["psar_max"]),
                        "criteria": crit, "approved": all(v["pass"] for v in crit.values()),
                        "max_dd_vs_control_pts": s["max_dd"] - c_sum["max_dd"]})
        res["variants"][vid] = row
    approved = [v for v, r in res["variants"].items() if r.get("approved")]
    res["decision"] = max(approved, key=lambda v: res["variants"][v]["stress"]["sharpe"]) if approved else None
    out = ROOT / "reports" / "h9_parabolic_sar_resultado.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print(json.dumps({v: {"CAGR": r["base"]["cagr"], "Sharpe": r["base"]["sharpe"], "maxDD": r["base"]["max_dd"],
                          "rot": r["base"]["turnover_per_year"], "costo": r["base"]["cost_per_year"],
                          "CAGR_estres": r["stress"]["cagr"], "aprobada": r.get("approved"),
                          "criterios": {k: (c_["value"], c_["pass"]) for k, c_ in r.get("criteria", {}).items()}}
                      for v, r in res["variants"].items()}, indent=1, default=float, ensure_ascii=False))
    print("datos:", data_notes)
    print("control CoinMetrics:", {k: res["control_on_coinmetrics_panel"][k] for k in ("cagr", "sharpe", "max_dd", "turnover_per_year")})
    print("decisión:", res["decision"])


if __name__ == "__main__":
    main()
