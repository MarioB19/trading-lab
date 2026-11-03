"""Sombra de ejecución (H7c): cotiza las órdenes del piloto en otros exchanges sin tocar la ejecución.

Preregistro: `reports/h7c_sombra_exchanges_preregistro.md`. Justo antes de que el piloto envíe una orden cripto
a Bitso, se lee el libro público del mismo activo contra USDT en Binance y OKX y se recorre para el mismo lado e
importe. Una vez por ciclo diario (y una vez al arrancar, como sondeo de acceso) se cotiza además un panel de US$100
por moneda en Bitso, Binance y OKX.

Reglas: solo libros públicos (sin llaves), sesión HTTP propia, tiempo máximo por libro y nada de excepciones hacia
afuera. Una cotización que falla se registra con su error; la orden del piloto sigue igual.
"""
from __future__ import annotations

import math
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

USER_AGENT = "trading-lab-shadow/1.0"
TIMEOUT_S = 8.0
LEVELS = 100
# Comisión taker del nivel más bajo (preregistro H7c). Binance: 0.10%, 0.075% pagando con BNB. OKX: 0.10%.
FEES = {"binance": {"taker": 0.001, "taker_bnb": 0.00075}, "okx": {"taker": 0.001}, "bitso": {"taker": 0.0036}}
# Fin de la ventana preregistrada: 1-dic-2026 18:00 CDMX; extensión máxima al 29-dic-2026 si faltan órdenes.
WINDOW_END_UTC = "2026-12-02 00:00"
WINDOW_MAX_UTC = "2026-12-30 00:00"
MIN_ORDERS = 20
THRESHOLD_BPS = 25.0
MIN_AVAILABILITY = 0.95


def _levels(rows, price_key=0, qty_key=1):
    out = []
    for row in rows or []:
        px, q = float(row[price_key]), float(row[qty_key])
        if math.isfinite(px) and math.isfinite(q) and px > 0 and q > 0:
            out.append((px, q))
    return out


def fetch_binance(session, asset: str) -> dict:
    r = session.get("https://data-api.binance.vision/api/v3/depth",
                    params={"symbol": f"{asset}USDT", "limit": LEVELS}, timeout=TIMEOUT_S)
    r.raise_for_status()
    data = r.json()
    return {"bids": _levels(data.get("bids")), "asks": _levels(data.get("asks"))}


def fetch_okx(session, asset: str) -> dict:
    r = session.get("https://www.okx.com/api/v5/market/books",
                    params={"instId": f"{asset}-USDT", "sz": LEVELS}, timeout=TIMEOUT_S)
    r.raise_for_status()
    data = r.json()
    if str(data.get("code")) != "0" or not data.get("data"):
        raise ValueError(f"okx code {data.get('code')}")
    book = data["data"][0]
    return {"bids": _levels(book.get("bids")), "asks": _levels(book.get("asks"))}


def fetch_bitso(session, asset: str) -> dict:
    r = session.get("https://api.bitso.com/v3/order_book/",
                    params={"book": f"{asset.lower()}_usd", "aggregate": "true"}, timeout=TIMEOUT_S)
    r.raise_for_status()
    payload = r.json().get("payload") or {}
    pick = lambda rows: [(x["price"], x["amount"]) for x in rows or []]  # noqa: E731
    return {"bids": _levels(pick(payload.get("bids"))), "asks": _levels(pick(payload.get("asks")))}


FETCHERS = {"binance": fetch_binance, "okx": fetch_okx, "bitso": fetch_bitso}


def walk(book: dict, side: str, usd: float) -> dict:
    """Recorre el libro para `usd` dólares (o USDT) del lado pedido. Costo contra el medio del propio libro."""
    bids = sorted(book["bids"], key=lambda x: -x[0])
    asks = sorted(book["asks"], key=lambda x: x[0])
    if not bids or not asks:
        raise ValueError("libro vacío")
    bid, ask = bids[0][0], asks[0][0]
    if ask <= bid:
        raise ValueError("libro cruzado")
    mid = (bid + ask) / 2
    got = cost = 0.0
    for px, q in (asks if side == "buy" else bids):
        need = usd - cost
        if need <= 1e-9:
            break
        take = min(q, need / px)
        got += take
        cost += take * px
    if got <= 0:
        raise ValueError("sin profundidad")
    avg = cost / got
    sign = 1 if side == "buy" else -1
    return {"mid": mid, "spread_bps": (ask - bid) / mid * 1e4, "impact_bps": (avg / mid - 1) * sign * 1e4,
            "filled_usd": cost, "depth_ok": cost >= usd * 0.999}


