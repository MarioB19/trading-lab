"""Investigación completa: ¿alguna estrategia le gana de verdad a comprar y aguantar?

    python -m lab.research            # usa datos en caché
    python -m lab.research --refresh  # descarga datos al día

Genera reports/informe.md, reports/results.json y gráficas PNG.
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from .backtest import perf, sharpe, simulate, window
from .data import ROOT, load_history
from .risk import kelly_uncertainty
from .strategies import ANN, compute, label
from .validation import (bootstrap_compare, deflated_sharpe, monte_carlo, placebo_shift_test,
                         probabilistic_sharpe, run_grid, walk_forward)

REPORTS = ROOT / "reports"

# Declarada ANTES de ver los resultados: filtro de tendencia promediado.
# Es la única que se recomendaría para el bot, gane o no el concurso de backtests,
# porque elegir "la que mejor salió" es exactamente cómo uno se engaña.
CANDIDATE = ("trend_ensemble", {"lookbacks": (20, 50, 100, 200)})

SETTINGS = {
    "signal_start": "2012-01-01",   # calentamiento de indicadores y del modelo de ML
    "eval_start": "2015-01-01",     # desde aquí se mide (antes el mercado era diminuto)
    "oos_start_year": 2018,         # walk-forward: primer año fuera de muestra
    "cost_per_side": 0.002,         # 0.10% comisión + 0.10% deslizamiento
    "band": 0.10,                   # igual que el bot
    "mc_capital": 10_000,
}


def yearly_returns(ret: pd.Series) -> pd.Series:
    return (1 + ret).groupby(ret.index.year).prod() - 1


def demean_by_year(close: pd.Series) -> pd.Series:
    """Misma volatilidad y mismas tendencias intra-año, pero cada año termina donde empezó.

    Si la estrategia gana aquí, gana por timing. Si solo gana con el precio real,
    su ganancia venía de que BTC subió (y eso lo obtienes con solo comprar).
    """
    lr = np.log(close).diff().fillna(0.0)
    lr = lr - lr.groupby(lr.index.year).transform("mean")
    return float(close.iloc[0]) * np.exp(lr.cumsum())


def ml_diagnostics(close: pd.Series, start: str) -> dict:
    from sklearn.metrics import roc_auc_score

    out = {}
    for model in ("logistic", "gbm"):
        s = compute("ml_model", close, {"model": model})
        proba = s.attrs.get("proba")
        if proba is None:  # compute() puede perder attrs al recortar
            from .strategies import ml_model
            proba = ml_model(close, model=model).attrs["proba"]
        y = (close.shift(-5) / close - 1 > 0).astype(float)
        m = proba.notna() & close.shift(-5).notna()
        m &= proba.index >= pd.Timestamp(start)
        out[model] = {"auc": float(roc_auc_score(y[m], proba[m])),
                      "base_rate_up": float(y[m].mean()), "n": int(m.sum())}
    return out


def run(refresh: bool = False) -> dict:
    t0 = time.time()
    S = SETTINGS
    cost, band = S["cost_per_side"], S["band"]
    btc = load_history("btc", refresh=refresh).loc[S["signal_start"]:]
    eth = load_history("eth", refresh=refresh)
    oos_start = f"{S['oos_start_year']}-01-01"
    res: dict = {"settings": S, "data": {"btc_first": str(btc.index[0].date()),
                                          "btc_last": str(btc.index[-1].date()),
                                          "btc_last_close": float(btc.iloc[-1])}}

    # 1) todas las variantes sobre todo el periodo ------------------------------------
    runs = run_grid(btc, cost, band)
    bh = simulate(btc, compute("buy_hold", btc), cost, band)
    full = {k: perf(window(v["bt"], S["eval_start"], None, cost)) for k, v in runs.items()}
    full["BUY & HOLD"] = perf(window(bh, S["eval_start"], None, cost))
    res["full_sample"] = full
    trial_srs = [sharpe(window(v["bt"], S["eval_start"], None, cost)["ret"]) / np.sqrt(ANN)
                 for v in runs.values()]
    best_is = max(runs, key=lambda k: full[k]["sharpe"])
    best_ret = window(runs[best_is]["bt"], S["eval_start"], None, cost)["ret"]
    bh_ret_full = window(bh, S["eval_start"], None, cost)["ret"]
    # "¿crece más rápido que BTC?": diferencia de rendimientos logarítmicos (crecimiento compuesto)
    active = lambda r: np.log1p(r) - np.log1p(bh_ret_full)  # noqa: E731
    active_srs = []
    for v in runs.values():
        a = active(window(v["bt"], S["eval_start"], None, cost)["ret"])
        active_srs.append(a.mean() / a.std(ddof=1))
    res["in_sample_best"] = {
        "name": best_is, **full[best_is],
        "dsr_vs_zero": deflated_sharpe(best_ret, trial_srs),
        "dsr_active_vs_buyhold": deflated_sharpe(active(best_ret), active_srs),
    }

    # 2) walk-forward: elegir con el pasado, medir en el futuro ----------------------
    wf_all = walk_forward(btc, runs, S["oos_start_year"], S["eval_start"], cost, band)
    wf_fam = {fam: walk_forward(btc, runs, S["oos_start_year"], S["eval_start"], cost, band, [fam])
              for fam in sorted({v["family"] for v in runs.values()})}
    cand_key = label(*CANDIDATE)
    cand_bt = runs[cand_key]["bt"]
    oos = {
        "BUY & HOLD": window(bh, oos_start, None, cost),
        f"CANDIDATA {cand_key}": window(cand_bt, oos_start, None, cost),
        "WALK-FORWARD (elige la mejor cada año)": window(wf_all["bt"], oos_start, None, cost),
    }
    for fam, w in wf_fam.items():
        oos[f"wf:{fam}"] = window(w["bt"], oos_start, None, cost)
    res["oos"] = {k: perf(v) for k, v in oos.items()}
    res["wf_picks"] = wf_all["picks"]
    bh_oos = oos["BUY & HOLD"]["ret"]
    cand_oos = oos[f"CANDIDATA {cand_key}"]
    wf_oos = oos["WALK-FORWARD (elige la mejor cada año)"]

    # 3) ¿el timing es real o suerte? ------------------------------------------------
    res["placebo"] = {
        "candidate": {k: v for k, v in placebo_shift_test(
            cand_oos["asset_ret"], cand_oos["position"], cost).items() if k != "sims"},
        "walk_forward": {k: v for k, v in placebo_shift_test(
            wf_oos["asset_ret"], wf_oos["position"], cost).items() if k != "sims"},
    }
    placebo_sims = placebo_shift_test(cand_oos["asset_ret"], cand_oos["position"], cost)["sims"]
    res["bootstrap_vs_buyhold"] = {
        "candidate": bootstrap_compare(cand_oos["ret"], bh_oos),
        "walk_forward": bootstrap_compare(wf_oos["ret"], bh_oos),
    }
    res["psr_candidate_oos"] = probabilistic_sharpe(cand_oos["ret"])

    # 4) ¿de dónde sale la ganancia? BTC sin tendencia anual ---------------------------
    flat = demean_by_year(btc)
    flat_c = window(simulate(flat, compute(*CANDIDATE[:1], flat, CANDIDATE[1]), cost, band),
                    oos_start, None, cost)
    flat_bh = window(simulate(flat, compute("buy_hold", flat), cost, band), oos_start, None, cost)
    res["zero_drift"] = {"candidate": perf(flat_c), "buy_hold": perf(flat_bh)}

    # 5) sensibilidad a costos ---------------------------------------------------------
    sens = {}
    for c in (0.0, 0.001, 0.002, 0.005, 0.01):
        sens[f"{c:.1%}"] = {
            "candidate_cagr": perf(window(simulate(btc, runs[cand_key]["target"], c, band), oos_start, None, c))["cagr"],
            "walk_forward_cagr": perf(window(simulate(btc, wf_all["target"], c, band), oos_start, None, c))["cagr"],
            "buy_hold_cagr": perf(window(simulate(btc, compute("buy_hold", btc), c, band), oos_start, None, c))["cagr"],
        }
    res["cost_sensitivity"] = sens

    # 6) año por año -------------------------------------------------------------------
    yr = pd.DataFrame({
        "buy_hold": yearly_returns(window(bh, S["eval_start"], None, cost)["ret"]),
        "candidate": yearly_returns(window(cand_bt, S["eval_start"], None, cost)["ret"]),
        "walk_forward": yearly_returns(wf_oos["ret"]),
    })
    res["yearly"] = {int(k): {c: (None if pd.isna(v) else float(v)) for c, v in row.items()}
                     for k, row in yr.iterrows()}

    # 7) riesgo hacia adelante: Monte Carlo 12 meses ----------------------------------
    mc_c = monte_carlo(cand_oos["ret"], capital=S["mc_capital"])
    mc_b = monte_carlo(bh_oos, capital=S["mc_capital"])
    res["monte_carlo_12m"] = {"candidate": {k: v for k, v in mc_c.items() if k not in ("finals", "dds")},
                              "buy_hold": {k: v for k, v in mc_b.items() if k not in ("finals", "dds")}}
    res["kelly_candidate_oos"] = kelly_uncertainty(cand_oos["ret"])

    # 8) otro activo sin re-optimizar: ETH ----------------------------------------------
    eth_c = window(simulate(eth, compute(CANDIDATE[0], eth, CANDIDATE[1]), cost, band), oos_start, None, cost)
    eth_b = window(simulate(eth, compute("buy_hold", eth), cost, band), oos_start, None, cost)
    res["eth_check"] = {"candidate": perf(eth_c), "buy_hold": perf(eth_b)}

    # 9) periodo reciente (mercado más maduro) ------------------------------------------
    recent = "2022-01-01"
    res["recent"] = {"since": recent,
                     "candidate": perf(window(cand_bt, recent, None, cost)),
                     "buy_hold": perf(window(bh, recent, None, cost)),
                     "walk_forward": perf(window(wf_all["bt"], recent, None, cost))}

    # 10) ¿el machine learning predice algo? --------------------------------------------
    res["ml"] = ml_diagnostics(btc, oos_start)

    # señal de hoy
    tgt_today = float(runs[cand_key]["target"].iloc[-1])
    res["today"] = {"date": str(btc.index[-1].date()), "close": float(btc.iloc[-1]),
                    "candidate_target": tgt_today}
    res["runtime_s"] = round(time.time() - t0, 1)

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "results.json").write_text(json.dumps(res, indent=2, default=float))
    extras = {"oos": oos, "placebo_sims": placebo_sims, "mc_c": mc_c, "mc_b": mc_b, "yearly": yr,
              "flat": (flat_c, flat_bh), "eth": (eth_c, eth_b), "cand_key": cand_key}
    try:
        from .report import write_report
        write_report(res, extras, REPORTS)
    except ImportError:
        pass
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="descargar datos al día")
    args = ap.parse_args()
    res = run(refresh=args.refresh)
    o = res["oos"]
    print(f"\nFuera de muestra desde {SETTINGS['oos_start_year']} ({res['runtime_s']} s):")
    print(pd.DataFrame(o).T[["cagr", "sharpe", "max_dd", "exposure", "trades_per_year"]]
          .round(3).to_string())
    print(f"\nInforme: {REPORTS / 'informe.md'}")


if __name__ == "__main__":
    main()
