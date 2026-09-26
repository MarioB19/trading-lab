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
from collections import defaultdict, deque
from pathlib import Path

import pandas as pd

from .data import ROOT

STATE = ROOT / "state"


def fifo(trades: pd.DataFrame, prices: dict[str, dict[str, float]]) -> dict:
    """trades: columnas sleeve, asset, side, qty, price, fee, candle, status.
    prices: {sleeve: {asset: último precio}} para valuar lo abierto."""
    t = trades[trades["status"].isin(["filled", "partial"])].copy()
    t["qty"] = t["qty"].astype(float)
    t["price"] = t["price"].astype(float)
    t["fee"] = t["fee"].astype(float)
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
    open_pos = []
    for (sleeve, asset), dq in lots.items():
        qty = sum(l[0] for l in dq)
        if qty <= 1e-12:
            continue
        cost = sum(l[0] * (l[1] + l[2]) for l in dq)
        px = prices.get(sleeve, {}).get(asset)
        value = qty * px if px else None
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
        "unrealized_pnl": round(float(o["pnl"].dropna().sum()), 2) if len(o) else 0.0,
    }
    s["total_pnl"] = round(s["realized_pnl"] + s["unrealized_pnl"], 2)
    s.update(res.get("costs", {}))
    by = {}
    for sleeve in sorted(set(c.get("sleeve", pd.Series(dtype=str))) | set(o.get("sleeve", pd.Series(dtype=str)))):
        cs = c[c["sleeve"] == sleeve] if len(c) else c
        os_ = o[o["sleeve"] == sleeve] if len(o) else o
        by[sleeve] = {"closed_lots": int(len(cs)), "wins": int((cs["pnl"] > 0).sum()) if len(cs) else 0,
                      "realized_pnl": round(float(cs["pnl"].sum()), 2) if len(cs) else 0.0,
                      "unrealized_pnl": round(float(os_["pnl"].dropna().sum()), 2) if len(os_) else 0.0}
    s["by_sleeve"] = by
    return s


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
    print(f"Abiertas: {s['open_positions']} · van ganando {s['open_winning']} · van perdiendo {s['open_losing']} · "
          f"resultado no realizado ${s['unrealized_pnl']:+.2f}")
    for p in sorted(a["open"], key=lambda x: -(x["pnl"] or 0)):
        print(f"  {p['sleeve']:7s} {p['asset']:5s} costo ${p['cost']:8.2f} → ${p['value'] or 0:8.2f}  "
              f"({(p['ret'] or 0):+.2%})  desde {p['since']}")


if __name__ == "__main__":
    main()