def quote(venue: str, asset: str, side: str, usd: float, *, session, ref_price: float | None = None,
          clock=time.monotonic) -> dict:
    """Una cotización. Nunca lanza: los errores quedan en `status`."""
    start = clock()
    row = {"venue": venue, "asset": asset, "side": side, "usd": round(float(usd), 2)}
    try:
        res = walk(FETCHERS[venue](session, asset), side, float(usd))
        row.update(status="ok", mid=res["mid"], spread_bps=round(res["spread_bps"], 3),
                   impact_bps=round(res["impact_bps"], 3), filled_usd=round(res["filled_usd"], 2),
                   depth_ok=res["depth_ok"],
                   cost_bps={name: round(res["impact_bps"] + fee * 1e4, 3) for name, fee in FEES[venue].items()})
        if ref_price:
            row["mid_gap_bps"] = round((res["mid"] / float(ref_price) - 1) * 1e4, 3)
    except Exception as exc:  # noqa: BLE001  la sombra nunca rompe el ciclo
        status = getattr(getattr(exc, "response", None), "status_code", None)
        row.update(status="error", error=(f"http {status}" if status else type(exc).__name__)[:80])
    row["latency_ms"] = round((clock() - start) * 1000)
    return row


def _session():
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    s.trust_env = True
    return s


class ExchangeShadow:
    """Cotizaciones sombra de un ciclo. `orders` y `panels` se guardan como eventos al final de la corrida."""

    def __init__(self, cfg: dict | None = None, session=None):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled"))
        self.venues = [v for v in cfg.get("venues", ["binance", "okx"]) if v in FETCHERS and v != "bitso"]
        self.panel_usd = float(cfg.get("panel_usd", 100.0))
        self.panel_budget_s = float(cfg.get("panel_budget_s", 90.0))
        self.session = session
        self.orders: list[dict] = []
        self.panels: list[dict] = []

    def _s(self):
        if self.session is None:
            self.session = _session()
        return self.session

    def before_order(self, sleeve: str, run_at: str, asset: str, side: str, qty: float, ref_price: float) -> None:
        """Cotiza la orden en cada venue, en paralelo, antes de que el piloto la mande a Bitso."""
        try:
            usd = float(qty) * float(ref_price)
            observed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            with ThreadPoolExecutor(max_workers=max(1, len(self.venues))) as pool:
                quotes = list(pool.map(lambda v: quote(v, asset, side, usd, session=self._s(), ref_price=ref_price),
                                       self.venues))
            self.orders.append({"run_at_utc": run_at, "observed_utc": observed, "sleeve": sleeve, "asset": asset,
                                "side": side, "usd": round(usd, 2), "ref_price": float(ref_price), "quotes": quotes})
        except Exception as exc:  # noqa: BLE001
            self.orders.append({"run_at_utc": run_at, "sleeve": sleeve, "asset": asset, "side": side,
                                "status": "error", "error": type(exc).__name__})

    def panel(self, run_at: str, universe, trigger: str = "cycle", clock=time.monotonic) -> dict:
        """US$100 de compra y de venta por moneda en Bitso y en cada venue, con presupuesto de tiempo."""
        observed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        deadline = clock() + self.panel_budget_s
        rows: list[dict] = []
        try:
            def one_venue(venue):
                out = []
                for asset in universe:
                    if clock() > deadline:
                        out.append({"venue": venue, "asset": asset, "status": "skipped", "error": "presupuesto"})
                        continue
                    try:
                        book = FETCHERS[venue](self._s(), asset)
                        for side in ("buy", "sell"):
                            res = walk(book, side, self.panel_usd)
                            out.append({"venue": venue, "asset": asset, "side": side, "status": "ok",
                                        "mid": res["mid"], "spread_bps": round(res["spread_bps"], 3),
                                        "impact_bps": round(res["impact_bps"], 3), "depth_ok": res["depth_ok"]})
                    except Exception as exc:  # noqa: BLE001
                        status = getattr(getattr(exc, "response", None), "status_code", None)
                        out.append({"venue": venue, "asset": asset, "status": "error",
                                    "error": (f"http {status}" if status else type(exc).__name__)[:80]})
                return out

            with ThreadPoolExecutor(max_workers=1 + len(self.venues)) as pool:
                for out in pool.map(one_venue, ["bitso", *self.venues]):
                    rows += out
        except Exception as exc:  # noqa: BLE001
            rows.append({"status": "error", "error": type(exc).__name__})
        panel = {"run_at_utc": run_at, "observed_utc": observed, "trigger": trigger, "usd": self.panel_usd,
                 "rows": rows}
        self.panels.append(panel)
        return panel


# ------------------------------------------------------------------ lectura y veredicto (preregistro H7c)
def _weighted(pairs):
    tot = sum(w for _, w in pairs)
    return sum(x * w for x, w in pairs) / tot if tot > 0 else None


