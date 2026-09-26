"""Investigación del portafolio multi-activo: criptos y ETFs.

    python -m lab.research_multi            # datos en caché
    python -m lab.research_multi --refresh  # descarga datos al día (~1 min)

Genera reports/multi_results.json y reports/multi_informe.md.
"""
from __future__ import annotations

import argparse
import itertools
import json
import time

import numpy as np
import pandas as pd

from .backtest import perf, sharpe
from .data import MULTI_MARKET, ROOT, load_crypto_panel, load_etf_panel
from .portfolio import (PortfolioParams, crypto_universe, equal_weight_buy_hold, fixed_weights,
                        listed_universe, simulate_portfolio, target_weights)
from .strategies import trend_ensemble
from .validation import bootstrap_compare, deflated_sharpe, monte_carlo

REPORTS = ROOT / "reports"
# Criptos con par en USD en Bitso (septiembre 2026) que existen en los datos de investigación
BITSO_TRADABLE = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "LTC", "BCH", "XLM",
                  "TRX", "HBAR", "NEAR", "UNI", "ATOM"]

# Declaradas ANTES de ver resultados. Son las que usa el bot, ganen o no el concurso.
CANDIDATES = {
    "crypto": {"top_k": 5, "vol_target": 0.40, "regime_asset": "BTC", "dd_brake": True},
    "stocks": {"top_k": 5, "vol_target": 0.10, "regime_asset": None, "dd_brake": True},
    # Declarada el 25-sep-2026 en el documento "Plan: bloque multi-mercado", antes de correr la prueba.
    "multi": {"top_k": 8, "vol_target": 0.10, "regime_asset": None, "dd_brake": True, "cash_asset": "BIL",
              "rebalance": "daily"},
    # Experimento 2, declarado el 25-sep-2026 tras fallar el 1: misma regla, rebalanceo mensual.
    "multi_monthly": {"top_k": 8, "vol_target": 0.10, "regime_asset": None, "dd_brake": True,
                      "cash_asset": "BIL", "rebalance": "monthly"},
}

SLEEVES = {
    "crypto": {
        "label": "Criptomonedas", "ann": 365, "eval_start": "2019-01-01", "oos_year": 2021,
        # 0.45% por lado = comisión real de Bitso contra USD (0.36% taker, nivel más bajo)
        # + medio diferencial medido en su libro (~0.08% para órdenes de ~$60, sep-2026)
        "cost": 0.0045, "band": 0.02, "base": {"mom_windows": (30, 90, 180), "max_weight": 0.40},
        "grid": {"top_k": [1, 3, 5], "vol_target": [None, 0.40, 0.60],
                 "regime_asset": ["BTC", None], "dd_brake": [True, False]},
        "costs_test": [0.003, 0.0045, 0.006, 0.01], "benchmark": "BTC", "kill_dd": 0.45,
        "passive": None,
    },
    "stocks": {
        "label": "Acciones y ETFs", "ann": 252, "eval_start": "2005-01-01", "oos_year": 2010,
        "cost": 0.0005, "band": 0.02,
        "base": {"mom_windows": (21, 63, 126), "max_weight": 0.35, "ann": 252, "cov_window": 63,
                 "dd_peak_window": 126},
        "grid": {"top_k": [1, 3, 5], "vol_target": [None, 0.10, 0.15], "regime_asset": [None],
                 "dd_brake": [True, False]},
        "costs_test": [0.0002, 0.0005, 0.002, 0.005], "benchmark": "SPY", "kill_dd": 0.25,
        "passive": "60/40 (SPY/IEF)",
    },
    "multi": {
        "label": "Multi-mercado", "ann": 252, "eval_start": "2009-01-01", "oos_year": 2012,
        "cost": 0.001, "band": 0.02,
        "base": {"mom_windows": (21, 63, 126), "max_weight": 0.25, "ann": 252, "cov_window": 63,
                 "dd_peak_window": 126},
        "grid": {"top_k": [4, 8, 12], "vol_target": [None, 0.10, 0.15], "regime_asset": [None],
                 "dd_brake": [True, False], "cash_asset": ["BIL", None], "rebalance": ["daily", "monthly"]},
        "costs_test": [0.0005, 0.001, 0.003, 0.005], "benchmark": "SPY", "kill_dd": 0.25,
        "passive": None,
    },
}


