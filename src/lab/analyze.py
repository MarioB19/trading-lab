"""Análisis de operaciones: cuántas se hicieron, cuáles ganan y cuáles pierden.

    python -m lab.analyze            # imprime el resumen y escribe state/analysis.json

Empareja compras y ventas por activo con el método FIFO (lo primero que se compra es lo
primero que se vende, como lo pide el SAT). Cada venta cierra uno o más "lotes":
  * ganancia REALIZADA: lotes ya vendidos, con comisiones de compra y venta incluidas.
  * ganancia NO REALIZADA: lo que sigue abierto, valuado al último cierre del bot.

Una operación "ganadora" es un lote cerrado con ganancia neta positiva. Las posiciones
abiertas se reportan aparte: su resultado todavía puede cambiar.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from pathlib import Path

import pandas as pd

from .data import ROOT

STATE = ROOT / "state"
TRADE_COLUMNS = ["sleeve", "asset", "side", "qty", "price", "fee", "candle", "status"]


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def fifo(trades: pd.DataFrame, prices: dict[str, dict[str, float]]) -> dict:
    """trades: columnas sleeve, asset, side, qty, price, fee, candle, status.
    prices: {sleeve: {asset: último precio}} para valuar lo abierto."""
    t = trades[trades["status"].isin(["filled", "partial"])].copy()
    t["qty"] = t["qty"].astype(float)
    t["price"] = t["price"].astype(float)
    t["fee"] = t["fee"].astype(float)
    if any(not math.isfinite(x) for x in t[["qty", "price", "fee"]].to_numpy().flat) or (
            (t["qty"] <= 0).any() or (t["price"] <= 0).any() or (t["fee"] < 0).any()
            or not t["side"].isin(["buy", "sell"]).all()):
        raise ValueError("Operaciones ejecutadas con cantidades, precios, comisiones o lados inválidos")
    # The append order resolves equal timestamps. Never let an out-of-order import
    # consume a later purchase to cover a sale whose cost basis is unknown.
    if len(t):
        dates = t["run_at_utc"] if "run_at_utc" in t else t["candle"]
        ordered = pd.to_datetime(dates, utc=True, errors="coerce", format="mixed")
        if ordered.isna().any():
            raise ValueError("Operaciones sin fecha verificable para ordenar el FIFO")
        t = t.assign(_order=ordered).sort_values("_order", kind="stable")
    quantity_tolerances = t.groupby(["sleeve", "asset"]).size() * 5e-9 + 1e-12
    lots: dict[tuple, deque] = defaultdict(deque)
    closed = []
    for _, r in t.iterrows():
        key = (r["sleeve"], r["asset"])
        if r["side"] == "buy":
            # costo por unidad incluyendo la comisión de compra
            lots[key].append([r["qty"], r["price"], r["fee"] / r["qty"] if r["qty"] else 0.0, r["candle"]])
            continue
        remaining, fee_per = r["qty"], (r["fee"] / r["qty"] if r["qty"] else 0.0)
        while remaining > 1e-12 and lots[key]:
            lot = lots[key][0]
            q = min(remaining, lot[0])
            cost = q * (lot[1] + lot[2])
            proceeds = q * (r["price"] - fee_per)
            closed.append({"sleeve": r["sleeve"], "asset": r["asset"], "qty": q, "opened": lot[3],
                           "closed": r["candle"], "buy_price": lot[1], "sell_price": r["price"],
                           "pnl": proceeds - cost, "ret": proceeds / cost - 1 if cost else 0.0})
            lot[0] -= q
            remaining -= q
            if lot[0] <= 1e-12:
                lots[key].popleft()
        # Legacy exports record quantity to 8 decimals. Only that accumulated
        # rounding bound is allowed; an unmatched sale otherwise has no P&L.
        if remaining > quantity_tolerances[key]:
            raise ValueError(f"Venta sin compra FIFO suficiente: {key[0]}/{key[1]} ({remaining:.10g})")
    open_pos = []
    for (sleeve, asset), dq in lots.items():
        qty = sum(l[0] for l in dq)
        if qty <= 1e-12:
            continue
        cost = sum(l[0] * (l[1] + l[2]) for l in dq)
        px = _number(prices.get(sleeve, {}).get(asset))
        px = px if px is not None and px > 0 else None
        value = qty * px if px is not None else None
        open_pos.append({"sleeve": sleeve, "asset": asset, "qty": qty, "cost": cost, "price": px,
                         "value": value, "pnl": (value - cost) if value is not None else None,
                         "ret": (value / cost - 1) if value is not None and cost else None,
                         "since": dq[0][3]})
    # costo real de ejecución (diferencial + comisión), ponderado por monto, donde se midió
    costs = {}
    if "cost_bps" in t:
        c = t[pd.to_numeric(t["cost_bps"], errors="coerce").notna()].copy()
        if len(c):
            c["cost_bps"] = pd.to_numeric(c["cost_bps"])
            c["value"] = (c["qty"] * c["price"]).abs()
            costs["avg_cost_bps"] = round(float((c["cost_bps"] * c["value"]).sum() / c["value"].sum()), 1)
            costs["cost_bps_by_sleeve"] = {k: round(float((g["cost_bps"] * g["value"]).sum() / g["value"].sum()), 1)
                                           for k, g in c.groupby("sleeve")}
            costs["n_cost_measured"] = int(len(c))
    return {"closed": closed, "open": open_pos, "fees": float(t["fee"].sum()), "costs": costs,
            "n_trades": int(len(t)), "n_buys": int((t["side"] == "buy").sum()),
            "n_sells": int((t["side"] == "sell").sum())}


def summarize(res: dict) -> dict:
    c = pd.DataFrame(res["closed"])
    o = pd.DataFrame(res["open"])
    wins = c[c["pnl"] > 0] if len(c) else c
    losses = c[c["pnl"] <= 0] if len(c) else c
    s = {
        "n_trades": res["n_trades"], "n_buys": res["n_buys"], "n_sells": res["n_sells"],
        "fees": round(res["fees"], 4),
        "closed_lots": int(len(c)), "wins": int(len(wins)), "losses": int(len(losses)),
        "win_rate": round(len(wins) / len(c), 4) if len(c) else None,
        "realized_pnl": round(float(c["pnl"].sum()), 2) if len(c) else 0.0,
        "avg_win": round(float(wins["pnl"].mean()), 2) if len(wins) else None,
        "avg_loss": round(float(losses["pnl"].mean()), 2) if len(losses) else None,
        "profit_factor": (round(float(wins["pnl"].sum() / -losses["pnl"].sum()), 2)
                          if len(losses) and losses["pnl"].sum() < 0 else None),
        "open_positions": int(len(o)),
        "open_winning": int((o["pnl"] > 0).sum()) if len(o) else 0,
        "open_losing": int((o["pnl"] <= 0).sum()) if len(o) else 0,
        "unpriced_positions": int(o["pnl"].isna().sum()) if len(o) else 0,
        "unrealized_pnl": (round(float(o["pnl"].sum()), 2) if o["pnl"].notna().all() else None) if len(o) else 0.0,
    }
    s["total_pnl"] = round(s["realized_pnl"] + s["unrealized_pnl"], 2) if s["unrealized_pnl"] is not None else None
    s.update(res.get("costs", {}))
    by = {}
    for sleeve in sorted(set(c.get("sleeve", pd.Series(dtype=str))) | set(o.get("sleeve", pd.Series(dtype=str)))):
        cs = c[c["sleeve"] == sleeve] if len(c) else c
        os_ = o[o["sleeve"] == sleeve] if len(o) else o
        by[sleeve] = {"closed_lots": int(len(cs)), "wins": int((cs["pnl"] > 0).sum()) if len(cs) else 0,
                      "realized_pnl": round(float(cs["pnl"].sum()), 2) if len(cs) else 0.0,
                      "unrealized_pnl": (round(float(os_["pnl"].sum()), 2) if os_["pnl"].notna().all() else None) if len(os_) else 0.0}
    s["by_sleeve"] = by
    return s


def build_analysis(trades: list[dict], snapshot: dict, state: dict) -> dict:
    """Derive FIFO from one coherent ledger read; never persist or fetch prices.

    P&L uses the explicitly dated snapshot close, not the live valuation. The
    quantity and dollar tolerances account for the bot's rounded trade exports.
    An incomplete ledger or mark remains visible, but never produces a total.
    """
    mode = snapshot.get("mode")
    issues = []
    prices, dates = {}, {}
    sleeves = snapshot.get("sleeves", {})
    selected = [row for row in trades if row.get("mode") == mode]
    t = pd.DataFrame(selected) if selected else pd.DataFrame(columns=TRADE_COLUMNS)
    out = {"source": "sqlite_ledger", "price_source": "snapshot_close", "mode": mode,
           "prices_as_of": dates, "issues": issues, "reconciliation": {"by_sleeve": {}},
           "open": [], "closed": [], "valid": False}
    try:
        if mode not in {"paper", "live"}:
            raise ValueError("Modo del análisis no verificado")
        if any(row.get("status") in {"filled", "partial"} and not row.get("mode") for row in trades):
            raise ValueError("Operaciones ejecutadas sin modo verificable")
        for name, sleeve in sleeves.items():
            if sleeve.get("mode", mode) != mode:
                raise ValueError(f"Modo del precio no coincide con el análisis: {name}")
            candle = sleeve.get("candle")
            dates[name] = candle
            if pd.isna(pd.to_datetime(candle, utc=True, errors="coerce")):
                prices[name] = {}
                continue
            prices[name] = {asset["asset"]: asset.get("price") for asset in sleeve.get("assets", [])}
        res = fifo(t, prices)
        summary = summarize(res)
    except (ValueError, TypeError, KeyError) as exc:
        issues.append({"code": "invalid_ledger", "message": str(exc)})
        out["summary"] = {**summarize(fifo(pd.DataFrame(columns=TRADE_COLUMNS), {})),
                          "n_trades": sum(row.get("status") in {"filled", "partial"} for row in selected),
                          "n_buys": sum(row.get("status") in {"filled", "partial"} and row.get("side") == "buy" for row in selected),
                          "n_sells": sum(row.get("status") in {"filled", "partial"} and row.get("side") == "sell" for row in selected),
                          "fees": None, "realized_pnl": None, "unrealized_pnl": None, "total_pnl": None}
        return out
    out.update(summary=summary, open=res["open"], closed=res["closed"][-100:])
    for position in res["open"]:
        if position["price"] is None:
            issues.append({"code": "missing_price", "sleeve": position["sleeve"], "asset": position["asset"],
                           "message": f"Sin precio de cierre fechado para {position['sleeve']}/{position['asset']}"})
    state_sleeves = state.get("sleeves", {})
    names = set(state_sleeves) | set(t["sleeve"])
    for name in sorted(names):
        st = state_sleeves.get(name, {})
        ledger = st.get("ledger", {})
        positions = ledger.get("positions", {})
        fills = t[(t["sleeve"] == name) & t["status"].isin(["filled", "partial"])]
        opened = {position["asset"]: position for position in res["open"] if position["sleeve"] == name}
        start = len(issues)
        if st.get("mode") != mode or not isinstance(ledger.get("positions"), dict):
            issues.append({"code": "unverified_positions", "sleeve": name,
                           "message": f"Inventario del bloque {name} no verificable en modo {mode}"})
        if len(fills):
            candles = pd.to_datetime(fills["candle"], utc=True, errors="coerce", format="mixed")
            price_date = pd.to_datetime(dates.get(name), utc=True, errors="coerce")
            if candles.isna().any() or pd.isna(price_date) or candles.max() > price_date:
                issues.append({"code": "stale_price_date", "sleeve": name,
                               "message": f"Fecha del cierre de {name} ausente o anterior a las operaciones"})
        quantities = {}
        for asset in sorted(set(positions) | set(opened)):
            actual = _number(positions.get(asset, 0))
            fifo_qty = opened.get(asset, {}).get("qty", 0.0)
            tolerance = int((fills["asset"] == asset).sum()) * 5e-9 + 1e-12
            difference = fifo_qty - actual if actual is not None else None
            matches = difference is not None and abs(difference) <= tolerance
            quantities[asset] = {"fifo_qty": fifo_qty, "ledger_qty": actual, "difference": difference,
                                 "tolerance": tolerance, "matches": matches}
            if not matches:
                issues.append({"code": "position_mismatch", "sleeve": name, "asset": asset,
                               "message": f"Cantidad FIFO no concilia con el inventario: {name}/{asset}"})
        cash, capital = _number(ledger.get("cash")), _number(st.get("capital_base"))
        marked = []
        for asset, quantity in positions.items():
            px = _number(prices.get(name, {}).get(asset))
            qty = _number(quantity)
            marked.append(qty * px if qty is not None and px is not None and px > 0 else None)
        ledger_pnl = cash + sum(marked) - capital if cash is not None and capital is not None and all(
            value is not None for value in marked) else None
        own_closed = [lot["pnl"] for lot in res["closed"] if lot["sleeve"] == name]
        own_open = [position["pnl"] for position in opened.values()]
        fifo_pnl = sum(own_closed) + sum(own_open) if all(value is not None for value in own_open) else None
        difference = fifo_pnl - ledger_pnl if fifo_pnl is not None and ledger_pnl is not None else None
        # Fees are exported to 4 decimals; prices to 6; quantities to 8.
        tolerance = .01 + len(fills) * .00005 + float(fills["qty"].astype(float).sum()) * .0000005
        tolerance += sum(item["tolerance"] * (_number(prices.get(name, {}).get(asset)) or 0)
                         for asset, item in quantities.items())
        if difference is None or abs(difference) > tolerance:
            issues.append({"code": "pnl_mismatch", "sleeve": name,
                           "message": f"Resultado FIFO de {name} no conciliado con efectivo, inventario y aportaciones"})
        out["reconciliation"]["by_sleeve"][name] = {
            "valid": len(issues) == start, "quantities": quantities, "fifo_pnl": fifo_pnl,
            "ledger_pnl": ledger_pnl, "difference": difference, "tolerance_usd": tolerance}
    if issues:
        # An invalid global summary must not masquerade as a complete account P&L.
        summary["total_pnl"] = None
        for issue in issues:
            if issue["code"] in {"stale_price_date", "unverified_positions", "position_mismatch", "pnl_mismatch"}:
                summary["unrealized_pnl"] = None
                if issue.get("sleeve") in summary["by_sleeve"]:
                    summary["by_sleeve"][issue["sleeve"]]["unrealized_pnl"] = None
    out["valid"] = not issues
    return out


def run(write: bool = True) -> dict:
    trades = pd.read_csv(STATE / "trades.csv") if (STATE / "trades.csv").exists() else pd.DataFrame(
        columns=["sleeve", "asset", "side", "qty", "price", "fee", "candle", "status"])
    snap = json.loads((STATE / "snapshot.json").read_text()) if (STATE / "snapshot.json").exists() else {}
    prices = {n: {a["asset"]: a.get("price") for a in s.get("assets", []) if a.get("price")}
              for n, s in snap.get("sleeves", {}).items()}
    mode = snap.get("mode", "paper")
    if len(trades) and "mode" in trades:
        trades = trades[trades["mode"] == mode]
    res = fifo(trades, prices)
    out = {"summary": summarize(res), "open": res["open"], "closed": res["closed"][-100:],
           "prices_as_of": {n: s.get("candle") for n, s in snap.get("sleeves", {}).items()}}
    if write:
        (STATE / "analysis.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def main() -> None:
    a = run()
    s = a["summary"]
    print(f"Operaciones: {s['n_trades']} ({s['n_buys']} compras, {s['n_sells']} ventas) · comisiones ${s['fees']:.2f}")
    if s["closed_lots"]:
        print(f"Cerradas: {s['closed_lots']} · ganadoras {s['wins']} · perdedoras {s['losses']} · "
              f"tasa de acierto {s['win_rate']:.0%} · resultado realizado ${s['realized_pnl']:+.2f}")
    else:
        print("Cerradas: 0 (todavía no se ha vendido nada; no hay ganadoras ni perdedoras definitivas)")
    unrealized = f"${s['unrealized_pnl']:+.2f}" if s["unrealized_pnl"] is not None else "no disponible (faltan precios)"
    print(f"Abiertas: {s['open_positions']} · van ganando {s['open_winning']} · van perdiendo {s['open_losing']} · "
          f"resultado no realizado {unrealized}")
    for p in sorted(a["open"], key=lambda x: -(x["pnl"] or 0)):
        value = f"${p['value']:8.2f} ({p['ret']:+.2%})" if p["value"] is not None else "sin precio"
        print(f"  {p['sleeve']:7s} {p['asset']:5s} costo ${p['cost']:8.2f} → {value}  desde {p['since']}")


if __name__ == "__main__":
    main()
