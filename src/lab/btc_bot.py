"""Bot de ejecución diaria. Usa EXACTAMENTE las mismas funciones de señal que el backtest.

Uso (desde la carpeta del proyecto):
    python -m lab.btc_bot                      # simulado (paper) con precios reales de hoy
    python -m lab.btc_bot --offline            # simulado con el CSV local, sin internet
    python -m lab.btc_bot --replay 365         # re-juega el último año día por día y lo compara con el backtest
    python -m lab.btc_bot --status             # estado, capital, drawdown, kill switch
    python -m lab.btc_bot --reset-kill-switch  # rearmar después de revisar qué pasó
    python -m lab.btc_bot --live               # DINERO REAL: requiere mode: live en config.yaml
                                           #   y la variable CONFIRMO_DINERO_REAL=si

Correrlo una vez al día, unos minutos después del cierre de la vela diaria
(00:05 UTC = 18:05 hora del centro de México). Ver README.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .backtest import simulate
from .data import ROOT, fetch_daily_closes, load_history, make_exchange
from .risk import RiskLimits, check_prices, drawdown_kill
from .strategies import compute, label

DEFAULT_CONFIG = {
    "mode": "paper",
    "strategy": {"name": "trend_ensemble", "params": {"lookbacks": [20, 50, 100, 200]}},
    "data": {"exchange": "kraken", "symbol": "BTC/USD", "offline_asset": "btc"},
    "execution": {"exchange": "bitso", "symbol": "BTC/MXN", "fee": 0.001, "slippage": 0.001,
                  "order_timeout_s": 20, "limit_offset": 0.003},
    "capital": {"max_capital": 5000, "paper_initial_cash": 5000},
    "risk": {},
    "paths": {"state": "state/state.json", "journal": "state/journal.csv"},
}
JOURNAL_FIELDS = ["run_at_utc", "mode", "candle_date", "signal_close", "strategy", "target",
                  "weight_before", "action", "amount_base", "price", "fee_quote",
                  "equity_after", "peak_equity", "drawdown", "kill_switch", "notes"]


# ------------------------------------------------------------------ config
def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_env(path: Path) -> None:
    """Carga un .env mínimo (CLAVE=valor) sin dependencias extra."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: Path) -> dict:
    import yaml

    user = yaml.safe_load(path.read_text()) if path.exists() else {}
    return _deep_merge(DEFAULT_CONFIG, user or {})


# ------------------------------------------------------------------ estado
def load_state(path: Path, cfg: dict) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"last_candle": None, "peak_equity": 0.0, "kill_switch": False,
            "paper": {"cash": float(cfg["capital"]["paper_initial_cash"]), "base": 0.0}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(path)  # escritura atómica: nunca queda un estado a medias


def append_journal(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in JOURNAL_FIELDS})


# ------------------------------------------------------------------ brokers
@dataclass
class Fill:
    side: str
    amount: float
    price: float
    fee_quote: float


class PaperBroker:
    """Simula ejecuciones con comisión y deslizamiento. Guarda saldos en el estado."""

    def __init__(self, state: dict, fee: float, slippage: float, min_cost: float = 10.0):
        self.s = state["paper"]
        self.fee, self.slip, self.min_cost = fee, slippage, min_cost

    def balances(self) -> tuple[float, float]:
        return self.s["base"], self.s["cash"]

    def execute(self, side: str, amount: float, ref_price: float) -> Fill:
        px = ref_price * (1 + self.slip if side == "buy" else 1 - self.slip)
        notional = amount * px
        fee = notional * self.fee
        if side == "buy":
            self.s["cash"] -= notional + fee
            self.s["base"] += amount
        else:
            self.s["cash"] += notional - fee
            self.s["base"] -= amount
        return Fill(side, amount, px, fee)


class LiveBroker:
    """Órdenes reales vía ccxt, con órdenes límite "agresivas" en vez de mercado:
    se llenan al instante como una de mercado pero con un precio máximo/mínimo,
    así un libro de órdenes vacío no te ejecuta a un precio absurdo."""

    def __init__(self, exchange, symbol: str, limit_offset: float, timeout_s: int):
        self.ex, self.symbol = exchange, symbol
        self.offset, self.timeout = limit_offset, timeout_s
        self.market = exchange.market(symbol)
        self.min_cost = (self.market.get("limits", {}).get("cost", {}) or {}).get("min") or 10.0

    def balances(self) -> tuple[float, float]:
        bal = self.ex.fetch_balance()
        base, quote = self.market["base"], self.market["quote"]
        return float(bal["total"].get(base, 0) or 0), float(bal["free"].get(quote, 0) or 0)

    def reference_price(self) -> float:
        t = self.ex.fetch_ticker(self.symbol)
        return float(t.get("last") or t["close"])

    def execute(self, side: str, amount: float, ref_price: float) -> Fill:
        t = self.ex.fetch_ticker(self.symbol)
        top = float(t["ask"] if side == "buy" else t["bid"])
        limit = top * (1 + self.offset) if side == "buy" else top * (1 - self.offset)
        amount = float(self.ex.amount_to_precision(self.symbol, amount))
        limit = float(self.ex.price_to_precision(self.symbol, limit))
        order = self.ex.create_order(self.symbol, "limit", side, amount, limit)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            order = self.ex.fetch_order(order["id"], self.symbol)
            if order.get("status") in ("closed", "canceled"):
                break
            time.sleep(2)
        if order.get("status") == "open":
            self.ex.cancel_order(order["id"], self.symbol)
            order = self.ex.fetch_order(order["id"], self.symbol)
        filled = float(order.get("filled") or 0)
        avg = float(order.get("average") or limit)
        fee = order.get("fee") or {}
        fee_quote = float(fee.get("cost") or 0) if fee.get("currency") == self.market["quote"] else 0.0
        return Fill(side, filled, avg, fee_quote)


