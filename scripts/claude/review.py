#!/usr/bin/env python3
"""Revisión del piloto a partir de un snapshot de `tl.py` (solo biblioteca estándar).

Uso:
  review.py alerts   SNAPSHOT.json            # salud y kill switches; código 1 si hay alertas
  review.py weekly   SNAPSHOT.json [--end YYYY-MM-DD] [--days 7] [--json]

Atribución semanal por bloque, con flujos de capital excluidos:
  resultado = mercado + estrategia − costos
  mercado    = Σ días beta × rendimiento diario de la referencia × patrimonio del día anterior
               (beta de los últimos 90 cierres; referencia = `benchmark_price` del propio bot:
                BTC para cripto, SPY para ETFs)
  costos     = comisión + diferencia contra el precio de referencia (`cost_bps` × importe);
               si falta `cost_bps`, solo la comisión
  estrategia = resultado − mercado + costos   (lo que la regla aportó antes de costos)
Las cifras se calculan con los datos del snapshot: no se inventa ningún precio.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import statistics
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


def _returns(rows: list[dict]) -> list[tuple[str, float, float]]:
    """(fecha, rendimiento del bloque sin flujos, rendimiento de la referencia)."""
    out = []
    for a, b in zip(rows, rows[1:]):
        ea, eb = _f(a.get("equity")), _f(b.get("equity"))
        pa, pb = _f(a.get("benchmark_price")), _f(b.get("benchmark_price"))
        flow = _f(b.get("flow")) or 0.0
        if ea and eb is not None and pa and pb:
            out.append((b["date"], (eb - flow - ea) / ea, pb / pa - 1))
    return out


def beta(rets: list[tuple[str, float, float]], end: str, n: int = 90) -> tuple[float | None, int]:
    pts = [(r, m) for d, r, m in rets if d <= end][-n:]
    pts = [(r, m) for r, m in pts if m != 0 or r != 0]  # días sin cierre (ETF en fin de semana)
    if len(pts) < 10:
        return None, len(pts)
    rs, ms = [p[0] for p in pts], [p[1] for p in pts]
    var = statistics.pvariance(ms)
    if var == 0:
        return None, len(pts)
    mr, mm = statistics.fmean(rs), statistics.fmean(ms)
    cov = sum((r - mr) * (m - mm) for r, m in pts) / len(pts)
    return cov / var, len(pts)


def weekly(snap: dict, end: str | None, days: int) -> dict:
    eq = equity_by_sleeve(snap)
    trades = [t for t in (_data(snap, "trades") or {}).get("items", []) if t.get("status") == "filled"]
    perf = _data(snap, "performance") or {}
    fx = _f((perf.get("fx") or {}).get("rate"))
    if end is None:
        end = max((rows[-1]["date"] for rows in eq.values() if rows), default=None)
    if end is None:
        return {"error": "Sin filas de patrimonio en el snapshot."}
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=days)).isoformat()
    result = {"start": start, "end": end, "fx_usd_mxn": fx, "sleeves": {}, "trades": []}
    tot = {"pnl": 0.0, "market": 0.0, "strategy": 0.0, "costs": 0.0, "unattributed": 0.0,
           "start_equity": 0.0, "end_equity": 0.0}
    for sleeve, rows in sorted(eq.items()):
        base = [r for r in rows if r["date"] <= start]
        inside = [r for r in rows if start < r["date"] <= end]
        if not base or not inside:
            result["sleeves"][sleeve] = {"error": "sin cierres suficientes en la ventana"}
            continue
        r0, r1 = base[-1], inside[-1]
        e0, e1 = _f(r0["equity"]), _f(r1["equity"])
        flows = sum(_f(r.get("flow")) or 0.0 for r in inside)
        pnl = e1 - e0 - flows
        p0, p1 = _f(r0.get("benchmark_price")), _f(r1.get("benchmark_price"))
        bench = (p1 / p0 - 1) if p0 and p1 else None
        b, n = beta(_returns(rows), end)
        # Mercado día a día sobre el patrimonio del día anterior: respeta aportaciones y retiros.
        market = None
        if b is not None:
            market, prev = 0.0, r0
            for r in inside:
                pa, pb, ea = _f(prev.get("benchmark_price")), _f(r.get("benchmark_price")), _f(prev.get("equity"))
                if pa and pb and ea:
                    market += b * (pb / pa - 1) * ea
                prev = r
        st_trades = [t for t in trades if t.get("sleeve") == sleeve and start < str(t.get("candle", ""))[:10] <= end]
        costs = 0.0
        for t in st_trades:
            v, bps, fee = _f(t.get("value")) or 0.0, _f(t.get("cost_bps")), _f(t.get("fee")) or 0.0
            costs += max(bps * v / 1e4, fee) if bps is not None else fee
        strategy = pnl - market + costs if market is not None else None
        traded = sum(_f(t.get("value")) or 0.0 for t in st_trades)
        maker = sum(_f(t.get("maker_value_usd")) or 0.0 for t in st_trades)
        result["sleeves"][sleeve] = {
            "start_equity": e0, "end_equity": e1, "flows": flows, "pnl_usd": pnl,
            "pnl_pct": pnl / (e0 + max(flows, 0.0)) if e0 else None, "benchmark_return": bench, "beta": b, "beta_obs": n,
            "market_usd": market, "strategy_usd": strategy, "costs_usd": costs,
            "trades": len(st_trades), "traded_usd": traded,
            "cost_bps_weighted": costs / traded * 1e4 if traded else None,
            "maker_share": maker / traded if traded else None,
            "drawdown": _f(r1.get("drawdown")), "kill_limit": KILL.get(sleeve),
        }
        tot["pnl"] += pnl
        tot["costs"] += costs
        tot["start_equity"] += e0
        tot["end_equity"] += e1
        if market is not None:
            tot["market"] += market
            tot["strategy"] += strategy
        else:  # sin beta confiable: su resultado (ya neto de costos) queda sin atribuir
            tot["unattributed"] += pnl + costs
        result["trades"] += [{k: t.get(k) for k in ("candle", "sleeve", "asset", "side", "value", "fee", "cost_bps")}
                             for t in st_trades]
    result["total"] = tot
    cur = perf.get("current") or {}
    result["since_start"] = {"equity_usd": cur.get("equity_usd"), "pnl_usd": cur.get("pnl_usd"),
                             "pnl_mxn": cur.get("pnl_mxn"), "as_of_utc": cur.get("as_of_utc")}
    return result


def _m(x, pct=False):
    if x is None:
        return "sin dato"
    return f"{x:+.2%}" if pct else f"{x:+,.2f}"


def markdown(w: dict) -> str:
    if "error" in w:
        return w["error"]
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
    lines += ["", f"Total semana: US${t['pnl']:+,.2f}{mxn} = mercado {_m(t['market'])} + estrategia "
                  f"{_m(t['strategy'])}{extra} − costos {t['costs']:,.2f}.",
              f"Desde el inicio: {_m(w['since_start'].get('pnl_usd'))} US$ / {_m(w['since_start'].get('pnl_mxn'))} MXN "
              f"(patrimonio {w['since_start'].get('equity_usd')}, corte {w['since_start'].get('as_of_utc')})."]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=("alerts", "weekly"))
    p.add_argument("snapshot", type=pathlib.Path)
    p.add_argument("--end")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    snap = json.loads(a.snapshot.read_text(encoding="utf-8"))
    if a.mode == "alerts":
        found = alerts(snap)
        print("\n".join(found) if found else "Sin alertas.")
        sys.exit(1 if found else 0)
    w = weekly(snap, a.end, a.days)
    print(json.dumps(w, ensure_ascii=False, indent=1) if a.json else markdown(w))


if __name__ == "__main__":
    main()
