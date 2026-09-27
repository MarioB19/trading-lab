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

    def _apply(self, asset: str, side: str, qty: float, px: float,
               fee_rate: float | None = None) -> tuple[float, float]:
        """Mueve efectivo y posición en el libro contable. Devuelve (cantidad, comisión)."""
        pos = self.l["positions"]
        if side == "sell":
            qty = min(qty, pos.get(asset, 0.0))
        notional = qty * px
        fee = notional * (self.fee if fee_rate is None else fee_rate)
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
                 fallback_slippage: float = 0.002, exchange=None, maker: dict | None = None,
                 sleep=None, clock=None):
        """maker: {"wait_s", "poll_s", "budget_s", "fee"}. Si está, cada orden primero se pone como
        orden límite al mejor precio del libro (maker) y solo lo que no se llene se opera a mercado."""
        super().__init__(ledger, taker_fee, fallback_slippage, min_order_value)
        self.maker = dict(maker or {})
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._maker_left = float(self.maker.get("budget_s", 0.0))
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

    def _is_dust(self, asset: str, qty: float) -> bool:
        """Residuo menor que la unidad mínima de Bitso: no se puede vender (pasa igual con dinero real)."""
        sym = f"{asset}/{self.quote}"
        if sym not in self.ex.markets:
            return False
        try:
            return float(self.ex.amount_to_precision(sym, qty)) <= 0
        except Exception:  # noqa: BLE001  ccxt lo rechaza por ser menor que la precisión
            return True

    def positions(self) -> dict[str, float]:
        """Sin residuos invendibles: no cuentan como posición ni bloquean el día si les falta precio."""
        return {k: v for k, v in super().positions().items() if not self._is_dust(k, v)}

    def _maker_fill(self, sym: str, side: str, qty: float, price: float) -> float | None:
        """Orden límite simulada a `price` (mejor compra si compras, mejor venta si vendes).

        Cuenta como llenada solo lo que el mercado negocia ATRAVESANDO ese precio mientras se espera
        (conservador: no supone que la orden estaba primera en la fila), o todo si el libro la cruza.
        """
        wait = min(float(self.maker.get("wait_s", 0)), self._maker_left)
        poll = max(1.0, float(self.maker.get("poll_s", 15)))
        if wait < poll:
            return None  # sin tiempo de espera disponible: se opera a mercado directamente
        since = self.ex.milliseconds()
        start = self._clock()
        got = 0.0
        while self._clock() - start < wait and got < qty:
            self._sleep(poll)
            try:
                trades = self.ex.fetch_trades(sym, since=since, limit=100)
                through = [t for t in trades if (t.get("timestamp") or 0) >= since and
                           (t["price"] < price if side == "buy" else t["price"] > price)]
                got = min(qty, sum(float(t["amount"]) for t in through))
                top = self.ex.fetch_order_book(sym, limit=5)
                crossed = (top["asks"] and top["asks"][0][0] <= price) if side == "buy" else \
                          (top["bids"] and top["bids"][0][0] >= price)
                if crossed:
                    got = qty
            except Exception:  # noqa: BLE001  sin datos: se deja de esperar
                break
        self._maker_left = max(0.0, self._maker_left - (self._clock() - start))
        return got

    def execute(self, asset: str, side: str, qty: float, ref_price: float) -> Fill:
        sym = f"{asset}/{self.quote}"
        m = self.ex.markets.get(sym)
        if not m:
            return Fill(asset, side, 0.0, ref_price, 0.0, "failed", "Bitso no tiene este mercado", ref_price)
        if side == "sell":
            qty = min(qty, self.l["positions"].get(asset, 0.0))
        if not self.maker.get("wait_s"):
            return self._taker(asset, sym, m, side, qty, ref_price)
        mk = self._maker_leg(asset, sym, m, side, qty, ref_price)
        if mk is None:
            return self._taker(asset, sym, m, side, qty, ref_price)
        mq, mpx, mfee, mid0 = mk
        min_cost = max(self.min_order_value, ((m.get("limits") or {}).get("cost") or {}).get("min") or 0.0)
        rest = qty - mq
        tk = self._taker(asset, sym, m, side, rest, ref_price) if rest * mpx >= min_cost else None
        tq = tk.qty if tk is not None and tk.status != "failed" else 0.0
        tot = mq + tq
        if tot <= 0:
            return tk or Fill(asset, side, 0.0, mpx, 0.0, "failed", "no se llenó", mid0)
        avg = (mq * mpx + tq * (tk.price if tq else 0.0)) / tot
        fee = mfee + (tk.fee if tq else 0.0)
        status = "filled" if tot >= qty * 0.999 else "partial"
        note = f"límite: {mq / tot:.0%} como maker" + (", resto a mercado" if tq else "")
        return Fill(asset, side, tot, avg, fee, status, note, mid0)

    def _taker(self, asset: str, sym: str, m: dict, side: str, qty: float, ref_price: float) -> Fill:
        """Orden a mercado: recorre el libro real con la comisión taker."""
        try:
            qty = float(self.ex.amount_to_precision(sym, qty))
            book = self.ex.fetch_order_book(sym, limit=100)
        except Exception as exc:  # noqa: BLE001  sin libro: deslizamiento supuesto
            f = SimBroker.execute(self, asset, side, qty, ref_price)
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
        self._drop_dust(asset, side)
        status = "filled" if got >= qty * 0.999 else "partial"
        return Fill(asset, side, got, avg, fee, status, "" if status == "filled" else "profundidad insuficiente", mid)

    def _drop_dust(self, asset: str, side: str) -> None:
        left = self.l["positions"].get(asset)
        if side == "sell" and left is not None and self._is_dust(asset, left):
            self.l["positions"].pop(asset)  # el redondeo de Bitso deja un residuo que no se puede vender

    def _maker_leg(self, asset: str, sym: str, m: dict, side: str, qty: float, ref_price: float):
        """(cantidad, precio, comisión, medio del libro al empezar) de la parte maker, o None."""
        try:
            qty = float(self.ex.amount_to_precision(sym, qty))
            top = self.ex.fetch_order_book(sym, limit=5)
        except Exception:  # noqa: BLE001
            return None
        if not top["bids"] or not top["asks"]:
            return None
        mid = (top["bids"][0][0] + top["asks"][0][0]) / 2
        price = top["bids"][0][0] if side == "buy" else top["asks"][0][0]
        got = self._maker_fill(sym, side, qty, price)
        if got is None:
            return None
        if got <= 0:
            return (0.0, price, 0.0, mid)
        try:
            got = float(self.ex.amount_to_precision(sym, got))
        except Exception:  # noqa: BLE001  menor que la unidad mínima
            return (0.0, price, 0.0, mid)
        got, fee = self._apply(asset, side, got, price, float(self.maker.get("fee", 0.003)))
        self._drop_dust(asset, side)
        return (got, price, fee, mid)


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
