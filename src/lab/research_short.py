"""Prueba pre-registrada: estrategias de corto plazo en cripto (velas por hora).

    python -m lab.research_short            # con las velas guardadas en data/
    python -m lab.research_short --refresh  # descarga antes las velas nuevas

Variantes y criterios en reports/corto_plazo_preregistro.md, escritos antes de correr esto.
Genera reports/corto_plazo_results.json y reports/corto_plazo_informe.md.
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from .backtest import perf, sharpe
from .data import load_hourly_panel
from .portfolio import PortfolioParams, breakout_weights, reversal_weights, simulate_portfolio
from .research_multi import BITSO_TRADABLE, CANDIDATES, SLEEVES, params_for
from .research_rt import OOS, REPORTS, SIM_START, hourly_targets, simulate_variant, to_daily
from .validation import bootstrap_compare

VARIANTS = {
    "C1": {"label": "Reversión: las 3 que más cayeron en 24 h, cada 4 h", "kind": "reversal",
           "args": {"every": 4, "k": 3, "lookback": 24, "threshold": None}, "every": 4},
    "C2": {"label": "Reversión con umbral: caída de más de 5% en 24 h", "kind": "reversal",
           "args": {"every": 4, "k": 3, "lookback": 24, "threshold": 0.05}, "every": 4},
    "C3": {"label": "Ruptura: máximo de 24 h / mínimo de 12 h", "kind": "breakout",
           "args": {"entry": 24, "exit": 12}, "every": 1},
    "C4": {"label": "Ruptura: máximo de 72 h / mínimo de 36 h", "kind": "breakout",
           "args": {"entry": 72, "exit": 36}, "every": 1},
}
HIGH_COST, LOW_COST = 0.006, 0.003
# Solo "se opera cuando cambia la cartera": la banda evita rebalancear por la simple deriva de precios;
# entrar o salir de una cripto (1/3 o 1/5 del bloque) siempre la supera.
BAND = 0.02
PLACEBO_N = 100
SIM = PortfolioParams(vol_target=None, dd_brake=False, regime_asset=None)


def weights(H: pd.DataFrame, v: dict) -> pd.DataFrame:
    return reversal_weights(H, **v["args"]) if v["kind"] == "reversal" else breakout_weights(H, **v["args"])


def check_mask(index: pd.DatetimeIndex, every: int) -> np.ndarray:
    return (np.asarray(index.hour) % every) == 0


def run_variant(H, W, every, cost, kill=None) -> pd.DataFrame:
    return to_daily(simulate_portfolio(H, W, SIM, cost, BAND, kill_dd=kill, check=check_mask(H.index, every))).loc[OOS:]


def placebo(H, W, every, cost, n=PLACEBO_N, seed=5) -> dict:
    rng = np.random.default_rng(seed)
    actual = sharpe(run_variant(H, W, every, cost)["ret"], 365)
    days = len(W) // 24
    sims = []
    for k in rng.integers(90, days - 90, size=n):
        Ws = pd.DataFrame(np.roll(W.values, int(k) * 24, axis=0), index=W.index, columns=W.columns)
        Ws = Ws.where(H.notna(), 0.0)
        sims.append(sharpe(run_variant(H, Ws, every, cost)["ret"], 365))
    sims = np.array(sims)
    return {"actual_sharpe": float(actual), "placebo_median": float(np.median(sims)),
            "p_value": float((sims >= actual).mean()), "n": int(n)}


def summary(d: pd.DataFrame, cost: float) -> dict:
    pf = perf(d, 365)
    years = len(d) / 365
    return {**{m: pf[m] for m in ("cagr", "vol", "sharpe", "max_dd", "exposure", "worst_day")},
            "rebalances_per_year": float(d["rebalances"].sum() / years),
            "cost_drag_per_year": float(d["turnover"].sum() / years * cost)}


def run(refresh: bool = False) -> dict:
    t0 = time.time()
    cfg = SLEEVES["crypto"]
    cost = cfg["cost"]
    H = load_hourly_panel(BITSO_TRADABLE, refresh=refresh)
    H = H.reindex(pd.date_range(H.index[0], H.index[-1], freq="h"))
    H = H.loc[:H.index[H.index.hour == 0][-1]]  # termina en un cierre diario completo
    Hs = H.loc[SIM_START:]
    # referencia: el bot diario en los mismos datos, sin kill switch
    p = params_for("crypto", CANDIDATES["crypto"])
    T = hourly_targets(H, p, SIM_START)
    r0 = {c: to_daily(simulate_variant(Hs, T, p, "1d", c, cfg["band"], None)).loc[OOS:] for c in (cost, HIGH_COST, LOW_COST)}
    r0_kill = to_daily(simulate_variant(Hs, T, p, "1d", cost, cfg["band"], cfg["kill_dd"])).loc[OOS:]
    res = {"generated": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"),
           "data": {"first": str(H.index[0]), "last": str(H.index[-1]), "oos_start": OOS, "cost": cost,
                    "band": BAND, "assets": list(H.columns)},
           "reference": {"label": "R0 · bot diario actual", **summary(r0[cost], cost),
                         "sharpe_at_0.60%": sharpe(r0[HIGH_COST]["ret"], 365),
                         "cagr_at_0.30%": perf(r0[LOW_COST], 365)["cagr"],
                         "with_kill_switch": perf(r0_kill, 365)["cagr"]},
           "variants": {}}
    ref = res["reference"]
    for k, v in VARIANTS.items():
        W = weights(Hs, v)
        d = run_variant(Hs, W, v["every"], cost)
        x = {"label": v["label"], **summary(d, cost),
             "sharpe_at_0.60%": sharpe(run_variant(Hs, W, v["every"], HIGH_COST)["ret"], 365),
             "cagr_at_0.30%": perf(run_variant(Hs, W, v["every"], LOW_COST), 365)["cagr"],
             "sharpe_at_0.30%": sharpe(run_variant(Hs, W, v["every"], LOW_COST)["ret"], 365),
             "with_kill_switch": perf(run_variant(Hs, W, v["every"], cost, cfg["kill_dd"]), 365)["cagr"],
             "cagr_no_costs": perf(run_variant(Hs, W, v["every"], 0.0), 365)["cagr"],
             # ¿a qué costo por operación dejaría de perder? (Bitso cobra mínimo 0.30% como maker)
             "cagr_by_cost": {f"{c:.2%}": perf(run_variant(Hs, W, v["every"], c), 365)["cagr"]
                              for c in (0.0005, 0.001, 0.0015, 0.002)}}
        boot = bootstrap_compare(d["ret"], r0[cost]["ret"])
        plc = placebo(Hs, W, v["every"], cost)
        crit = [
            {"id": 1, "name": "Sharpe fuera de muestra mayor que R0", "value": [x["sharpe"], ref["sharpe"]],
             "pass": x["sharpe"] > ref["sharpe"]},
            {"id": 2, "name": "Bootstrap: P(Sharpe mejor que R0) ≥ 80%", "value": boot["p_sharpe_better"],
             "pass": boot["p_sharpe_better"] >= 0.80},
            {"id": 3, "name": "Placebo p < 0.05", "value": plc["p_value"], "pass": plc["p_value"] < 0.05},
            {"id": 4, "name": "Caída máxima no peor que R0 por más de 1 punto", "value": [x["max_dd"], ref["max_dd"]],
             "pass": x["max_dd"] >= ref["max_dd"] - 0.01},
            {"id": 5, "name": "Con 0.60% por operación, Sharpe mayor que R0 con 0.60%",
             "value": [x["sharpe_at_0.60%"], ref["sharpe_at_0.60%"]],
             "pass": x["sharpe_at_0.60%"] > ref["sharpe_at_0.60%"]},
        ]
        x.update(bootstrap=boot, placebo=plc, criteria=crit,
                 verdict="aprobada" if all(c["pass"] for c in crit) else "no aprobada")
        res["variants"][k] = x
        print(f"{k} {x['label'][:45]:45s} {x['cagr']:7.1%} Sharpe {x['sharpe']:.2f} DD {x['max_dd']:.0%} "
              f"costo/año {x['cost_drag_per_year']:.0%} sin costos {x['cagr_no_costs']:.0%} {x['verdict']}", flush=True)
    passed = [k for k, x in res["variants"].items() if x["verdict"] == "aprobada"]
    res["winner"] = max(passed, key=lambda k: res["variants"][k]["sharpe"]) if passed else None
    res["runtime_s"] = round(time.time() - t0, 1)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "corto_plazo_results.json").write_text(json.dumps(res, indent=1, default=float))
    (REPORTS / "corto_plazo_informe.md").write_text(markdown(res))
    return res


def markdown(res: dict) -> str:
    def pct(x, d=1):
        return "–" if x is None else f"{x:.{d}%}".replace("-", "−")

    d, r = res["data"], res["reference"]
    L = ["# ¿Estrategias de corto plazo en cripto?", "",
         "Prueba declarada antes de correrla en `reports/corto_plazo_preregistro.md`. "
         f"Velas de 1 hora de {d['first'][:10]} a {d['last'][:10]}; fuera de muestra desde {d['oos_start'][:4]}; "
         f"costo {d['cost']:.2%} por operación; solo compras; sin kill switch (se reporta aparte).", "",
         "| Estrategia | Rend. anual | Sharpe | Caída máx. | Operaciones al año* | Costo al año | Sin costos | Con 0.30% | Veredicto |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---|",
         f"| R0 · {r['label'].split('· ')[-1]} | {pct(r['cagr'])} | {r['sharpe']:.2f} | {pct(r['max_dd'], 0)} | "
         f"{r['rebalances_per_year']:.0f} | {pct(r['cost_drag_per_year'])} | – | {pct(r['cagr_at_0.30%'])} | referencia |"]
    for k, x in res["variants"].items():
        L.append(f"| {k} · {x['label']} | {pct(x['cagr'])} | {x['sharpe']:.2f} | {pct(x['max_dd'], 0)} | "
                 f"{x['rebalances_per_year']:.0f} | {pct(x['cost_drag_per_year'])} | {pct(x['cagr_no_costs'])} | "
                 f"{pct(x['cagr_at_0.30%'])} | {x['verdict']} |")
    L += ["", "\\* Revisiones en las que se operó al menos un activo.", "", "## Criterios", ""]
    for k, x in res["variants"].items():
        L.append(f"**{k} · {x['label']}: {x['verdict']}**")
        for c in x["criteria"]:
            val = c["value"]
            txt = ", ".join(f"{y:.3f}" for y in val) if isinstance(val, list) else f"{val:.3f}"
            L.append(f"- {'✅' if c['pass'] else '❌'} {c['name']} ({txt})")
        L.append("")
    L += ["## Qué se decidió", "",
          (f"Pasa **{res['winner']}**: se agrega como bloque separado en simulado, 4 semanas mínimo." if res["winner"]
           else "Ninguna variante pasó. No se agrega nada; el bot sigue operando una vez al día."), "",
          "## Notas", "",
          "- Con kill switch de 45%: " + "; ".join(f"{k} {pct(x['with_kill_switch'])}" for k, x in res["variants"].items())
          + f"; R0 {pct(r['with_kill_switch'])} anual.",
          "- La banda de 2 puntos solo evita rebalancear por la deriva de precios: entrar o salir de una cripto "
          "siempre se opera, como dice el pre-registro.",
          "- \"Sin costos\" muestra si la regla tiene alguna ventaja antes de pagar comisiones. Parte de esa ventaja en "
          "velas de 1 hora es ilusoria: el cierre de cada hora cae a veces en el precio de compra y a veces en el de venta, "
          "y ese rebote no se puede capturar.",
          "- Rendimiento anual según el costo por operación: " + "; ".join(
              f"{k}: " + ", ".join(f"{c} → {pct(v)}" for c, v in x["cagr_by_cost"].items())
              for k, x in res["variants"].items()) + ". Bitso cobra como mínimo 0.30% (orden límite) en el nivel "
          "de volumen más bajo."]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    res = run(args.refresh)
    print("Decisión:", res["winner"] or "ninguna", f"· {res['runtime_s']} s")


if __name__ == "__main__":
    main()