def key_of(d: dict) -> str:
    vt = "sin" if d["vol_target"] is None else f"{d['vol_target']:.0%}"
    rg = "con filtro BTC" if d.get("regime_asset") else "sin filtro"
    br = "freno" if d["dd_brake"] else "sin freno"
    cash = ""
    if "cash_asset" in d:
        cash = " · efectivo en " + d["cash_asset"] if d["cash_asset"] else " · efectivo sin rendir"
    reb = {"monthly": " · mensual", "daily": ""}.get(d.get("rebalance", "daily"), "")
    return f"top{d['top_k']} · vol {vt} · {rg} · {br}{cash}{reb}"


def params_for(sleeve: str, d: dict) -> PortfolioParams:
    cfg = SLEEVES[sleeve]
    return PortfolioParams.from_dict({**cfg["base"], "ann": cfg["ann"], **d})


def load_sleeve(sleeve: str, refresh: bool):
    if sleeve == "crypto":
        P, M = load_crypto_panel(refresh)
        return P, crypto_universe(M, P, top_n=15)
    if sleeve == "multi":
        P = load_etf_panel(MULTI_MARKET, refresh=refresh, name="multi_prices")
        elig = listed_universe(P)
        elig["BIL"] = False  # el efectivo no compite ni entra a la referencia de pesos iguales
        return P, elig
    P = load_etf_panel(refresh=refresh)
    return P, listed_universe(P)


def win(df: pd.DataFrame, start: str) -> pd.DataFrame:
    return df.loc[start:]


def walk_forward(P, runs, first_year, train_start, ann, cfg):
    """Cada enero elige la variante con mejor Sharpe pasado; la aplica ese año."""
    stitched = pd.DataFrame(0.0, index=P.index, columns=P.columns)
    picks = []
    for year in range(first_year, P.index[-1].year + 1):
        scores = {k: sharpe(v["bt"]["ret"].loc[train_start:f"{year - 1}-12-31"], ann) for k, v in runs.items()}
        best = max(scores, key=scores.get)
        sel = slice(f"{year - 1}-12-31" if year == first_year else f"{year}-01-01", f"{year}-12-31")
        stitched.loc[sel] = runs[best]["W"].loc[sel]
        picks.append({"year": year, "pick": best, "train_sharpe": round(scores[best], 3)})
    # el freno/parámetros del año se toman de la variante elegida más reciente
    p = runs[picks[-1]["pick"]]["params"]
    return simulate_portfolio(P, stitched, p, cfg["cost"], cfg["band"]), picks


def placebo(P, W, p, cfg, start, n=200, seed=5):
    rng = np.random.default_rng(seed)
    actual = sharpe(win(simulate_portfolio(P, W, p, cfg["cost"], cfg["band"]), start)["ret"], cfg["ann"])
    L = len(W)
    sims = []
    for k in rng.integers(90, L - 90, size=n):
        Ws = pd.DataFrame(np.roll(W.values, k, axis=0), index=W.index, columns=W.columns)
        Ws = Ws.where(P.notna(), 0.0)
        sims.append(sharpe(win(simulate_portfolio(P, Ws, p, cfg["cost"], cfg["band"]), start)["ret"], cfg["ann"]))
    sims = np.array(sims)
    return {"actual_sharpe": float(actual), "placebo_median": float(np.median(sims)),
            "p_value": float((sims >= actual).mean()), "n": int(n)}


def yearly(ret: pd.Series) -> dict:
    return {int(k): float(v) for k, v in ((1 + ret).groupby(ret.index.year).prod() - 1).items()}


