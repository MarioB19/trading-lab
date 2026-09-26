"""Prueba pre-registrada: ¿operar en tiempo real mejora al bloque cripto?

    python -m lab.research_rt            # con las velas por hora guardadas en data/
    python -m lab.research_rt --refresh  # descarga antes las velas nuevas

Las variantes y los cinco criterios están en reports/tiempo_real_preregistro.md, escritos
antes de correr esto. Genera reports/tiempo_real_results.json y reports/tiempo_real_informe.md.

Todas las variantes usan las funciones del bot (lab.portfolio): la señal diaria con el precio
del momento como cierre provisional (`with_provisional_close`) y el mismo simulador
(`simulate_portfolio`) sobre una malla por hora. Solo cambia cuándo se revisa.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import dataclasses
import hashlib
import json
import time

import numpy as np
import pandas as pd

from .backtest import perf, sharpe
from .data import DATA_DIR, ROOT, hourly_to_daily, load_hourly_panel
from .portfolio import (PortfolioParams, listed_universe, simulate_portfolio, target_weights,
                        with_provisional_close)
from .research_multi import BITSO_TRADABLE, CANDIDATES, SLEEVES, params_for
from .validation import bootstrap_compare

REPORTS = ROOT / "reports"
VARIANTS = {
    "R0": {"check": "1d", "label": "Una vez al día, 00:00 UTC (lo que hace hoy el bot)"},
    "R1": {"check": "4h", "label": "Cada 4 horas"},
    "R2": {"check": "1h", "label": "Cada hora"},
    "R3": {"check": "vigia", "label": "Vigía: rebalanceo diario; freno y kill switch cada hora"},
}
WINDOW_DAYS = 420        # historia diaria que se pasa a la señal (le sobra a los promedios de 200 días)
SIM_START = "2020-09-01"
OOS = "2021-01-01"
MIN_HISTORY = 250
PLACEBO_N = 100
HIGH_COST = 0.006


# ------------------------------------------------------------------ señal en cada hora
_G: dict = {}


def _init(H, D, p):
    _G.update(H=H, D=D, p=p)


def price_now(H: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    """Último precio conocido a la hora t (un hueco de hasta 5 horas usa el anterior)."""
    return H.loc[:t].iloc[-6:].ffill().iloc[-1]


def target_at(H: pd.DataFrame, D: pd.DataFrame, t: pd.Timestamp, p: PortfolioParams) -> np.ndarray:
    """Pesos objetivo que calcularía una revisión a la hora t, solo con datos hasta t."""
    day = (t - pd.Timedelta(hours=1)).normalize()  # a las 00:00 el día que acaba de cerrar
    panel = with_provisional_close(D, price_now(H, t), day, WINDOW_DAYS)
    elig = listed_universe(panel, MIN_HISTORY)
    return target_weights(panel, elig, p, last_only=True).iloc[-1].values


def _chunk(times):
    H, D, p = _G["H"], _G["D"], _G["p"]
    return [target_at(H, D, t, p) for t in times]


def hourly_targets(H: pd.DataFrame, p: PortfolioParams, start: str = SIM_START,
                   workers: int = 2) -> pd.DataFrame:
    """Pesos objetivo de cada hora. Se guardan en data/ y solo se calculan las horas nuevas."""
    D = hourly_to_daily(H)
    key = hashlib.sha1(json.dumps([dataclasses.asdict(p), list(H.columns), WINDOW_DAYS, MIN_HISTORY],
                                  sort_keys=True, default=str).encode()).hexdigest()[:10]
    path = DATA_DIR / f"rt_targets_{key}.csv"
    old = pd.read_csv(path, index_col=0, parse_dates=True) if path.exists() else pd.DataFrame()
    times = H.loc[start:].index
    todo = times[~times.isin(old.index)] if len(old) else times
    if len(todo):
        chunks = [todo[i:i + 500] for i in range(0, len(todo), 500)]
        with cf.ProcessPoolExecutor(workers, initializer=_init, initargs=(H, D, p)) as ex:
            rows = [r for part in ex.map(_chunk, chunks) for r in part]
        new = pd.DataFrame(rows, index=todo, columns=H.columns)
        old = pd.concat([old, new]).sort_index() if len(old) else new
        old = old[~old.index.duplicated(keep="last")]
        DATA_DIR.mkdir(exist_ok=True)
        old.to_csv(path)
    return old.reindex(times)


# ------------------------------------------------------------------ simulación de cada variante
def masks(index: pd.DatetimeIndex, kind: str) -> tuple[np.ndarray, np.ndarray | None]:
    h = np.asarray(index.hour)
    if kind == "1d":
        return h == 0, None
    if kind == "4h":
        return h % 4 == 0, None
    if kind == "1h":
        return np.ones(len(index), bool), None
    if kind == "vigia":
        return h == 0, np.ones(len(index), bool)
    raise ValueError(kind)


def hourly_params(p: PortfolioParams) -> PortfolioParams:
    """Mismos parámetros; la ventana del freno pasa de días a horas."""
    return dataclasses.replace(p, dd_peak_window=p.dd_peak_window * 24)


def to_daily(bt: pd.DataFrame) -> pd.DataFrame:
    """Rendimientos diarios (de 00:00 a 00:00 UTC) para comparar con la misma vara."""
    eq = (1 + bt["ret"]).cumprod()
    mid = eq[eq.index.hour == 0]
    day = mid.index.normalize() - pd.Timedelta(days=1)
    grp = (bt.index - pd.Timedelta(hours=1)).normalize()
    out = pd.DataFrame({"ret": mid.pct_change().values}, index=day)
    out["position"] = bt["position"].groupby(grp).mean().reindex(day).values
    out["turnover"] = bt["turnover"].groupby(grp).sum().reindex(day).values
    out["rebalances"] = (bt["turnover"] > 1e-9).groupby(grp).sum().reindex(day).values
    return out.iloc[1:].fillna(0.0)


def simulate_variant(H: pd.DataFrame, T: pd.DataFrame, p: PortfolioParams, kind: str,
                     cost: float, band: float, kill: float) -> pd.DataFrame:
    check, watch = masks(H.index, kind)
    return simulate_portfolio(H, T, hourly_params(p), cost, band, kill_dd=kill, check=check, watch=watch)


def placebo(H, T, p, kind, cost, band, kill, n=PLACEBO_N, seed=5) -> dict:
    """Mismos pesos desfasados en el tiempo (en días completos, para no mover la hora de revisión)."""
    rng = np.random.default_rng(seed)
    actual = sharpe(to_daily(simulate_variant(H, T, p, kind, cost, band, kill)).loc[OOS:]["ret"], 365)
    days = len(T) // 24
    sims = []
    for k in rng.integers(90, days - 90, size=n):
        Ts = pd.DataFrame(np.roll(T.values, int(k) * 24, axis=0), index=T.index, columns=T.columns)
        Ts = Ts.where(H.notna(), 0.0)
        sims.append(sharpe(to_daily(simulate_variant(H, Ts, p, kind, cost, band, kill)).loc[OOS:]["ret"], 365))
    sims = np.array(sims)
    return {"actual_sharpe": float(actual), "placebo_median": float(np.median(sims)),
            "p_value": float((sims >= actual).mean()), "n": int(n)}


# ------------------------------------------------------------------ prueba completa
def run(refresh: bool = False, workers: int = 2) -> dict:
    t0 = time.time()
    cfg = SLEEVES["crypto"]
    cost, band, kill = cfg["cost"], cfg["band"], cfg["kill_dd"]
    p = params_for("crypto", CANDIDATES["crypto"])
    H = load_hourly_panel(BITSO_TRADABLE, refresh=refresh)
    H = H.reindex(pd.date_range(H.index[0], H.index[-1], freq="h"))
    H = H.loc[:H.index[H.index.hour == 0][-1]]  # termina en un cierre diario completo
    T = hourly_targets(H, p, SIM_START, workers)
    Hs = H.loc[SIM_START:]
    res = {"generated": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"),
           "data": {"first": str(H.index[0]), "last": str(H.index[-1]), "assets": list(H.columns),
                    "oos_start": OOS, "cost": cost, "band": band, "kill": kill,
                    "first_hour": {c: str(H[c].first_valid_index()) for c in H.columns}},
           "variants": {}}
    daily, daily_hi = {}, {}
    for k, v in VARIANTS.items():
        bt = simulate_variant(Hs, T, p, v["check"], cost, band, kill)
        d = to_daily(bt).loc[OOS:]
        daily[k] = d
        daily_hi[k] = to_daily(simulate_variant(Hs, T, p, v["check"], HIGH_COST, band, kill)).loc[OOS:]
        pf = perf(d, 365)
        years = len(d) / 365
        res["variants"][k] = {**v, **{m: pf[m] for m in ("cagr", "vol", "sharpe", "max_dd", "exposure",
                                                        "turnover_per_year", "worst_day")},
                              "rebalances_per_year": float(d["rebalances"].sum() / years),
                              "cost_drag_per_year": float(d["turnover"].sum() / years * cost),
                              "sharpe_at_0.60%": sharpe(daily_hi[k]["ret"], 365)}
    # sanidad: la referencia por hora debe reproducir el simulador diario sobre los mismos cierres
    D = hourly_to_daily(Hs)
    Wd = T[T.index.hour == 0].copy()
    Wd.index = Wd.index.normalize() - pd.Timedelta(days=1)
    bt_d = simulate_portfolio(D, Wd.reindex(D.index), p, cost, band, kill_dd=kill)
    res["sanity_daily_engine"] = {"cagr_daily_engine": perf(bt_d.loc[OOS:], 365)["cagr"],
                                  "cagr_R0_hourly": res["variants"]["R0"]["cagr"]}

    r0 = res["variants"]["R0"]
    for k in ("R1", "R2", "R3"):
        v = res["variants"][k]
        boot = bootstrap_compare(daily[k]["ret"], daily["R0"]["ret"])
        plc = placebo(Hs, T, p, v["check"], cost, band, kill)
        crit = [
            {"id": 1, "name": "Sharpe fuera de muestra mayor que R0", "value": [v["sharpe"], r0["sharpe"]],
             "pass": v["sharpe"] > r0["sharpe"]},
            {"id": 2, "name": "Bootstrap: P(Sharpe mejor que R0) ≥ 80%", "value": boot["p_sharpe_better"],
             "pass": boot["p_sharpe_better"] >= 0.80},
            {"id": 3, "name": "Placebo p < 0.05", "value": plc["p_value"], "pass": plc["p_value"] < 0.05},
            {"id": 4, "name": "Caída máxima no peor que R0 por más de 1 punto", "value": [v["max_dd"], r0["max_dd"]],
             "pass": v["max_dd"] >= r0["max_dd"] - 0.01},
            {"id": 5, "name": "Con 0.60% por operación, Sharpe mayor que R0 con 0.60%",
             "value": [v["sharpe_at_0.60%"], r0["sharpe_at_0.60%"]],
             "pass": v["sharpe_at_0.60%"] > r0["sharpe_at_0.60%"]},
        ]
        v.update(bootstrap=boot, placebo=plc, criteria=crit,
                 verdict="aprobada" if all(c["pass"] for c in crit) else "no aprobada")
    # Análisis adicional, NO pre-registrado (no decide nada): con este universo las cuatro variantes
    # tocan el kill switch; sin él se ve si revisar más seguido ayuda o estorba en el resto del periodo.
    extra = {}
    for k, v in VARIANTS.items():
        dk = to_daily(simulate_variant(Hs, T, p, v["check"], cost, band, None)).loc[OOS:]
        pk = perf(dk, 365)
        extra[k] = {m: pk[m] for m in ("cagr", "sharpe", "max_dd")}
        extra[k]["cost_drag_per_year"] = float(dk["turnover"].sum() / (len(dk) / 365) * cost)
    res["no_kill_switch_extra"] = extra
    kills = {}
    for k, v in VARIANTS.items():
        b_ = simulate_variant(Hs, T, p, v["check"], cost, band, kill)
        k_on = b_.index[b_["brake"] == 0]
        kills[k] = str(k_on[0]) if len(k_on) else None
    res["kill_switch_date"] = kills

    passed = [k for k in ("R1", "R2", "R3") if res["variants"][k]["verdict"] == "aprobada"]
    res["winner"] = max(passed, key=lambda k: res["variants"][k]["sharpe"]) if passed else None
    res["mode"] = {"R1": "rebalance_4h", "R2": "rebalance_1h", "R3": "watch", None: "observe"}[res["winner"]]
    res["runtime_s"] = round(time.time() - t0, 1)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "tiempo_real_results.json").write_text(json.dumps(res, indent=1, default=float))
    (REPORTS / "tiempo_real_informe.md").write_text(markdown(res))
    return res


def markdown(res: dict) -> str:
    def pct(x, d=1):
        return "–" if x is None else f"{x:.{d}%}".replace("-", "−")

    v = res["variants"]
    d = res["data"]
    L = ["# ¿Operar en tiempo real mejora al bot cripto?", "",
         "Prueba declarada antes de correrla en `reports/tiempo_real_preregistro.md`. "
         f"Velas de 1 hora (Coinbase y Bitstamp) de {d['first'][:10]} a {d['last'][:10]}; "
         f"fuera de muestra desde {d['oos_start'][:4]}; costo {d['cost']:.2%} por operación; "
         "misma regla y mismos candados que el bot. Solo cambia cada cuánto revisa.", "",
         "| Variante | Rend. anual | Sharpe | Caída máx. | Rebalanceos al año | Costo al año | Veredicto |",
         "|---|---:|---:|---:|---:|---:|---|"]
    for k, x in v.items():
        L.append(f"| {k} · {x['label']} | {pct(x['cagr'])} | {x['sharpe']:.2f} | {pct(x['max_dd'], 0)} | "
                 f"{x['rebalances_per_year']:.0f} | {pct(x['cost_drag_per_year'])} | {x.get('verdict', 'referencia')} |")
    L += ["", "## Criterios", ""]
    for k in ("R1", "R2", "R3"):
        L.append(f"**{k} · {v[k]['label']}: {v[k]['verdict']}**")
        for c in v[k]["criteria"]:
            val = c["value"]
            txt = (", ".join(f"{x:.3f}" for x in val) if isinstance(val, list) else f"{val:.3f}")
            L.append(f"- {'✅' if c['pass'] else '❌'} {c['name']} ({txt})")
        L.append("")
    x = res["no_kill_switch_extra"]
    L += ["## Análisis adicional (no pre-registrado; no cambia la decisión)", "",
          "Con este universo las cuatro variantes tocan el kill switch de 45% "
          f"(R0: {str(res['kill_switch_date']['R0'])[:10]}) y después quedan en efectivo, así que la comparación "
          "de 2023 en adelante es plana. Sin kill switch se ve el efecto de revisar más seguido en todo el periodo:", "",
          "| Variante | Rend. anual | Sharpe | Caída máx. | Costo al año |", "|---|---:|---:|---:|---:|"]
    for k, y in x.items():
        L.append(f"| {k} · {v[k]['label']} | {pct(y['cagr'])} | {y['sharpe']:.2f} | {pct(y['max_dd'], 0)} | {pct(y['cost_drag_per_year'])} |")
    L.append("")
    s = res["sanity_daily_engine"]
    L += ["## Qué se decidió", "",
          (f"Pasa **{res['winner']}**: se enciende en simulado 4 semanas antes de considerar dinero real."
           if res["winner"] else
           "Ninguna variante pasó. El bot sigue operando una vez al día y el motor en tiempo real queda en "
           "**modo observación**: cada hora actualiza valuación, caída y precios, sin operar."), "",
          "## Notas", "",
          f"- Control: la referencia simulada por hora da {pct(s['cagr_R0_hourly'])} anual y el simulador diario sobre "
          f"los mismos cierres {pct(s['cagr_daily_engine'])}; el motor por hora reproduce al diario.",
          "- El universo es el del bot, con historia por hora en esas fuentes: SOL, ADA, DOGE, AVAX, HBAR y NEAR "
          "entran más tarde que en la investigación diaria y TRX casi no tiene historia. Por eso el rendimiento absoluto "
          "no es comparable con `multi_informe.md`; la comparación entre variantes sí, porque comparten datos.",
          "- Placebo: los mismos pesos desfasados días completos; mide si el timing de la variante tiene señal."]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    res = run(args.refresh, args.workers)
    for k, x in res["variants"].items():
        print(f"{k} {x['label'][:40]:40s} {x['cagr']:7.2%} Sharpe {x['sharpe']:.2f} DD {x['max_dd']:.1%} "
              f"rebal/año {x['rebalances_per_year']:.0f} costo/año {x['cost_drag_per_year']:.1%} {x.get('verdict', '')}")
    print("Decisión:", res["winner"] or "ninguna (modo observación)", f"· {res['runtime_s']} s")


if __name__ == "__main__":
    main()
