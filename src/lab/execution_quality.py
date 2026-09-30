"""Read-only execution diagnostics. Costs are simulated, never broker-account fills."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def book_quality(book, side, qty, fee):
    """Estimate cost and visible depth using the book already fetched by execution.

    This function never blocks a trade, fetches data, assumes unseen liquidity,
    or treats a missing/invalid book as zero execution cost.
    """
    if side not in {"buy", "sell"} or not number(qty) or qty <= 0:
        return {}
    bids, asks = book.get("bids", []), book.get("asks", [])
    try:
        if not bids or not asks:
            return {}
        bid, ask = float(bids[0][0]), float(asks[0][0])
        if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
            return {}
        mid = (bid + ask) / 2
        levels = [(float(p), float(q)) for p, q, *_ in (asks if side == "buy" else bids)]
        if any(not (math.isfinite(p) and math.isfinite(q) and p > 0 and q >= 0) for p, q in levels):
            return {}
    except (TypeError, ValueError, IndexError):
        return {}
    filled = cost = visible = 0.0
    for price, amount in levels:
        within = price <= mid * 1.005 if side == "buy" else price >= mid * .995
        if within:
            visible += price * amount
        take = min(amount, max(0.0, qty - filled))
        filled += take
        cost += take * price
    sign = 1 if side == "buy" else -1
    return {"spread_bps": round((ask - bid) / mid * 1e4, 3),
            "visible_depth_usd": round(visible, 4),
            "depth_fill_ratio": round(min(1.0, filled / qty), 6),
            "estimated_taker_cost_bps": round(((cost / filled / mid - 1) * sign + fee) * 1e4, 3)
            if filled > 0 else None}


def _summary(trades):
    valid, measured, structured, waits, liquidity, assumed = [], [], [], [], [], []
    for trade in trades:
        value = number(trade.get("value"))
        if trade.get("status") not in {"filled", "partial"} or value is None or value <= 0:
            continue
        valid.append(trade)
        cost = number(trade.get("cost_bps"))
        source = trade.get("execution_source", "")
        legacy_book = not source and "libro real" in trade.get("broker", "") and "libro no disponible" not in trade.get("note", "")
        if "assumed" in source or "libro no disponible" in trade.get("note", ""):
            assumed.append(trade)
        elif cost is not None and (source == "public_book_simulation" or legacy_book):
            measured.append((value, cost))
        maker, taker = number(trade.get("maker_value_usd")), number(trade.get("taker_value_usd"))
        if maker is not None and taker is not None and maker >= 0 and taker >= 0 and maker + taker > 0:
            structured.append((maker, taker))
        wait = number(trade.get("execution_wait_s"))
        if wait is not None and wait >= 0:
            waits.append(wait)
        spread = number(trade.get("spread_bps"))
        fill = number(trade.get("depth_fill_ratio"))
        if spread is not None or fill is not None:
            liquidity.append(trade)
    basis = sum(value for value, _ in measured)
    maker = sum(m for m, _ in structured)
    taker = sum(t for _, t in structured)
    last_sell, reentries = {}, []
    ordered = sorted((t for t in valid if stamp(t.get("run_at_utc"))), key=lambda t: stamp(t["run_at_utc"]))
    for trade in ordered:
        key = (trade.get("sleeve"), trade.get("mode"), trade.get("asset"))
        time = stamp(trade["run_at_utc"])
        if trade.get("side") == "sell":
            last_sell[key] = time
        elif trade.get("side") == "buy" and key in last_sell:
            hours = (time - last_sell.pop(key)).total_seconds() / 3600
            if 0 < hours <= 48:
                reentries.append({"asset": key[2], "buy_at_utc": time.isoformat(), "hours_since_sale": round(hours, 2)})
    fees = [number(t.get("fee")) for t in valid]
    return {"filled_trades": len(valid), "traded_usd": round(sum(number(t['value']) for t in valid), 2),
            "fees_usd": round(sum(f for f in fees if f is not None), 4) if any(f is not None for f in fees) else None,
            "fees_known_trades": sum(f is not None for f in fees),
            "book_cost_bps": round(sum(v * c for v, c in measured) / basis, 3) if basis else None,
            "book_cost_trades": len(measured), "book_cost_basis_usd": round(basis, 2),
            "assumed_cost_trades": len(assumed),
            "maker_share": maker / (maker + taker) if maker + taker else None,
            "maker_known_trades": len(structured), "maker_basis_usd": round(maker + taker, 4),
            "mean_execution_wait_s": round(sum(waits) / len(waits), 2) if waits else None,
            "liquidity_known_trades": len(liquidity),
            "liquidity_warnings": sum((number(t.get("spread_bps")) or 0) > 50
                                      or (number(t.get("depth_fill_ratio")) is not None
                                          and number(t['depth_fill_ratio']) < .999) for t in liquidity),
            "reentries_48h": reentries,
            "unmeasured_trades": len(valid) - len(measured) - len(assumed)}


def build_execution_quality(trades, *, now=None, days=30):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    eligible = [t for t in trades if t.get("mode") == "paper" and stamp(t.get("run_at_utc")) is not None
                and cutoff <= stamp(t['run_at_utc']) <= now]
    groups = defaultdict(list)
    for trade in eligible:
        groups[trade.get("sleeve", "unknown")].append(trade)
    return {"mode": "paper", "read_only": True, "as_of_utc": now.isoformat(), "window_days": days,
            "total": _summary(eligible), "by_sleeve": {name: _summary(rows) for name, rows in groups.items()},
            "notes": ["Ejecuciones simuladas; el libro público no acredita fills de una cuenta real.",
                      "El costo incluye comisión y diferencia de precio: no sumar las comisiones otra vez.",
                      "Maker sólo usa importes estructurados; los registros antiguos sin dato quedan sin medición.",
                      "Una reentrada en 48 horas es un diagnóstico, no demuestra que mantener hubiera sido mejor."]}
