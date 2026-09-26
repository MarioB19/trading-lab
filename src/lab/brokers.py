"""Brokers: dónde se ejecutan las órdenes.

  SimBroker     simulado interno (sin dinero real, sin llaves). Default.
  AlpacaBroker  acciones/ETFs en Alpaca: paper (gratis, sin dinero real) o real.
  BitsoBroker   criptos en Bitso, pares contra USD. Solo en modo real.

Todos exponen la misma interfaz: cash(), positions(), execute(asset, side, qty, ref_price).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests


@dataclass
class Fill:
    asset: str
    side: str
    qty: float
    price: float
    fee: float
    status: str = "filled"   # filled | submitted (se llenará al abrir el mercado) | partial | failed
    note: str = ""
    ref: float = 0.0         # precio de referencia justo antes de ejecutar (medio del libro o cierre)


class SimBroker:
    def __init__(self, ledger: dict, fee: float, slippage: float, min_order_value: float = 1.0):
        self.l = ledger
        self.l.setdefault("positions", {})
        self.fee, self.slip, self.min_order_value = fee, slippage, min_order_value
        self.name = "simulado"

    def cash(self) -> float:
        return float(self.l["cash"])

    def positions(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.l["positions"].items() if abs(v) > 1e-12}

    def pending(self) -> int:
        return 0

    def _apply(self, asset: str, side: str, qty: float, px: float) -> tuple[float, float]:
        """Mueve efectivo y posición en el libro contable. Devuelve (cantidad, comisión)."""
        pos = self.l["positions"]
        if side == "sell":
            qty = min(qty, pos.get(asset, 0.0))
        notional = qty * px
        fee = notional * self.fee
        if side == "buy":
            self.l["cash"] -= notional + fee
            pos[asset] = pos.get(asset, 0.0) + qty
        else:
            self.l["cash"] += notional - fee
            pos[asset] = pos.get(asset, 0.0) - qty
            if pos[asset] <= 1e-12:
                pos.pop(asset)
        return qty, fee

    def execute(self, asset: str, side: str, qty: float, ref_price: float) -> Fill:
        px = ref_price * (1 + self.slip if side == "buy" else 1 - self.slip)
        qty, fee = self._apply(asset, side, qty, px)
        return Fill(asset, side, qty, px, fee, ref=ref_price)


class BookSimBroker(SimBroker):
    """Simulado contra el libro de órdenes REAL de Bitso en el momento de operar.

    Usa la comisión real, el diferencial real y la profundidad real: si no hay suficiente
    oferta a buen precio, la orden se llena más cara o solo en parte, como pasaría con dinero.
    El dinero sigue siendo ficticio.
    """

    def __init__(self, ledger: dict, taker_fee: float, quote: str = "USD", min_order_value: float = 1.0,
                 fallback_slippage: float = 0.002, exchange=None):
        super().__init__(ledger, taker_fee, fallback_slippage, min_order_value)
        if exchange is None:
            from .data import make_exchange

            exchange = make_exchange("bitso")
        self.ex = exchange
        self.ex.load_markets()
        self.quote = quote
        self.name = "simulado · libro real de Bitso"

    def asset_info(self, asset: str) -> dict:
        m = self.ex.markets.get(f"{asset}/{self.quote}")
        return {"tradable": bool(m) and m.get("active") is not False, "fractionable": True}

    def execute(self, asset: str, side: str, qty: float, ref_price: float) -> Fill:
        sym = f"{asset}/{self.quote}"
        m = self.ex.markets.get(sym)
        if not m:
            return Fill(asset, side, 0.0, ref_price, 0.0, "failed", "Bitso no tiene este mercado", ref_price)
        if side == "sell":
            qty = min(qty, self.l["positions"].get(asset, 0.0))
        try:
            qty = float(self.ex.amount_to_precision(sym, qty))
            book = self.ex.fetch_order_book(sym, limit=100)
        except Exception as exc:  # noqa: BLE001  sin libro: deslizamiento supuesto
            f = super().execute(asset, side, qty, ref_price)
            f.note = f"libro no disponible, se supuso {self.slip:.2%} ({str(exc)[:60]})"
            return f
        if not book["bids"] or not book["asks"]:
            return Fill(asset, side, 0.0, ref_price, 0.0, "failed", "libro vacío", ref_price)
        mid = (book["bids"][0][0] + book["asks"][0][0]) / 2
        got = cost = 0.0
        for px, q in (book["asks"] if side == "buy" else book["bids"]):
            take = min(q, qty - got)
            got += take
            cost += take * px
            if got >= qty - 1e-12:
                break
        min_cost = ((m.get("limits") or {}).get("cost") or {}).get("min") or 0.0
        if got <= 0 or cost < min_cost:
            return Fill(asset, side, 0.0, mid, 0.0, "failed", f"debajo del mínimo de Bitso (${min_cost})", mid)
        avg = cost / got
        got, fee = self._apply(asset, side, got, avg)
        status = "filled" if got >= qty * 0.999 else "partial"
        return Fill(asset, side, got, avg, fee, status, "" if status == "filled" else "profundidad insuficiente", mid)


class AlpacaBroker:
    """API REST de Alpaca. Órdenes a mercado 'day': si el mercado está cerrado se ejecutan al abrir."""

    def __init__(self, paper: bool = True, min_order_value: float = 1.0):
        self.key = os.environ.get("ALPACA_KEY_ID", "")
        self.secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not self.key or not self.secret:
            raise RuntimeError("faltan ALPACA_KEY_ID / ALPACA_SECRET_KEY")
        self.base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        self.min_order_value = min_order_value
        self.name = "alpaca paper" if paper else "alpaca real"

    def _req(self, method: str, path: str, **kw):
        h = {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret}
        r = requests.request(method, self.base + path, headers=h, timeout=30, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Alpaca {method} {path}: {r.status_code} {r.text[:200]}")
        return r.json() if r.text else {}

    def cash(self) -> float:
        return float(self._req("GET", "/v2/account")["cash"])

    def positions(self) -> dict[str, float]:
        return {p["symbol"]: float(p["qty"]) for p in self._req("GET", "/v2/positions")
                if abs(float(p["qty"])) > 1e-9}

    def asset_info(self, symbol: str) -> dict:
        """¿Tu cuenta puede operar este ETF, y en fracciones?"""
        if not hasattr(self, "_info"):
            self._info = {}
        if symbol not in self._info:
            try:
                a = self._req("GET", f"/v2/assets/{symbol}")
                self._info[symbol] = {"tradable": bool(a.get("tradable")), "fractionable": bool(a.get("fractionable"))}
            except RuntimeError:
                self._info[symbol] = {"tradable": False, "fractionable": False}
        return self._info[symbol]

    def pending(self) -> int:
        """Órdenes de la corrida anterior que aún esperan la apertura del mercado."""
        return len(self._req("GET", "/v2/orders", params={"status": "open"}))

    def execute(self, asset: str, side: str, qty: float, ref_price: float) -> Fill:
        body = {"symbol": asset, "qty": f"{qty:.6f}", "side": side, "type": "market", "time_in_force": "day"}
        try:
            o = self._req("POST", "/v2/orders", json=body)
        except RuntimeError as exc:
            return Fill(asset, side, 0.0, ref_price, 0.0, "failed", str(exc))
        status = "filled" if o.get("status") == "filled" else "submitted"
        return Fill(asset, side, qty, float(o.get("filled_avg_price") or ref_price), 0.0, status,
                    f"orden {o.get('id', '')[:8]}", ref_price)


class BitsoBroker:
    """Bitso vía ccxt, pares ASSET/USD. Órdenes límite agresivas con tope de precio."""

    def __init__(self, quote: str = "USD", limit_offset: float = 0.004, timeout_s: int = 20,
                 min_order_value: float = 1.0):
        from .data import make_exchange

        self.ex = make_exchange("bitso", os.environ.get("BITSO_API_KEY"), os.environ.get("BITSO_API_SECRET"))
        if not self.ex.apiKey:
            raise RuntimeError("faltan BITSO_API_KEY / BITSO_API_SECRET")
        self.ex.load_markets()
        self.quote, self.offset, self.timeout = quote, limit_offset, timeout_s
        self.min_order_value = min_order_value
        self.name = "bitso real"

    def cash(self) -> float:
        return float(self.ex.fetch_balance()["free"].get(self.quote, 0) or 0)

    def positions(self) -> dict[str, float]:
        tot = self.ex.fetch_balance()["total"]
        return {k: float(v) for k, v in tot.items() if k != self.quote and v and float(v) > 0
                and f"{k}/{self.quote}" in self.ex.markets}

    def pending(self) -> int:
        return 0  # las órdenes que no se llenan en segundos se cancelan

    def price(self, asset: str) -> float:
        t = self.ex.fetch_ticker(f"{asset}/{self.quote}")
        return float(t.get("last") or t["close"])

    def execute(self, asset: str, side: str, qty: float, ref_price: float) -> Fill:
        sym = f"{asset}/{self.quote}"
        try:
            t = self.ex.fetch_ticker(sym)
            top = float(t["ask"] if side == "buy" else t["bid"])
            mid = (float(t["ask"]) + float(t["bid"])) / 2
            limit = top * (1 + self.offset) if side == "buy" else top * (1 - self.offset)
            amount = float(self.ex.amount_to_precision(sym, qty))
            limit = float(self.ex.price_to_precision(sym, limit))
            o = self.ex.create_order(sym, "limit", side, amount, limit)
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                o = self.ex.fetch_order(o["id"], sym)
                if o.get("status") in ("closed", "canceled"):
                    break
                time.sleep(2)
            if o.get("status") == "open":
                self.ex.cancel_order(o["id"], sym)
                o = self.ex.fetch_order(o["id"], sym)
        except Exception as exc:  # noqa: BLE001
            return Fill(asset, side, 0.0, ref_price, 0.0, "failed", str(exc)[:200])
        filled = float(o.get("filled") or 0)
        fee = o.get("fee") or {}
        return Fill(asset, side, filled, float(o.get("average") or limit),
                    float(fee.get("cost") or 0) if fee.get("currency") == self.quote else 0.0,
                    "filled" if filled >= amount * 0.999 else ("partial" if filled else "failed"), "", mid)
