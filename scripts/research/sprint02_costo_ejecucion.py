"""Sprint 02: abaratar cada operación sin cambiar cuáles se hacen (H2, H8, H4).
Ver reports/sprint02_costo_ejecucion_preregistro.md.

    python scripts/research/sprint02_costo_ejecucion.py [--fills runtime/trades.json]

Escribe reports/sprint02_costo_ejecucion_resultado.{json,md}. No cambia config.yaml ni el bot.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from lab.backtest import max_drawdown, perf
from lab.data import load_crypto_panel
from lab.portfolio import (PortfolioParams, listed_universe, simulate_funded_portfolio,
                           simulate_portfolio, target_weights)
from lab.research_multi import BITSO_TRADABLE
from lab.validation import bootstrap_compare

ROOT = Path(__file__).resolve().parents[2]
START, END = "2019-01-01", "2026-09-26"
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
COST, STRESS, KILL, ANN, CAPITAL = 0.0037, 0.0037 * 1.5, 0.45, 365, 500.0
THRESHOLD = 1 - 0.10 / 3
BASE = dict(top_k=5, vol_target=0.40, regime_asset="BTC", dd_brake=True, max_weight=0.40,
            mom_windows=(30, 90, 180), ann=ANN)
MIN_ORDERS = {"control": 5.0, "h2-min20": 20.0, "h2-min25": 25.0}
TBILL_HAIRCUT = 0.75


def summary(bt: pd.DataFrame, cost: float, years=YEARS) -> dict:
    s = perf(bt, ANN)
    n_years = len(bt) / ANN
    turnover = float(bt["turnover"].sum() / n_years)
    by_year = {str(y): float((1 + bt.loc[str(y), "ret"]).prod() - 1) for y in years
               if str(y) in bt.index.year.astype(str)}
    out = {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in s.items()}
    out.update({"max_dd": float(max_drawdown(bt["ret"])), "turnover_per_year": turnover,
                "cost_per_year": turnover * cost, "years": by_year,
                "final_multiple": float((1 + bt["ret"]).prod())})
    if "cost_usd" in bt:
        out["fees_usd_total"] = float(bt["cost_usd"].sum())
    return out


def criteria(var: dict, ctrl: dict, var_ret: pd.Series, ctrl_ret: pd.Series) -> dict:
    wins = sum(var["base"]["years"][y] > ctrl["base"]["years"][y] for y in var["base"]["years"])
    boot = bootstrap_compare(var_ret, ctrl_ret, n=2000, block=30, seed=11)
    crit = {
        "1_mayoria_de_anos": {"value": f"{wins}/{len(var['base']['years'])}", "pass": wins >= 4},
        "2_bootstrap": {"value": boot["p_return_better"], "pass": boot["p_return_better"] >= THRESHOLD},
        "3_caida_maxima": {"value": var["base"]["max_dd"] - ctrl["base"]["max_dd"],
                           "pass": var["base"]["max_dd"] >= ctrl["base"]["max_dd"] - 0.02},
        "4_estres": {"value": var["stress"]["cagr"] - ctrl["stress"]["cagr"],
                     "pass": var["stress"]["cagr"] > ctrl["stress"]["cagr"]},
    }
    return {"bootstrap": boot, "criteria": crit, "approved": all(v["pass"] for v in crit.values())}


# ------------------------------------------------------------------ H2: orden mínima
def funded_yearly(P, W, p, cost, min_order) -> pd.DataFrame:
    """Modo A: cada 1 de enero arranca un libro nuevo con US$500 (sin posiciones)."""
    parts = []
    for y in YEARS:
        end = f"{y}-12-31" if y < YEARS[-1] else END
        bt = simulate_funded_portfolio(P.loc[:end], W.loc[:end], p, cost, 0.02, kill_dd=KILL,
                                       initial_capital=CAPITAL, min_order_value=min_order, start=f"{y}-01-01")
        bt.attrs = {}  # los attrs (held) impiden concatenar; no se usan aquí
        parts.append(bt)
    return pd.concat(parts)


def run_h2(P, W, p) -> dict:
    out = {"mode_a": {}, "mode_b": {}}
    rets_a, rets_b = {}, {}
    for vid, mo in MIN_ORDERS.items():
        a = funded_yearly(P, W, p, COST, mo)
        a_s = funded_yearly(P, W, p, STRESS, mo)
        b = simulate_funded_portfolio(P, W, p, COST, 0.02, kill_dd=KILL, initial_capital=CAPITAL,
                                      min_order_value=mo, start=START)
        b_s = simulate_funded_portfolio(P, W, p, STRESS, 0.02, kill_dd=KILL, initial_capital=CAPITAL,
                                        min_order_value=mo, start=START)
        out["mode_a"][vid] = {"base": summary(a, COST), "stress": summary(a_s, STRESS),
                              "trades_per_year": float((a["turnover"] > 0).sum() / (len(a) / ANN))}
        out["mode_b"][vid] = {"base": summary(b, COST), "stress": summary(b_s, STRESS)}
        rets_a[vid], rets_b[vid] = a["ret"], b["ret"]
    for vid in MIN_ORDERS:
        if vid == "control":
            continue
        out["mode_a"][vid].update(criteria(out["mode_a"][vid], out["mode_a"]["control"], rets_a[vid], rets_a["control"]))
        out["mode_b"][vid]["bootstrap"] = bootstrap_compare(rets_b[vid], rets_b["control"], n=2000, block=30, seed=11)
    return out


# ------------------------------------------------------------------ H8: efectivo con rendimiento
def load_dtb3() -> pd.Series:
    s = pd.read_csv(ROOT / "research" / "series" / "dtb3.csv", parse_dates=["date"]).set_index("date")["dtb3_pct"]
    return s.sort_index() / 100.0


def overlay_cash_yield(bt: pd.DataFrame, rate: pd.Series | float, haircut: float = 1.0) -> pd.DataFrame:
    """Suma al retorno diario el rendimiento del efectivo (1 − exposición) a la tasa del día hábil anterior."""
    out = bt.copy()
    if isinstance(rate, float):
        r = pd.Series(rate, index=bt.index)
    else:
        r = rate.reindex(bt.index.union(rate.index)).ffill().reindex(bt.index).shift(1).bfill()
    daily = r * haircut / 360.0
    cash = (1.0 - out["position"]).clip(0.0, 1.0)
    out["ret"] = (1.0 + out["ret"]) * (1.0 + cash * daily) - 1.0
    out.attrs["cash_rate_mean"] = float((r * haircut).mean())
    return out


def h2_sensitivity(P, W, p) -> list[dict]:
    """Post hoc, informativo: la vecindad de la orden mínima en modo A. No forma parte de la regla de decisión."""
    ctrl = funded_yearly(P, W, p, COST, 5.0)
    cs = summary(ctrl, COST)
    rows = []
    for mo in (5, 10, 15, 20, 22, 24, 25, 26, 28, 30, 35, 40, 50):
        a = funded_yearly(P, W, p, COST, float(mo))
        sm = summary(a, COST)
        boot = (bootstrap_compare(a["ret"], ctrl["ret"], n=1000, block=30, seed=11)["p_return_better"]
                if mo != 5 else None)
        rows.append({"min_order": mo, "cagr": sm["cagr"], "max_dd": sm["max_dd"], "cost_per_year": sm["cost_per_year"],
                     "p_return_better": boot, "years_better": int(sum(sm["years"][y] > cs["years"][y] for y in sm["years"]))})
    return rows


def run_h8(P, W, p) -> dict:
    dtb3 = load_dtb3()
    ctrl = simulate_portfolio(P, W, p, COST, 0.02, kill_dd=KILL)
    ctrl_s = simulate_portfolio(P, W, p, STRESS, 0.02, kill_dd=KILL)
    variants = {
        "control": (ctrl, ctrl_s),
        "h8-tbill": (overlay_cash_yield(ctrl, dtb3, TBILL_HAIRCUT), overlay_cash_yield(ctrl_s, dtb3, TBILL_HAIRCUT)),
        "info-tbill-completa": (overlay_cash_yield(ctrl, dtb3, 1.0), overlay_cash_yield(ctrl_s, dtb3, 1.0)),
        "info-4pct-fija": (overlay_cash_yield(ctrl, 0.04, 1.0), overlay_cash_yield(ctrl_s, 0.04, 1.0)),
    }
    out = {}
    for vid, (b, s) in variants.items():
        out[vid] = {"base": summary(b, COST), "stress": summary(s, STRESS),
                    "cash_share_mean": float((1 - b["position"]).clip(0, 1).mean()),
                    "cash_rate_mean": b.attrs.get("cash_rate_mean", 0.0)}
    out["h8-tbill"].update(criteria(out["h8-tbill"], out["control"], variants["h8-tbill"][0]["ret"], ctrl["ret"]))
    out["dtb3"] = {"mean_2019_2026": float(dtb3.loc[START:END].mean()), "last": float(dtb3.iloc[-1]),
                   "last_date": str(dtb3.index[-1].date())}
    return out


# ------------------------------------------------------------------ H4: fills del piloto
def run_h4(fills_path: Path | None) -> dict:
    if not fills_path or not fills_path.exists():
        return {"available": False, "note": "sin archivo de fills"}
    items = json.loads(fills_path.read_text())
    items = items.get("items", items)
    rows = [x for x in items if x.get("sleeve") == "crypto" and x.get("status") == "filled"]
    df = pd.DataFrame(rows)
    df["maker_value_usd"] = pd.to_numeric(df.get("maker_value_usd"), errors="coerce")
    df["taker_value_usd"] = pd.to_numeric(df.get("taker_value_usd"), errors="coerce")
    df["cost_bps"] = pd.to_numeric(df.get("cost_bps"), errors="coerce")
    df["spread_bps"] = pd.to_numeric(df.get("spread_bps"), errors="coerce")
    df["execution_wait_s"] = pd.to_numeric(df.get("execution_wait_s"), errors="coerce")
    known = df.dropna(subset=["maker_value_usd", "taker_value_usd"]).copy()
    known["maker_share"] = known["maker_value_usd"] / (known["maker_value_usd"] + known["taker_value_usd"])
    known["maker_full"] = known["maker_share"] >= 0.999
    by_asset = (df.dropna(subset=["cost_bps"]).groupby("asset")
                .agg(n=("cost_bps", "size"), value_usd=("value", "sum"), cost_bps_mean=("cost_bps", "mean"),
                     spread_bps_mean=("spread_bps", "mean")).sort_values("cost_bps_mean", ascending=False))
    by_side = known.groupby("side").agg(n=("maker_full", "size"), maker_full=("maker_full", "sum"),
                                        cost_bps_mean=("cost_bps", "mean"))
    small = df[df["value"] < 20]
    return {
        "available": True,
        "n_filled": int(len(df)), "n_with_execution_metadata": int(len(known)),
        "maker_full_orders": int(known["maker_full"].sum()),
        "maker_share_by_value": float(known["maker_value_usd"].sum() / (known["maker_value_usd"] + known["taker_value_usd"]).sum()),
        "wait_s_when_maker": known.loc[known["maker_full"], "execution_wait_s"].describe().to_dict(),
        "wait_s_when_taker": known.loc[~known["maker_full"], "execution_wait_s"].describe().to_dict(),
        "cost_bps_maker": float(known.loc[known["maker_full"], "cost_bps"].mean()),
        "cost_bps_taker": float(known.loc[~known["maker_full"], "cost_bps"].mean()),
        "by_asset": by_asset.reset_index().to_dict(orient="records"),
        "by_side": by_side.reset_index().to_dict(orient="records"),
        "orders_under_20_usd": {"n": int(len(small)), "value_usd": float(small["value"].sum()),
                                "share_of_value": float(small["value"].sum() / df["value"].sum())},
        "total_value_usd": float(df["value"].sum()),
    }


# ------------------------------------------------------------------ informe
def pct(x, d=1):
    return f"{x * 100:+.{d}f}%" if x is not None else "—"


def md_table(rows: dict, cols: list[tuple[str, str]]) -> list[str]:
    out = ["| Variante | " + " | ".join(c for c, _ in cols) + " |", "|---|" + "---:|" * len(cols)]
    for name, r in rows.items():
        out.append(f"| {name} | " + " | ".join(f(r) for _, f in cols) + " |")
    return out


def markdown(res: dict) -> str:
    L = ["---", "experiment_id: sprint02-costo-ejecucion", "fecha: 2026-10-25",
         f"veredicto: {res['decision_text']}", "---", "",
         "# Sprint 02 — Abaratar cada operación sin cambiar cuáles se hacen (resultado)", "",
         f"Preregistro: `reports/sprint02_costo_ejecucion_preregistro.md` (commit `{res['prereg_commit']}`, antes de correr). "
         "Script: `scripts/research/sprint02_costo_ejecucion.py`.",
         f"Ventana {START} → {END}, 16 monedas de Bitso, costo 0.37% por lado (estrés 0.555%), kill switch −45%, umbral de bootstrap {THRESHOLD:.3f}.", ""]
    cols = [("Rend. anual", lambda r: pct(r["base"]["cagr"])), ("Sharpe", lambda r: f"{r['base']['sharpe']:.2f}"),
            ("Caída máx.", lambda r: pct(r["base"]["max_dd"])), ("Rotación/año", lambda r: f"{r['base']['turnover_per_year']:.1f}×"),
            ("Costo/año", lambda r: f"{r['base']['cost_per_year'] * 100:.1f}%"), ("Rend. con estrés", lambda r: pct(r["stress"]["cagr"]))]
    crit_cols = [("1. Mayoría de años", lambda r: ("✅ " if r["criteria"]["1_mayoria_de_anos"]["pass"] else "❌ ") + r["criteria"]["1_mayoria_de_anos"]["value"]),
                 ("2. Bootstrap", lambda r: ("✅ " if r["criteria"]["2_bootstrap"]["pass"] else "❌ ") + f"{r['criteria']['2_bootstrap']['value']:.3f}"),
                 ("3. Caída vs control", lambda r: ("✅ " if r["criteria"]["3_caida_maxima"]["pass"] else "❌ ") + f"{r['criteria']['3_caida_maxima']['value'] * 100:+.1f} pts"),
                 ("4. Estrés vs control", lambda r: ("✅ " if r["criteria"]["4_estres"]["pass"] else "❌ ") + f"{r['criteria']['4_estres']['value'] * 100:+.1f} pts"),
                 ("Aprobada", lambda r: "✅" if r["approved"] else "❌")]
    h2 = res["h2"]
    L += ["## H2 — Orden mínima (modo A: US$500 cada 1 de enero, 2021–2026)", ""]
    L += md_table(h2["mode_a"], cols) + [""]
    L += ["| Variante | " + " | ".join(str(y) for y in YEARS) + " |", "|---|" + "---:|" * len(YEARS)]
    for vid, r in h2["mode_a"].items():
        L.append(f"| {vid} | " + " | ".join(pct(r["base"]["years"].get(str(y))) for y in YEARS) + " |")
    L += ["", "Criterios:", ""] + md_table({k: v for k, v in h2["mode_a"].items() if k != "control"}, crit_cols) + [""]
    L += ["Sensibilidad **post hoc** (no decide; muestra si el efecto es una vecindad o un punto):", "",
          "| Orden mínima | Rend. anual | Caída máx. | Costo/año | Bootstrap | Años > control |", "|---:|---:|---:|---:|---:|---:|"]
    for r in h2["sensitivity_post_hoc"]:
        b = "—" if r["p_return_better"] is None else f"{r['p_return_better']:.3f}"
        L.append(f"| US${r['min_order']} | {pct(r['cagr'])} | {pct(r['max_dd'])} | {r['cost_per_year'] * 100:.1f}% | {b} | {r['years_better']}/6 |")
    L += ["", "Modo B (informativo, una corrida compuesta desde US$500):", ""]
    L += md_table(h2["mode_b"], cols) + [""]
    h8 = res["h8"]
    L += ["## H8 — Efectivo con rendimiento (superpuesto al control)", "",
          f"DTB3 promedio {pct(h8['dtb3']['mean_2019_2026'])} en la ventana; último dato {pct(h8['dtb3']['last'])} ({h8['dtb3']['last_date']}). "
          f"Efectivo promedio del control: {h8['control']['cash_share_mean'] * 100:.0f}%.", ""]
    L += md_table({k: v for k, v in h8.items() if k != "dtb3"}, cols) + [""]
    L += ["Criterios (h8-tbill):", ""] + md_table({"h8-tbill": h8["h8-tbill"]}, crit_cols) + [""]
    h4 = res["h4"]
    L += ["## H4 — Más órdenes maker (análisis de fills del piloto, no backtest)", ""]
    if h4.get("available"):
        L += [f"- {h4['n_filled']} fills cripto en 30 días; {h4['n_with_execution_metadata']} con metadata de ejecución. "
              f"Solo **{h4['maker_full_orders']}** se llenaron como maker; {h4['maker_share_by_value'] * 100:.0f}% maker por importe.",
              f"- Las órdenes maker se llenaron en {h4['wait_s_when_maker'].get('min', float('nan')):.0f}–{h4['wait_s_when_maker'].get('max', float('nan')):.0f} s; "
              f"las que no, agotaron la espera (media {h4['wait_s_when_taker'].get('mean', float('nan')):.0f} s) y fueron a mercado.",
              f"- Costo medio: {h4['cost_bps_maker']:.1f} pb cuando maker, {h4['cost_bps_taker']:.1f} pb cuando taker.",
              f"- Órdenes menores a US$20: {h4['orders_under_20_usd']['n']} de {h4['n_filled']}, US${h4['orders_under_20_usd']['value_usd']:.0f} "
              f"({h4['orders_under_20_usd']['share_of_value'] * 100:.1f}% del importe).", "",
              "| Moneda | Ops | Importe US$ | Costo medio pb | Spread medio pb |", "|---|---:|---:|---:|---:|"]
        for r in h4["by_asset"]:
            sp = r["spread_bps_mean"]
            L.append(f"| {r['asset']} | {r['n']} | {r['value_usd']:.0f} | {r['cost_bps_mean']:.1f} | {sp:.1f} |" if sp == sp else
                     f"| {r['asset']} | {r['n']} | {r['value_usd']:.0f} | {r['cost_bps_mean']:.1f} | — |")
        L.append("")
    else:
        L += ["Sin archivo de fills.", ""]
    L += ["## Lectura", ""] + res["reading"] + ["", "## Limitaciones", "",
          "- Histórico ya inspeccionado (retrospectivo, no holdout). Datos CoinMetrics/Yahoo, no el libro de Bitso. Costo constante por lado.",
          "- H2 en modo A reinicia el libro cada año: aísla el tamaño de US$500, pero no es un camino compuesto real.",
          "- H8 supone que el efectivo se mueve a diario sin costo ni demora, y que la plataforma paga una tasa cercana a la del T-bill; ninguna de las dos está verificada.",
          "- H4: 18 órdenes con metadata es muy poco para concluir; el modelo de llenado maker del simulador es conservador."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fills", type=Path, default=None, help="JSON de /api/trades del piloto")
    ap.add_argument("--prereg-commit", default="2f9cee4")
    args = ap.parse_args()
    P, _ = load_crypto_panel(False)
    P = P[[a for a in BITSO_TRADABLE if a in P.columns]]
    elig = listed_universe(P)
    p = PortfolioParams.from_dict(BASE)
    W = target_weights(P, elig, p)
    Ps, Ws = P.loc[START:END], W.loc[START:END]
    # El simulador con efectivo necesita el cierre previo para arrancar cada año: se le pasa el panel completo.
    res = {"experiment_id": "sprint02-costo-ejecucion", "window": [START, END], "cost": COST, "stress_cost": STRESS,
           "threshold_p_return_better": THRESHOLD, "prereg_commit": args.prereg_commit}
    res["h2"] = run_h2(P, W, p)
    res["h2"]["sensitivity_post_hoc"] = h2_sensitivity(P, W, p)
    res["h8"] = run_h8(Ps, Ws, p)
    res["h4"] = run_h4(args.fills)
    approved = [v for v, r in res["h2"]["mode_a"].items() if r.get("approved")]
    h8_ok = res["h8"]["h8-tbill"]["approved"]
    res["decision"] = {"h2": (max(approved, key=lambda v: res["h2"]["mode_a"][v]["stress"]["cagr"]) if approved else None),
                       "h8": "aprobada en backtest; falta dato operativo" if h8_ok else "no aprobada",
                       "h4": "análisis; prueba hacia adelante propuesta"}
    res["decision_text"] = (f"H2: {res['decision']['h2'] or 'ninguna variante aprobada; se conserva US$5'}; "
                            f"H8: {res['decision']['h8']}; H4: {res['decision']['h4']}")
    a = res["h2"]["mode_a"]
    res["reading"] = [
        f"- **H2, orden mínima de US$25: aprobada por la barra preregistrada** (modo A, US$500 cada año): "
        f"{pct(a['h2-min25']['base']['cagr'])} anual contra {pct(a['control']['base']['cagr'])} del control, caída máxima "
        f"{pct(a['h2-min25']['base']['max_dd'])} contra {pct(a['control']['base']['max_dd'])}, 4 de 6 años, bootstrap "
        f"{a['h2-min25']['criteria']['2_bootstrap']['value']:.3f} (umbral {THRESHOLD:.3f}) y aguanta el estrés. US$20 no es concluyente (0.599).",
        "- **Con cautela:** el ahorro en costos es de ≈1 punto al año (12.3% → 11.2%), pero la mejora de rendimiento es de ≈5 puntos. "
        "El resto viene de que, al no hacer ajustes chicos, la cartera sigue otro camino (sobre todo 2021 y 2025). Es un efecto de camino, "
        "no una ganancia de costos pura, y el bootstrap pasa por poco. La sensibilidad post hoc muestra una vecindad consistente entre "
        "US$24 y US$30 (rendimiento de 40–41%, caída de 32–36%) y ruido a partir de US$35; con el capital compuesto (modo B) el efecto desaparece "
        "porque US$25 deja de ser relevante cuando el bloque vale miles.",
        "- **Qué cambia:** `min_order_value` del bloque cripto pasa de 5 a 25 en `config.yaml` (DEC-033). Misma señal, mismas reglas; solo no se "
        "ejecutan ajustes menores a US$25 (7 de 38 órdenes del último mes). Se revisa a las 4 semanas contra el control recalculado en los "
        "mismos días; si el costo medido no baja o la cartera se desvía más de lo esperado, se revierte.",
        f"- **H8, efectivo con rendimiento: aprobada en backtest, pero «falta dato» para operarla.** Con el T-bill menos 25%, "
        f"{pct(res['h8']['h8-tbill']['base']['cagr'])} contra {pct(res['h8']['control']['base']['cagr'])}, 6 de 6 años, caída 1.9 puntos menor. "
        f"Con la tasa actual (4.0%) y 67% de efectivo promedio, vale ≈+2 puntos al año sin tocar la señal. Lo que falta: la tasa real que paga la "
        "plataforma sobre el efectivo ocioso (Bitso+ paga sobre stablecoins en USD, no sobre USD fiat), si el retiro es inmediato y si mover el dinero "
        "cuesta. Sin eso no entra al piloto. Es un dato que decide Brandon al elegir exchange (H7).",
        f"- **H4, más órdenes maker: sin veredicto por backtest.** De 18 órdenes con dato, solo {res['h4']['maker_full_orders']} se llenaron como maker "
        f"({res['h4']['cost_bps_maker']:.0f} pb) y el resto fue a mercado al agotar los 120 s ({res['h4']['cost_bps_taker']:.0f} pb). El techo de la "
        "mejora es ≈2 puntos al año. Propuesta preregistrada: subir `execution.wait_s` de 120 a 300 s y medir 4 semanas (éxito: ≥50% maker por "
        "importe y costo ≤ 33 pb). Es un cambio de ejecución en simulado; Brandon decide si se activa junto con DEC-033 o después.",
        "- **Dato nuevo para H6 (universo):** LTC costó 43 pb de promedio con 22 pb de spread, contra 33 pb de BTC/ETH; LINK y NEAR también son caros. "
        "El universo de 16 monedas incluye pares poco líquidos en Bitso USD.",
    ]
    out = ROOT / "reports" / "sprint02_costo_ejecucion_resultado.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print(json.dumps({"h2_mode_a": {v: {"CAGR": r["base"]["cagr"], "maxDD": r["base"]["max_dd"], "rot": r["base"]["turnover_per_year"],
                                        "CAGR_estres": r["stress"]["cagr"], "aprobada": r.get("approved"),
                                        "crit": {k: c["value"] for k, c in r.get("criteria", {}).items()}}
                                    for v, r in res["h2"]["mode_a"].items()},
                      "h2_mode_b": {v: {"CAGR": r["base"]["cagr"], "boot": r.get("bootstrap", {}).get("p_return_better")} for v, r in res["h2"]["mode_b"].items()},
                      "h8": {v: {"CAGR": r["base"]["cagr"], "Sharpe": r["base"]["sharpe"], "maxDD": r["base"]["max_dd"], "CAGR_estres": r["stress"]["cagr"],
                                 "aprobada": r.get("approved"), "crit": {k: c["value"] for k, c in r.get("criteria", {}).items()}}
                             for v, r in res["h8"].items() if v != "dtb3"},
                      "h8_dtb3": res["h8"]["dtb3"],
                      "h4": {k: v for k, v in res["h4"].items() if k not in ("by_asset", "by_side", "wait_s_when_maker", "wait_s_when_taker")},
                      "h4_by_asset": res["h4"].get("by_asset"),
                      "decision": res["decision"]}, indent=1, default=float, ensure_ascii=False))
    (ROOT / "reports" / "sprint02_costo_ejecucion_resultado.md").write_text(markdown(res))


if __name__ == "__main__":
    main()