def run_sleeve(sleeve: str, refresh: bool = False, candidate: str | None = None) -> tuple[dict, dict]:
    cfg = SLEEVES[sleeve]
    cand_cfg = CANDIDATES[candidate or sleeve]
    ann, start, oos = cfg["ann"], cfg["eval_start"], f"{cfg['oos_year']}-01-01"
    P, elig = load_sleeve(sleeve, refresh)
    res: dict = {"label": cfg["label"], "assets": list(P.columns), "first": str(P.index[0].date()),
                 "last": str(P.index[-1].date()), "eval_start": start, "oos_start": oos,
                 "cost_per_side": cfg["cost"], "candidate": key_of(cand_cfg)}

    # 1) todas las variantes --------------------------------------------------------------
    g = cfg["grid"]
    combos = [dict(zip(g, vals)) for vals in itertools.product(*g.values())]
    runs = {}
    for d in combos:
        p = params_for(sleeve, d)
        W = target_weights(P, elig, p)
        runs[key_of(d)] = {"params": p, "W": W, "bt": simulate_portfolio(P, W, p, cfg["cost"], cfg["band"])}
    cand = key_of(cand_cfg)
    pc = runs[cand]["params"]

    # 2) referencias -----------------------------------------------------------------------
    nobrake = PortfolioParams.from_dict({**cfg["base"], "ann": ann, "dd_brake": False})
    bench = {}
    bench[f"Comprar y aguantar {cfg['benchmark']}"] = simulate_portfolio(
        P, fixed_weights(P, {cfg["benchmark"]: 1.0}), nobrake, cfg["cost"], 0.05)
    bench["Pesos iguales, rebalanceo mensual"] = simulate_portfolio(
        P, equal_weight_buy_hold(P, elig), nobrake, cfg["cost"], 0.05)
    if sleeve == "crypto":
        te = pd.DataFrame(0.0, index=P.index, columns=P.columns)
        te["BTC"] = trend_ensemble(P["BTC"].dropna()).reindex(P.index).fillna(0.0)
        bench["Regla de tendencia solo BTC"] = simulate_portfolio(P, te, nobrake, cfg["cost"], 0.10)
    else:
        bench["60/40 (SPY/IEF)"] = simulate_portfolio(P, fixed_weights(P, {"SPY": 0.6, "IEF": 0.4}),
                                                      nobrake, cfg["cost"], 0.05)
    bkey = f"Comprar y aguantar {cfg['benchmark']}"

    # 3) walk-forward ----------------------------------------------------------------------
    wf_bt, picks = walk_forward(P, runs, cfg["oos_year"], start, ann, cfg)

    table = {"CANDIDATA: " + cand: runs[cand]["bt"], "Optimizador (elige la mejor cada año)": wf_bt, **bench}
    res["oos"] = {k: perf(win(v, oos), ann) for k, v in table.items()}
    res["full"] = {k: perf(win(v["bt"], start), ann) for k, v in runs.items()}
    res["full_bench"] = {k: perf(win(v, start), ann) for k, v in bench.items()}
    res["wf_picks"] = picks

    # 4) ¿suerte? --------------------------------------------------------------------------
    srs = [sharpe(win(v["bt"], start)["ret"], ann) / np.sqrt(ann) for v in runs.values()]
    best = max(runs, key=lambda k: res["full"][k]["sharpe"])
    best_ret = win(runs[best]["bt"], start)["ret"]
    b_ret = win(bench[bkey], start)["ret"]
    act = lambda r: np.log1p(r) - np.log1p(b_ret)  # noqa: E731
    act_srs = []
    for v in runs.values():
        a = act(win(v["bt"], start)["ret"])
        act_srs.append(a.mean() / a.std(ddof=1))
    res["best_in_sample"] = {"name": best, **res["full"][best],
                             "dsr_vs_zero": deflated_sharpe(best_ret, srs, ann),
                             "dsr_vs_benchmark": deflated_sharpe(act(best_ret), act_srs, ann)}
    res["placebo"] = placebo(P, runs[cand]["W"], pc, cfg, oos)
    c_oos = win(runs[cand]["bt"], oos)["ret"]
    res["bootstrap"] = {k: bootstrap_compare(c_oos, win(v, oos)["ret"]) for k, v in bench.items()}

    # 5) costos, kill switch, año por año, Monte Carlo ------------------------------------
    res["costs"], res["costs_sharpe"] = {}, {}
    for c in cfg["costs_test"]:
        pf_c = perf(win(simulate_portfolio(P, runs[cand]["W"], pc, c, cfg["band"]), oos), ann)
        res["costs"][f"{c:.2%}"], res["costs_sharpe"][f"{c:.2%}"] = pf_c["cagr"], pf_c["sharpe"]
    res["kill_switch"] = {}
    for kd in (0.35, cfg["kill_dd"]):
        killed = simulate_portfolio(P.loc[start:], runs[cand]["W"].loc[start:], pc, cfg["cost"], cfg["band"], kill_dd=kd)
        k_on = killed.index[killed["brake"] == 0]
        res["kill_switch"][f"{kd:.0%}"] = {"triggered": bool(len(k_on)),
                                          "date": str(k_on[0].date()) if len(k_on) else None}
    res["yearly"] = {"candidate": yearly(win(runs[cand]["bt"], start)["ret"]),
                     "benchmark": yearly(win(bench[bkey], start)["ret"]),
                     "optimizer": yearly(win(wf_bt, oos)["ret"])}
    mc_c = monte_carlo(c_oos, horizon=ann, capital=1000)
    mc_b = monte_carlo(win(bench[bkey], oos)["ret"], horizon=ann, capital=1000)
    strip = lambda m: {k: v for k, v in m.items() if k not in ("finals", "dds")}  # noqa: E731
    res["monte_carlo_12m"] = {"candidate": strip(mc_c), "benchmark": strip(mc_b)}

    # 6) señal de hoy ------------------------------------------------------------------------
    W, sig = target_weights(P, elig, pc, return_signals=True)
    last = P.index[-1]
    today = []
    for a in P.columns:
        if not elig.loc[last, a]:
            continue
        today.append({"asset": a, "weight": round(float(W.loc[last, a]), 4),
                      "trend": round(float(sig["trend"].loc[last, a]), 2),
                      "momentum": round(float(sig["mom"].loc[last, a]), 4),
                      "vol": round(float(sig["vol"].loc[last, a]), 3)})
    res["today"] = {"date": str(last.date()), "cash": round(1 - float(W.loc[last].sum()), 4),
                    "assets": sorted(today, key=lambda x: -x["weight"])}

    if sleeve == "crypto":
        # Lo que el bot puede operar HOY en Bitso (sesgo de supervivencia: estas sobrevivieron)
        bitso = [a for a in BITSO_TRADABLE if a in P.columns]
        Pb = P[bitso]
        Wb = target_weights(Pb, crypto_universe(pd.DataFrame(1.0, index=Pb.index, columns=bitso).where(Pb.notna()),
                                                Pb, top_n=len(bitso)), pc)
        res["bitso_universe"] = {"assets": bitso, **perf(win(simulate_portfolio(Pb, Wb, pc, cfg["cost"], cfg["band"]), oos), ann)}

    series = {"candidate": win(runs[cand]["bt"], oos)["ret"], "benchmark": win(bench[bkey], oos)["ret"],
              "optimizer": win(wf_bt, oos)["ret"]}
    for k, v in bench.items():
        series["bench:" + k] = win(v, oos)["ret"]
    if cfg["passive"]:
        series["passive"] = win(bench[cfg["passive"]], oos)["ret"]
        res["recommended"] = cfg["passive"]
        mc_p = monte_carlo(series["passive"], horizon=ann, capital=1000)
        res["monte_carlo_12m"]["passive"] = strip(mc_p)
    else:
        res["recommended"] = "CANDIDATA: " + cand
    return res, series