# ------------------------------------------------------------------ lógica diaria
def decide_and_trade(cfg: dict, closes: pd.Series, broker, state: dict, now: pd.Timestamp,
                     exec_price: float, mode: str) -> dict:
    limits = RiskLimits(**cfg["risk"])
    strat = cfg["strategy"]
    name = label(strat["name"], strat.get("params"))
    candle = closes.index[-1].date().isoformat()
    row = {"run_at_utc": now.strftime("%Y-%m-%d %H:%M"), "mode": mode, "candle_date": candle,
           "signal_close": round(float(closes.iloc[-1]), 2), "strategy": name}

    if state.get("last_candle") == candle:
        row.update(action="skip", notes="ya se operó esta vela (evita operar dos veces)")
        return row

    issues, cautions = check_prices(closes, limits, now)
    base, quote = broker.balances()
    equity_total = quote + base * exec_price
    cap = float(cfg["capital"]["max_capital"])
    equity = min(equity_total, cap) if mode == "live" else equity_total
    weight = (base * exec_price / equity) if equity > 0 else 0.0
    state["peak_equity"] = max(float(state.get("peak_equity") or 0), equity)

    target = float(compute(strat["name"], closes, strat.get("params")).iloc[-1])
    target = min(target, limits.max_position)
    notes = list(cautions)
    if cautions:
        target = min(target, weight)
    if issues:
        row.update(action="no_trade", target=round(target, 4), weight_before=round(weight, 4),
                   equity_after=round(equity, 2), notes="; ".join(issues))
        return row  # no marcamos la vela como operada: se reintenta en la próxima corrida

    if state.get("kill_switch") or drawdown_kill(equity, state["peak_equity"], limits):
        if not state.get("kill_switch"):
            notes.append(f"KILL SWITCH: caída ≥{limits.max_drawdown_kill:.0%} desde el máximo")
        state["kill_switch"] = True
        target = 0.0

    diff = target - weight
    action, fill = "hold", None
    must_exit = target == 0.0 and base * exec_price >= broker.min_cost
    if abs(diff) > limits.rebalance_band or must_exit:
        value = diff * equity
        # El tope por orden solo limita COMPRAS: reducir riesgo nunca se frena.
        if value > limits.max_order_value:
            notes.append(f"compra recortada a {limits.max_order_value:,.0f}")
            value = limits.max_order_value
        if value > 0:
            ex = cfg["execution"]
            buffer = ex["fee"] + ex["slippage"] + ex.get("limit_offset", 0) + 0.001
            value = min(value, quote * (1 - buffer))
        amount = abs(value) / exec_price
        if value < 0:
            amount = min(amount, base)
        if amount * exec_price >= broker.min_cost:
            fill = broker.execute("buy" if value > 0 else "sell", amount, exec_price)
            action = fill.side
        else:
            notes.append("diferencia menor al mínimo del exchange")

    base, quote = broker.balances()
    equity_after = quote + base * exec_price
    if mode == "live":
        equity_after = min(equity_after, cap)
    state["peak_equity"] = max(state["peak_equity"], equity_after)
    state["last_candle"] = candle
    dd = equity_after / state["peak_equity"] - 1 if state["peak_equity"] else 0.0
    row.update(target=round(target, 4), weight_before=round(weight, 4), action=action,
               amount_base=round(fill.amount, 8) if fill else 0, price=round(fill.price, 2) if fill else "",
               fee_quote=round(fill.fee_quote, 4) if fill else 0, equity_after=round(equity_after, 2),
               peak_equity=round(state["peak_equity"], 2), drawdown=round(dd, 4),
               kill_switch=state.get("kill_switch", False), notes="; ".join(notes))
    return row


# ------------------------------------------------------------------ modos
def get_signal_closes(cfg: dict, offline: bool) -> pd.Series:
    if offline:
        return load_history(cfg["data"].get("offline_asset", "btc"))
    ex = make_exchange(cfg["data"]["exchange"])
    return fetch_daily_closes(ex, cfg["data"]["symbol"], days=720)


