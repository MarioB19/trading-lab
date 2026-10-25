#!/usr/bin/env python3
"""Revisión del piloto a partir de un snapshot de `tl.py` (solo biblioteca estándar).

Uso:
  review.py alerts   SNAPSHOT.json            # salud y kill switches; código 1 si hay alertas
  review.py weekly   SNAPSHOT.json [--json]   # atribución de la semana, 28 días y desde el primer cierre

La atribución (mercado + estrategia − costos) ya no se calcula aquí: sale de `/api/attribution`, que usa
`lab.attribution` en el servidor. Así el panel y la revisión dan la misma cifra (una sola fórmula, DEC-032).
Un snapshot anterior al 25-oct sin `attribution` no sirve para `weekly`: toma uno nuevo con `tl.py snapshot`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

KILL = {"crypto": 0.45, "stocks": 0.25}
WARN_POINTS = 0.05
STALE_HOURS = 30


def _data(snap: dict, key: str):
    node = snap.get("pilot", {}).get(key, {})
    return node.get("data") if isinstance(node, dict) and node.get("http") == 200 else None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_utc(s: str | None):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M"):
        try:
            t = dt.datetime.fromisoformat(s) if fmt is None else dt.datetime.strptime(s, fmt)
            return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def equity_by_sleeve(snap: dict) -> dict[str, list[dict]]:
    rows = (_data(snap, "equity") or {}).get("items", [])
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if r.get("mode", "paper") != "paper" or _f(r.get("equity")) is None:
            continue
        out.setdefault(r["sleeve"], {})[r["date"]] = r  # una fila por fecha (la última gana)
    return {s: [d[k] for k in sorted(d)] for s, d in out.items()}


def alerts(snap: dict) -> list[str]:
    found: list[str] = []
    st = _data(snap, "status")
    if st is None:
        return ["No se pudo leer /api/status del piloto (credenciales, red o servicio caído)."]
    if st.get("mode") != "paper":
        found.append(f"MODO NO VERIFICADO COMO PAPER: {st.get('mode')!r}. Revisar de inmediato.")
    if not st.get("ready"):
        found.append(f"Piloto no listo: {st.get('reason')}")
    storage = st.get("storage") or {}
    if storage.get("pending_orders") or storage.get("unknown_orders"):
        found.append(f"Órdenes sin conciliar: pendientes={storage.get('pending_orders')} "
                     f"desconocidas={storage.get('unknown_orders')}")
    runtime = st.get("runtime") or {}
    last = _parse_utc(runtime.get("last_success_utc"))
    try:
        taken = dt.datetime.strptime(snap.get("taken_at_utc", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        taken = dt.datetime.now(dt.timezone.utc)
    if last is None:
        found.append("Sin último ciclo exitoso registrado.")
    elif (taken - last).total_seconds() > STALE_HOURS * 3600:
        found.append(f"Último ciclo exitoso hace {(taken - last).total_seconds() / 3600:.0f} h (> {STALE_HOURS} h).")
    for sleeve, rows in equity_by_sleeve(snap).items():
        dd = _f(rows[-1].get("drawdown")) if rows else None
        if dd is None:
            continue
        limit = KILL.get(sleeve)
        if limit is not None and -dd >= limit - WARN_POINTS:
            found.append(f"Kill switch {sleeve}: caída {dd:.1%}, a {(limit + dd) * 100:.1f} puntos del límite −{limit:.0%}.")
    return found


def weekly(snap: dict) -> dict:
    data = _data(snap, "attribution")
    if not isinstance(data, dict) or "week" not in data:
        return {"error": "El snapshot no trae /api/attribution (es anterior al panel único). Toma uno nuevo con tl.py snapshot."}
    perf = _data(snap, "performance") or {}
    cur = perf.get("current") or {}
    data["since_start_performance"] = {"equity_usd": cur.get("equity_usd"), "pnl_usd": cur.get("pnl_usd"),
                                       "pnl_mxn": cur.get("pnl_mxn"), "as_of_utc": cur.get("as_of_utc")}
    return data


def _m(x, pct=False):
    if x is None:
        return "sin dato"
    return f"{x:+.2%}" if pct else f"{x:+,.2f}"


LABELS = {"week": "Semana", "days_28": "28 días", "since_start": "Desde el primer cierre"}


def _table(w: dict) -> list[str]:
    fx = w.get("fx_usd_mxn")
    lines = [f"Ventana {w['start']} → {w['end']} (cierres del bot). Tipo de cambio {fx or 'sin dato'}.", "",
             "| Bloque | Resultado US$ | % | Referencia | Beta | Mercado | Estrategia | Costos | Ops | pb | Maker |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s, d in w["sleeves"].items():
        if "error" in d:
            lines.append(f"| {s} | {d['error']} |||||||||| ")
            continue
        b = "sin dato" if d["beta"] is None else format(d["beta"], ".2f")
        bps = "—" if d["cost_bps_weighted"] is None else format(d["cost_bps_weighted"], ".0f")
        mk = "—" if d["maker_share"] is None else format(d["maker_share"], ".0%")
        lines.append(f"| {s} | {_m(d['pnl_usd'])} | {_m(d['pnl_pct'], True)} | {_m(d['benchmark_return'], True)} | "
                     f"{b} | {_m(d['market_usd'])} | {_m(d['strategy_usd'])} | {_m(-d['costs_usd'])} | "
                     f"{d['trades']} | {bps} | {mk} |")
    t = w["total"]
    mxn = f" (MXN {t['pnl'] * fx:+,.0f})" if fx else ""
    extra = f" + sin atribuir {_m(t['unattributed'])}" if t["unattributed"] else ""
    lines += ["", f"Total del periodo: US${t['pnl']:+,.2f}{mxn} = mercado {_m(t['market'])} + estrategia "
                  f"{_m(t['strategy'])}{extra} − costos {t['costs']:,.2f}."]
    return lines


def markdown(data: dict) -> str:
    if "error" in data:
        return data["error"]
    lines = []
    for key in ("week", "days_28", "since_start"):
        w = data.get(key) or {}
        if "error" in w or not w:
            lines += [f"**{LABELS[key]}:** {w.get('error', 'sin dato')}", ""]
            continue
        lines += [f"**{LABELS[key]}**", ""] + _table(w) + [""]
    s = data["since_start_performance"]
    lines.append(f"Desde el inicio (panel): {_m(s.get('pnl_usd'))} US$ / {_m(s.get('pnl_mxn'))} MXN "
                 f"(patrimonio {s.get('equity_usd')}, corte {s.get('as_of_utc')}).")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=("alerts", "weekly"))
    p.add_argument("snapshot", type=pathlib.Path)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    snap = json.loads(a.snapshot.read_text(encoding="utf-8"))
    if a.mode == "alerts":
        found = alerts(snap)
        print("\n".join(found) if found else "Sin alertas.")
        sys.exit(1 if found else 0)
    w = weekly(snap)
    print(json.dumps(w, ensure_ascii=False, indent=1) if a.json else markdown(w))


if __name__ == "__main__":
    main()