def combined(series: dict, crypto_share: float = 0.3, stocks_key: str = "passive") -> dict:
    """Ejemplo: 30% cripto y 70% ETFs, cada bloque en su cuenta, sin rebalancear entre ellos."""
    c, s = series["crypto"]["candidate"], series["stocks"][stocks_key]
    c.index, s.index = c.index.astype("datetime64[ns]"), s.index.astype("datetime64[ns]")
    start = max(c.index[0], s.index[0])
    idx = pd.date_range(start, min(c.index[-1], s.index[-1]), freq="D")
    fill = lambda x: (1 + x).cumprod().reindex(x.index.union(idx)).ffill().reindex(idx)  # noqa: E731
    ec, es = fill(c), fill(s)
    ec, es = ec / ec.iloc[0], es / es.iloc[0]
    total = crypto_share * ec + (1 - crypto_share) * es
    r = total.pct_change().fillna(0.0)
    bt = pd.DataFrame({"ret": r, "position": 1.0, "turnover": 0.0})
    out = perf(bt, 365)
    out["crypto_share"] = crypto_share
    out["p_loss_12m"] = monte_carlo(r, horizon=365, capital=1000)["p_loss"]
    return out


def markdown(res: dict) -> str:
    def pct(x, d=0):
        return "–" if x is None else f"{x:.{d}%}".replace("-", "−")

    L = ["# Portafolio multi-activo: resultados de la investigación", "",
         "Estrategia: tendencia + momentum ajustado por riesgo + paridad de riesgo + volatilidad objetivo "
         "+ filtro de régimen (cripto) + freno por caída. Candidatas declaradas antes de ver resultados.", ""]
    for sl in ("crypto", "stocks"):
        r = res[sl]
        L += [f"## {r['label']}", "",
              f"Datos {r['first']} a {r['last']}; fuera de muestra desde {r['oos_start'][:4]}; "
              f"costo {r['cost_per_side']:.2%} por lado; candidata: {r['candidate']}.", "",
              "| Estrategia | Rend. anual | Sharpe | Caída máx. | Exposición media |", "|---|---:|---:|---:|---:|"]
        for k, p in r["oos"].items():
            L.append(f"| {k} | {pct(p['cagr'],1)} | {p['sharpe']:.2f} | {pct(p['max_dd'])} | {pct(p['exposure'])} |")
        b = r["best_in_sample"]
        mc = r["monte_carlo_12m"]
        L += ["",
              f"- Placebo (pesos desfasados al azar): p = {r['placebo']['p_value']:.3f}.",
              f"- Mejor variante de {b['dsr_vs_zero']['n_trials']} en todo el periodo: {b['name']} "
              f"(DSR vs 0: {b['dsr_vs_zero']['dsr']:.3f}; DSR vs referencia: {b['dsr_vs_benchmark']['dsr']:.3f}).",
              "- Bootstrap de la candidata: " + "; ".join(
                  f"vs {k}: P(más rendimiento) {pct(v['p_return_better'])}, P(menor caída) {pct(v['p_drawdown_smaller'])}"
                  for k, v in r["bootstrap"].items()),
              "- Costos: " + ", ".join(f"{k} → {pct(v,1)}" for k, v in r["costs"].items()),
              "- Kill switch: " + "; ".join(f"a {k}: " + (f"se habría activado el {v['date']}" if v["triggered"] else "no se habría activado")
                                            for k, v in r["kill_switch"].items()) + ".",
              f"- 12 meses con $1,000: peor 5% ${mc['candidate']['final_p5']:,.0f}, mediana ${mc['candidate']['final_median']:,.0f}, "
              f"P(pérdida) {pct(mc['candidate']['p_loss'])}, P(caída >30%) {pct(mc['candidate']['p_dd_30'])} "
              f"(referencia: P(pérdida) {pct(mc['benchmark']['p_loss'])}, P(caída >30%) {pct(mc['benchmark']['p_dd_30'])}).",
              ]
        if "bitso_universe" in r:
            bu = r["bitso_universe"]
            L.append(f"- Solo con las {len(bu['assets'])} criptos operables hoy en Bitso: {pct(bu['cagr'],1)} anual, "
                     f"caída máx. {pct(bu['max_dd'])} (estas sobrevivieron, así que es optimista).")
        L += [f"- **Qué usa el bot en este bloque:** {r['recommended']}.",
              "", "| Año | Candidata | Referencia |", "|---|---:|---:|"]
        for y, v in r["yearly"]["candidate"].items():
            L.append(f"| {y} | {pct(v)} | {pct(r['yearly']['benchmark'].get(y))} |")
        L.append("")
    c = res["combined"]
    L += ["## Combinado de ejemplo", "",
          f"{c['crypto_share']:.0%} cripto (candidata) / {1 - c['crypto_share']:.0%} ETFs (60/40 pasivo) sin rebalancear entre cuentas: "
          f"{pct(c['cagr'],1)} anual, caída máx. {pct(c['max_dd'])}, P(pérdida en 12 meses) {pct(c['p_loss_12m'])}.", "",
          "## Limitaciones", "",
          "- El universo cripto incluye monedas que se desplomaron (LUNA, FTT, EOS...) y se elige por capitalización de cada día, "
          "pero la lista inicial la hice en 2026: queda algo de sesgo de supervivencia.",
          "- IOTA y MATIC antes de 2023 usan la capitalización como aproximación del precio.",
          "- Cripto: precios de CoinMetrics y Yahoo en USD. ETFs: cierres ajustados de Yahoo. Sin impuestos."]
    return "\n".join(L) + "\n"