def summarize(orders: list[dict], trades: list[dict], panels: list[dict] | None = None, *,
              now_utc: str | None = None, reps: int = 10000, seed: int = 20261103) -> dict:
    """Une cada cotización sombra con la operación real del piloto y aplica la regla preregistrada."""
    now_utc = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    real = {}
    for t in trades:
        if t.get("sleeve") != "crypto" or t.get("status") not in ("filled", "partial"):
            continue
        try:
            value, cost = float(t["value"]), float(t["cost_bps"])
        except (KeyError, TypeError, ValueError):
            continue
        if value > 0 and math.isfinite(cost):
            real[(t.get("run_at_utc"), t.get("asset"), t.get("side"))] = (value, cost)
    venues = sorted({q["venue"] for o in orders for q in o.get("quotes", [])})
    first = min((o["run_at_utc"] for o in orders if o.get("run_at_utc")), default=None)
    calendar_days = 1.0
    if first:
        try:
            span = datetime.strptime(now_utc[:16], "%Y-%m-%d %H:%M") - datetime.strptime(first[:16], "%Y-%m-%d %H:%M")
            calendar_days = max(1.0, span.total_seconds() / 86400)
        except ValueError:
            pass
    out = {"window": {"from_utc": first, "end_utc": WINDOW_END_UTC, "max_utc": WINDOW_MAX_UTC,
                      "now_utc": now_utc, "min_orders": MIN_ORDERS, "threshold_bps": THRESHOLD_BPS},
           "orders_recorded": len(orders), "panels_recorded": len(panels or []), "venues": {}}
    for venue in venues:
        quotes = [q for o in orders for q in o.get("quotes", []) if q["venue"] == venue]
        quotes += [r for p in panels or [] for r in p.get("rows", []) if r.get("venue") == venue
                   and r.get("side", "buy") == "buy"]
        ok = sum(1 for q in quotes if q.get("status") == "ok")
        availability = ok / len(quotes) if quotes else None
        fee_names = sorted(FEES[venue]) if venue in FEES else []
        by_fee = {}
        for fee in fee_names:
            pairs, days = [], {}
            for o in orders:
                key = (o.get("run_at_utc"), o.get("asset"), o.get("side"))
                q = next((q for q in o.get("quotes", []) if q["venue"] == venue), None)
                if key not in real or not q or q.get("status") != "ok" or not q.get("depth_ok"):
                    continue
                value, bitso_cost = real[key]
                diff = bitso_cost - q["cost_bps"][fee]
                pairs.append((diff, value))
                days.setdefault(str(key[0])[:10], []).append((diff, value))
            mean = _weighted(pairs)
            lo = hi = None
            if len(days) >= 2:
                rng = random.Random(seed)
                groups = list(days.values())
                boots = sorted(_weighted([p for _ in groups for p in rng.choice(groups)]) for _ in range(reps))
                lo, hi = boots[int(0.05 * reps)], boots[int(0.95 * reps) - 1]
            value_total = sum(w for _, w in pairs)
            by_fee[fee] = {"n_orders": len(pairs), "n_days": len(days), "value_usd": round(value_total, 2),
                           "mean_diff_bps": None if mean is None else round(mean, 2),
                           "ci90_bps": None if lo is None else [round(lo, 2), round(hi, 2)],
                           "saving_usd": None if mean is None else round(mean / 1e4 * value_total, 2),
                           "saving_usd_per_year": None if mean is None else
                           round(mean / 1e4 * value_total * 365 / calendar_days, 2)}
        verdict = _verdict(venue, by_fee, availability, now_utc)
        out["venues"][venue] = {"availability": None if availability is None else round(availability, 4),
                                "quotes": len(quotes), "by_fee": by_fee, "verdict": verdict}
    return out


def _verdict(venue, by_fee, availability, now_utc) -> str:
    main = by_fee.get("taker_bnb" if venue == "binance" else "taker") or {}
    n = main.get("n_orders", 0)
    if now_utc < WINDOW_END_UTC or (n < MIN_ORDERS and now_utc < WINDOW_MAX_UTC):
        return "en curso"
    if availability is None or availability < MIN_AVAILABILITY:
        return "no medible desde el servidor"
    if n < MIN_ORDERS:
        return "falta dato"
    ci = main.get("ci90_bps")
    if not ci or ci[0] <= THRESHOLD_BPS:
        return "sin ventaja clara"
    if venue == "binance":
        plain = (by_fee.get("taker") or {}).get("ci90_bps")
        return "ventaja medida, robusta a la comisión" if plain and plain[0] > THRESHOLD_BPS else "ventaja medida (solo con BNB)"
    return "ventaja medida"