def replay(cfg: dict, days: int, closes: pd.Series | None = None) -> pd.DataFrame:
    """Re-juega los últimos `days` días con la lógica del bot y lo compara con el backtest.

    Si el bot y el backtest no coinciden, el backtest no describe lo que el bot hará.
    """
    if closes is None:
        closes = load_history(cfg["data"].get("offline_asset", "btc"))
    state = {"last_candle": None, "peak_equity": 0.0, "kill_switch": False,
             "paper": {"cash": float(cfg["capital"]["paper_initial_cash"]), "base": 0.0}}
    ex = cfg["execution"]
    broker = PaperBroker(state, ex["fee"], ex["slippage"], min_cost=0.0)
    rows = []
    for i in range(len(closes) - days, len(closes)):
        hist = closes.iloc[: i + 1]
        now = hist.index[-1] + pd.Timedelta(days=1, minutes=5)
        rows.append(decide_and_trade(cfg, hist, broker, state, now, float(hist.iloc[-1]), "paper"))
    df = pd.DataFrame(rows)
    df["candle_date"] = pd.to_datetime(df["candle_date"])
    df = df.set_index("candle_date")

    strat = cfg["strategy"]
    tgt = compute(strat["name"], closes, strat.get("params"))
    risk = RiskLimits(**cfg["risk"])
    bt = simulate(closes.iloc[len(closes) - days:], tgt, ex["fee"] + ex["slippage"], risk.rebalance_band)
    bot_eq = df["equity_after"].astype(float)
    bt_eq = (1 + bt["ret"]).cumprod() * float(cfg["capital"]["paper_initial_cash"])
    # el backtest aplica en D+1 lo decidido en D; el bot valúa al cierre de D después de operar
    df["backtest_equity"] = bt_eq.reindex(df.index).values
    return df


def print_status(state: dict, journal: Path) -> None:
    print(json.dumps({k: v for k, v in state.items()}, indent=2, default=str))
    if journal.exists():
        j = pd.read_csv(journal)
        print("\nÚltimas 10 corridas:")
        print(j.tail(10)[["run_at_utc", "mode", "candle_date", "target", "action", "equity_after",
                          "drawdown", "notes"]].to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bot de trading de tendencia (paper por defecto)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--live", action="store_true", help="operar con dinero real")
    ap.add_argument("--offline", action="store_true", help="usar datos locales, sin internet")
    ap.add_argument("--replay", type=int, metavar="DIAS", help="re-jugar N días y comparar con el backtest")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset-kill-switch", action="store_true")
    args = ap.parse_args(argv)

    load_env(ROOT / ".env")
    cfg = load_config(Path(args.config))
    state_path, journal = ROOT / cfg["paths"]["state"], ROOT / cfg["paths"]["journal"]

    if args.replay:
        df = replay(cfg, args.replay)
        gap = (df["equity_after"].astype(float) / df["backtest_equity"] - 1).abs().max()
        print(df[["target", "action", "equity_after", "backtest_equity"]].tail(15).to_string())
        print(f"\nDiferencia máxima bot vs backtest: {gap:.4%}")
        return 0 if gap < 0.01 else 1

    mode = "live" if args.live else "paper"
    if mode == "live":
        if cfg["mode"] != "live" or os.environ.get("CONFIRMO_DINERO_REAL", "").lower() != "si":
            print("Bloqueado: para operar en real necesitas mode: live en config.yaml, "
                  "la bandera --live y CONFIRMO_DINERO_REAL=si en el entorno.")
            return 2
    state = load_state(state_path, cfg)
    if args.status:
        print_status(state, journal)
        return 0
    if args.reset_kill_switch:
        state["kill_switch"] = False
        state["peak_equity"] = 0.0  # se recalcula en la siguiente corrida
        save_state(state_path, state)
        print("Kill switch rearmado y máximo de capital reiniciado.")
        return 0

    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    closes = get_signal_closes(cfg, args.offline)
    ex_cfg = cfg["execution"]
    if mode == "live":
        exchange = make_exchange(ex_cfg["exchange"], os.environ.get("EXCHANGE_API_KEY"),
                                 os.environ.get("EXCHANGE_API_SECRET"),
                                 os.environ.get("EXCHANGE_API_PASSWORD"))
        exchange.load_markets()
        broker = LiveBroker(exchange, ex_cfg["symbol"], ex_cfg["limit_offset"], ex_cfg["order_timeout_s"])
        price = broker.reference_price()
    else:
        broker = PaperBroker(state, ex_cfg["fee"], ex_cfg["slippage"])
        if args.offline:
            price = float(closes.iloc[-1])
            now = closes.index[-1] + pd.Timedelta(days=1, minutes=5)
        else:
            t = make_exchange(ex_cfg["exchange"]).fetch_ticker(ex_cfg["symbol"])
            price = float(t.get("last") or t["close"])

    row = decide_and_trade(cfg, closes, broker, state, now, price, mode)
    save_state(state_path, state)
    append_journal(journal, row)
    print(f"[{row['mode']}] vela {row['candle_date']} | objetivo {row.get('target', '-')} | "
          f"acción {row['action']} | capital {row.get('equity_after', '-')} | {row.get('notes', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