def run(refresh: bool = False) -> dict:
    t0 = time.time()
    res, series = {}, {}
    for sl in ("crypto", "stocks"):
        res[sl], series[sl] = run_sleeve(sl, refresh)
    res["combined"] = combined(series)
    res["generated"] = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")
    res["runtime_s"] = round(time.time() - t0, 1)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "multi_results.json").write_text(json.dumps(res, indent=1, default=float))
    (REPORTS / "multi_informe.md").write_text(markdown(res))
    # curvas semanales para el tablero
    curves = {}
    for sl, s in series.items():
        for k, r in s.items():
            curves[f"{sl}_{k}"] = (1 + r).cumprod().resample("W").last()
    pd.DataFrame(curves).round(4).to_csv(REPORTS / "multi_curves.csv")
    return res


def combine(c: pd.Series, s: pd.Series, share: float) -> dict:
    """Dos cuentas separadas, sin rebalancear entre ellas: `share` en c y el resto en s."""
    c, s = c.copy(), s.copy()
    c.index, s.index = c.index.astype("datetime64[ns]"), s.index.astype("datetime64[ns]")
    idx = pd.date_range(max(c.index[0], s.index[0]), min(c.index[-1], s.index[-1]), freq="D")
    fill = lambda x: (1 + x).cumprod().reindex(x.index.union(idx)).ffill().reindex(idx)  # noqa: E731
    ec, es = fill(c), fill(s)
    r = (share * ec / ec.iloc[0] + (1 - share) * es / es.iloc[0]).pct_change().fillna(0.0)
    out = perf(pd.DataFrame({"ret": r, "position": 1.0, "turnover": 0.0}), 365)
    out["p_loss_12m"] = monte_carlo(r, horizon=365, capital=1000)["p_loss"]
    return out


