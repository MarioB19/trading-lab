"""Atribución del resultado del piloto: mercado + estrategia − costos (una sola fórmula).

La usan el panel (`/api/attribution`) y la revisión semanal (`scripts/claude/review.py` lee la API),
así que las dos dan la misma cifra. Trasladada sin cambios de método desde `review.py` (25-oct-2026).

  resultado  = mercado + estrategia − costos            (sin contar aportaciones ni retiros)
  mercado    = Σ días beta × rendimiento diario de la referencia × patrimonio del día anterior
               (beta de los últimos 90 cierres; referencia = `benchmark_price` del propio bot:
                BTC para cripto, SPY para ETFs)
  costos     = comisión + diferencia contra el precio de referencia (`cost_bps` × importe);
               si falta `cost_bps`, solo la comisión
  estrategia = resultado − mercado + costos             (lo que la regla aportó antes de costos)

Solo usa las filas de patrimonio y operaciones del bot: no inventa ni descarga precios.
"""
from __future__ import annotations

import datetime as dt
import statistics

KILL = {"crypto": 0.45, "stocks": 0.25}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def equity_by_sleeve(rows: list[dict]) -> dict[str, list[dict]]:
    """Una fila por bloque y fecha de cierre (la última gana), solo simulado."""
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if r.get("mode", "paper") != "paper" or _f(r.get("equity")) is None or not r.get("sleeve"):
            continue
        out.setdefault(r["sleeve"], {})[r["date"]] = r
    return {s: [d[k] for k in sorted(d)] for s, d in out.items()}


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


def attribute(equity_rows: list[dict], trades: list[dict], *, end: str | None = None,
              days: int | None = 7, fx: float | None = None) -> dict:
    """Atribución de la ventana (end − days, end]. Con days=None, desde el primer cierre."""
    eq = equity_by_sleeve(equity_rows)
    filled = [t for t in trades if t.get("status") == "filled"]
    if end is None:
        end = max((rows[-1]["date"] for rows in eq.values() if rows), default=None)
    if end is None:
        return {"error": "Sin filas de patrimonio."}
    if days is None:
        start = min(rows[0]["date"] for rows in eq.values() if rows)
    else:
        start = (dt.date.fromisoformat(end) - dt.timedelta(days=days)).isoformat()
    result = {"start": start, "end": end, "days": days, "fx_usd_mxn": fx, "sleeves": {}, "trades": []}
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
        st_trades = [t for t in filled if t.get("sleeve") == sleeve and start < str(t.get("candle", ""))[:10] <= end]
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
    return result


def windows(equity_rows: list[dict], trades: list[dict], *, end: str | None = None, fx: float | None = None) -> dict:
    """Las tres ventanas del panel: semana, 28 días y desde el primer cierre."""
    return {"week": attribute(equity_rows, trades, end=end, days=7, fx=fx),
            "days_28": attribute(equity_rows, trades, end=end, days=28, fx=fx),
            "since_start": attribute(equity_rows, trades, end=end, days=None, fx=fx),
            "method": "mercado = beta × referencia del bot; costos = comisión + diferencia contra referencia; "
                      "estrategia = resultado − mercado + costos"}