def run_multi_market(refresh: bool = False, candidate: str = "multi") -> dict:
    """Prueba del bloque multi-mercado contra los criterios declarados antes de correrla."""
    t0 = time.time()
    res, ser = run_sleeve("multi", refresh, candidate)
    _, cser = run_sleeve("crypto", False)
    cand = "CANDIDATA: " + res["candidate"]
    ref = "60/40 (SPY/IEF)"
    o_c, o_r = res["oos"][cand], res["oos"][ref]
    boot = res["bootstrap"][ref]
    comb_new = combine(cser["candidate"], ser["candidate"], 0.3)
    comb_old = combine(cser["candidate"], ser["bench:" + ref], 0.3)
    crit = [
        {"id": 1, "name": "El timing no es suerte (placebo p < 0.05)", "value": res["placebo"]["p_value"],
         "pass": res["placebo"]["p_value"] < 0.05},
        {"id": 2, "name": "Mejor Sharpe que el 60/40 con probabilidad ≥ 80% (bootstrap)",
         "value": boot["p_sharpe_better"], "pass": boot["p_sharpe_better"] >= 0.80},
        {"id": 3, "name": "Caída máxima no peor que la del 60/40", "value": [o_c["max_dd"], o_r["max_dd"]],
         "pass": o_c["max_dd"] >= o_r["max_dd"]},
        {"id": 4, "name": "Con costos de 0.3% sigue con mejor Sharpe que el 60/40",
         "value": [res["costs_sharpe"]["0.30%"], o_r["sharpe"]], "pass": res["costs_sharpe"]["0.30%"] > o_r["sharpe"]},
        {"id": 5, "name": "Junto con cripto (30/70) mejora el Sharpe sin más caída que con el 60/40",
         "value": [comb_new["sharpe"], comb_old["sharpe"], comb_new["max_dd"], comb_old["max_dd"]],
         "pass": comb_new["sharpe"] > comb_old["sharpe"] and comb_new["max_dd"] >= comb_old["max_dd"] - 0.01},
    ]
    res["criteria"] = crit
    res["combined_new"], res["combined_old"] = comb_new, comb_old
    res["verdict"] = "aprobado" if all(c["pass"] for c in crit) else "no aprobado"
    res["generated"] = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")
    res["runtime_s"] = round(time.time() - t0, 1)
    REPORTS.mkdir(exist_ok=True)
    suffix = "" if candidate == "multi" else "_" + candidate.split("_", 1)[1]
    (REPORTS / f"multi_market{suffix}_results.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--multi-market", action="store_true", help="prueba del bloque multi-mercado")
    ap.add_argument("--candidate", default="multi", help="multi (diario) o multi_monthly (mensual)")
    args = ap.parse_args()
    if args.multi_market:
        r = run_multi_market(args.refresh, args.candidate)
        print(pd.DataFrame(r["oos"]).T[["cagr", "sharpe", "max_dd", "exposure"]].round(3).to_string())
        for c in r["criteria"]:
            print(("PASA  " if c["pass"] else "FALLA ") + c["name"], c["value"])
        print("Veredicto:", r["verdict"])
        return
    res = run(args.refresh)
    for sl in ("crypto", "stocks"):
        print(f"\n{res[sl]['label']} (fuera de muestra desde {res[sl]['oos_start'][:4]}):")
        print(pd.DataFrame(res[sl]["oos"]).T[["cagr", "sharpe", "max_dd", "exposure", "trades_per_year"]]
              .round(3).to_string())
    print(f"\n{res['runtime_s']} s · reports/multi_informe.md")


if __name__ == "__main__":
    main()
