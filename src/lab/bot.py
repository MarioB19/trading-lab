"""Bot multi-activo diario: un bloque de criptomonedas y uno de acciones/ETFs.

    python -m lab.bot                    # corrida del día, SIMULADA, con precios reales
    python -m lab.bot --offline          # con los datos locales de data/, sin internet
    python -m lab.bot --replay 365       # re-juega el último año (cripto) y lo compara con el backtest
    python -m lab.bot --status           # resumen de cada bloque
    python -m lab.bot --reset-kill-switch crypto
    python -m lab.bot --live             # DINERO REAL: mode: live en config.yaml + CONFIRMO_DINERO_REAL=si

Usa las MISMAS funciones de señal que la investigación (lab.portfolio), así que lo que
el backtest mide es lo que el bot hace.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .brokers import AlpacaBroker, BitsoBroker, Fill, SimBroker
from .data import DATA_DIR, ROOT, fetch_daily_closes, make_exchange, yahoo_daily
from .portfolio import PortfolioParams, clean, drawdown_multiplier, listed_universe, target_weights

SLEEVE_DEFAULTS = {
    "crypto": {
        "enabled": True, "label": "Criptomonedas", "strategy": "tactical",
        "params": {"top_k": 5, "vol_target": 0.40, "regime_asset": "BTC", "dd_brake": True,
                   "max_weight": 0.40, "ann": 365, "mom_windows": [30, 90, 180]},
        "universe": ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "LTC", "BCH",
                     "XLM", "TRX", "HBAR", "NEAR", "UNI", "ATOM"],
        "data": {"source": "ccxt", "exchange": "kraken", "fallback_exchange": "bitso"},
        "quote": "USD", "paper_broker": "sim", "live_broker": "bitso",
        "capital": 300.0, "fee": 0.001, "slippage": 0.002, "band": 0.02,
        "kill_drawdown": 0.45, "max_order_value": 300.0, "min_order_value": 5.0,
        "max_data_age_hours": 36, "benchmark": "BTC", "min_history": 250,
    },
    "stocks": {
        "enabled": True, "label": "Acciones y ETFs", "strategy": "passive",
        "mix": {"SPY": 0.6, "IEF": 0.4},
        "params": {"top_k": 5, "vol_target": 0.10, "regime_asset": None, "dd_brake": True,
                   "max_weight": 0.35, "ann": 252, "mom_windows": [21, 63, 126], "cov_window": 63,
                   "dd_peak_window": 126},
        "universe": ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWW", "TLT", "IEF", "GLD", "DBC", "VNQ",
                     "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB"],
        "data": {"source": "yahoo"},
        "quote": "USD", "paper_broker": "sim", "live_broker": "alpaca",
        "capital": 700.0, "fee": 0.0, "slippage": 0.0005, "band": 0.05,
        "kill_drawdown": 0.25, "max_order_value": 700.0, "min_order_value": 1.0,
        "max_data_age_hours": 100, "benchmark": "SPY", "min_history": 250,
    },
}
DEFAULT_CONFIG = {"mode": "paper", "max_price_jump": 0.40, "sleeves": SLEEVE_DEFAULTS,
                  "paths": {"state": "state/state.json", "trades": "state/trades.csv",
                            "equity": "state/equity.csv", "snapshot": "state/snapshot.json"}}
TRADE_FIELDS = ["run_at_utc", "sleeve", "mode", "broker", "candle", "asset", "side", "qty", "price",
                "value", "fee", "status", "note"]
EQUITY_FIELDS = ["date", "sleeve", "mode", "equity", "cash", "exposure", "drawdown", "brake",
                 "benchmark_price", "n_positions"]


# ------------------------------------------------------------------ config y estado
def _merge(base, over):
    if not isinstance(base, dict) or not isinstance(over, dict):
        return copy.deepcopy(over)
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if k in base and isinstance(base[k], dict) and k not in ("mix",) else copy.deepcopy(v)
    return out


def load_config(path: Path) -> dict:
    import yaml

    user = yaml.safe_load(path.read_text()) if path.exists() else {}
    return _merge(DEFAULT_CONFIG, user or {})


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"sleeves": {}}


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    tmp.replace(path)


def append_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


# ------------------------------------------------------------------ datos
def fetch_prices(name: str, sc: dict, now: pd.Timestamp, notes: list[str]) -> pd.DataFrame:
    """Cierres diarios COMPLETOS del universo del bloque, en USD."""
    out = {}
    if sc["data"]["source"] == "ccxt":
        exs = [make_exchange(sc["data"]["exchange"])]
        if sc["data"].get("fallback_exchange"):
            exs.append(make_exchange(sc["data"]["fallback_exchange"]))
        for a in sc["universe"]:
            for ex in exs:
                try:
                    out[a] = fetch_daily_closes(ex, f"{a}/{sc['quote']}", days=720)
                    break
                except Exception:  # noqa: BLE001
                    continue
            else:
                notes.append(f"sin datos para {a}")
    else:
        start = (now - pd.Timedelta(days=3 * 365)).strftime("%Y-%m-%d")
        for a in sc["universe"]:
            try:
                out[a] = yahoo_daily(a, start=start)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"sin datos para {a}: {exc}")
        ny = now.tz_localize("UTC").tz_convert("America/New_York") if now.tzinfo is None else now.tz_convert("America/New_York")
        cutoff = ny.normalize().tz_localize(None)
        if ny.hour < 17:  # la sesión de hoy no ha cerrado
            out = {k: v[v.index < cutoff] for k, v in out.items()}
    if not out:
        raise RuntimeError("no se pudo descargar ningún precio")
    P = pd.DataFrame(out).sort_index()
    return P


def offline_prices(name: str, sc: dict) -> pd.DataFrame:
    f = DATA_DIR / ("crypto_prices.csv" if name == "crypto" else "etf_prices.csv")
    P = pd.read_csv(f, index_col=0, parse_dates=True)
    return P[[a for a in sc["universe"] if a in P.columns]]


# ------------------------------------------------------------------ señales
def sleeve_params(sc: dict) -> PortfolioParams:
    return PortfolioParams.from_dict(sc["params"])


def compute_targets(sc: dict, prices: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    last = prices.index[-1]
    valid = prices.iloc[-1].notna()
    if sc["strategy"] == "passive":
        mix = {k: v for k, v in sc["mix"].items() if k in prices.columns and valid.get(k, False)}
        tot = sum(sc["mix"].values())
        target = pd.Series({k: v / max(tot, 1.0) for k, v in mix.items()}).reindex(prices.columns).fillna(0.0)
        table = pd.DataFrame({"target": target, "price": prices.loc[last]})
        return target, table
    p = sleeve_params(sc)
    elig = listed_universe(prices, sc.get("min_history", 250))
    W, sig = target_weights(prices, elig, p, return_signals=True)
    table = pd.DataFrame({
        "target": W.loc[last], "trend": sig["trend"].loc[last], "momentum": sig["mom"].loc[last],
        "vol": sig["vol"].loc[last], "score": sig["score"].loc[last], "eligible": elig.loc[last],
        "price": prices.loc[last]})
    return W.loc[last], table


# ------------------------------------------------------------------ lógica diaria de un bloque
def run_sleeve(name: str, sc: dict, prices: pd.DataFrame, broker, st: dict, now: pd.Timestamp,
               mode: str, eq_hist: pd.Series, max_jump: float) -> dict:
    """Decide y ejecuta. Devuelve trades, fila de capital y la foto para el tablero."""
    candle = prices.index[-1]
    cstr = candle.date().isoformat()
    notes: list[str] = []
    res = {"trades": [], "equity_row": None, "snapshot": None, "status": "ok", "notes": notes}
    if st.get("last_candle") == cstr:
        res["status"] = "skip"
        notes.append("esta vela ya se operó")
        return res
    age_h = ((now.tz_localize(None) if now.tzinfo else now) - (candle + pd.Timedelta(days=1))).total_seconds() / 3600
    if age_h > sc["max_data_age_hours"]:
        res["status"] = "blocked"
        notes.append(f"datos viejos: la última vela cerró hace {age_h:.0f} h")
        return res
    if broker.pending():
        res["status"] = "blocked"
        notes.append("hay órdenes de la corrida anterior esperando la apertura del mercado")
        return res

    target, table = compute_targets(sc, prices)
    fresh = prices.iloc[-1].notna()           # activos con precio del día: se pueden operar
    px = clean(prices).iloc[-1]               # valuación: último precio válido (hasta 5 días)
    positions = broker.positions()
    cash = broker.cash()
    missing = [a for a in positions if a not in px.index or not np.isfinite(px.get(a, np.nan))]
    if missing:
        # valuar a 0 algo que sí tienes dispararía un kill switch falso
        res["status"] = "blocked"
        notes.append(f"sin precio confiable para {', '.join(missing)}: no se opera hoy")
        return res
    value = {a: q * float(px[a]) for a, q in positions.items() if a in px.index and np.isfinite(px[a])}
    equity_total = cash + sum(value.values())
    # En una cuenta externa (real o paper de Alpaca, que trae $100k virtuales) el bot solo
    # maneja `capital`; así el simulado se comporta igual que lo haría el real.
    capped = mode == "live" or not isinstance(broker, SimBroker)
    equity = min(equity_total, float(sc["capital"])) if capped else equity_total
    w_now = {a: v / equity for a, v in value.items()} if equity > 0 else {}

    peak = max(float(st.get("peak") or 0), equity)
    p = sleeve_params(sc)
    recent = pd.concat([eq_hist.iloc[-(p.dd_peak_window - 1):] if len(eq_hist) else eq_hist,
                        pd.Series([equity], index=[candle])])
    dd_roll = equity / recent.max() - 1 if len(recent) else 0.0
    brake = drawdown_multiplier(dd_roll, p) if sc["strategy"] == "tactical" else 1.0
    if st.get("kill_switch") or (peak > 0 and equity <= peak * (1 - sc["kill_drawdown"])):
        if not st.get("kill_switch"):
            notes.append(f"KILL SWITCH: caída de {sc['kill_drawdown']:.0%} desde el máximo. Se vende todo y "
                         "el bloque queda apagado hasta rearmarlo a mano.")
        st["kill_switch"] = True
        brake = 0.0
    desired = (target * brake).to_dict()

    # un dato raro nunca debe hacer comprar: solo se permite reducir ese activo
    jumps = prices.pct_change(fill_method=None).abs().iloc[-5:].max()
    for a, j in jumps.items():
        if np.isfinite(j) and j > max_jump and desired.get(a, 0) > w_now.get(a, 0):
            desired[a] = w_now.get(a, 0.0)
            notes.append(f"{a}: salto de {j:.0%}; solo se permite reducir")

    band, minv = sc["band"], broker.min_order_value
    orders = []
    for a in sorted(set(desired) | set(w_now)):
        if a not in px.index or not np.isfinite(px[a]):
            continue
        if not fresh.get(a, False):
            if abs(desired.get(a, 0.0) - w_now.get(a, 0.0)) > band:
                notes.append(f"{a}: sin precio de hoy, se opera mañana")
            continue
        d, w = desired.get(a, 0.0), w_now.get(a, 0.0)
        diff = d - w
        exit_all = d == 0 and w > 0 and value.get(a, 0) >= minv
        if abs(diff) > band or exit_all:
            orders.append((a, diff))
    run_at = (now.tz_localize(None) if now.tzinfo else now).strftime("%Y-%m-%d %H:%M")
    buffer = sc["fee"] + sc["slippage"] + 0.005
    fills: list[Fill] = []
    for a, diff in sorted(orders, key=lambda x: x[1]):  # primero ventas (liberan efectivo)
        price = float(px[a])
        if diff < 0:
            qty = positions.get(a, 0.0) if desired.get(a, 0.0) == 0 else min(-diff * equity / price, positions.get(a, 0.0))
            if qty * price < minv:
                continue
            fills.append(broker.execute(a, "sell", qty, price))
        else:
            val = min(diff * equity, sc["max_order_value"], broker.cash() * (1 - buffer))
            if val < minv:
                if diff * equity >= minv:
                    notes.append(f"{a}: sin efectivo suficiente para comprar")
                continue
            fills.append(broker.execute(a, "buy", val / price, price))
    for f in fills:
        res["trades"].append({"run_at_utc": run_at, "sleeve": name, "mode": mode, "broker": broker.name,
                              "candle": cstr, "asset": f.asset, "side": f.side, "qty": round(f.qty, 8),
                              "price": round(f.price, 6), "value": round(f.qty * f.price, 2),
                              "fee": round(f.fee, 4), "status": f.status, "note": f.note})
        if f.status == "failed":
            notes.append(f"orden fallida {f.side} {f.asset}: {f.note}")

    # valuación después de operar
    positions = broker.positions()
    cash = broker.cash()
    value = {a: q * float(px[a]) for a, q in positions.items() if a in px.index and np.isfinite(px[a])}
    eq_after = cash + sum(value.values())
    if capped:
        eq_after = min(eq_after, float(sc["capital"]))
        cash = max(0.0, eq_after - sum(value.values()))  # efectivo dentro del capital asignado
    st["peak"] = max(peak, eq_after)
    st["last_candle"] = cstr
    exposure = sum(value.values()) / eq_after if eq_after > 0 else 0.0
    bench = sc.get("benchmark")
    res["equity_row"] = {"date": cstr, "sleeve": name, "mode": mode, "equity": round(eq_after, 2),
                         "cash": round(cash, 2), "exposure": round(exposure, 4),
                         "drawdown": round(eq_after / st["peak"] - 1, 4), "brake": round(brake, 3),
                         "benchmark_price": round(float(px[bench]), 6) if bench in px.index else "",
                         "n_positions": len(value)}
    tbl = table.copy()
    tbl["weight"] = pd.Series({a: v / eq_after for a, v in value.items()}) if eq_after > 0 else 0.0
    tbl["weight"] = tbl["weight"].fillna(0.0)
    tbl["qty"] = pd.Series(positions).reindex(tbl.index).fillna(0.0)
    tbl = tbl.replace([np.inf, -np.inf], np.nan)
    res["snapshot"] = {
        "label": sc["label"], "strategy": sc["strategy"], "broker": broker.name, "mode": mode,
        "candle": cstr, "equity": round(eq_after, 2), "cash": round(cash, 2), "capital": sc["capital"],
        "exposure": round(exposure, 4), "peak": round(st["peak"], 2),
        "drawdown": round(eq_after / st["peak"] - 1, 4), "brake": round(brake, 3),
        "kill_switch": bool(st.get("kill_switch")), "kill_drawdown": sc["kill_drawdown"],
        "benchmark": bench,
        "assets": [{"asset": a, **{k: _jsonable(v) for k, v in row.items()}}
                   for a, row in tbl.sort_values(["target", "weight"], ascending=False).iterrows()],
        "notes": notes,
    }
    return res


def _jsonable(v):
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return None if not np.isfinite(v) else round(float(v), 6)
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else v


# ------------------------------------------------------------------ brokers
def make_broker(name: str, sc: dict, mode: str, st: dict, notes: list[str]):
    minv = float(sc["min_order_value"])
    if mode == "live":
        if sc["live_broker"] == "bitso":
            return BitsoBroker(sc["quote"], min_order_value=minv)
        if sc["live_broker"] == "alpaca":
            return AlpacaBroker(paper=False, min_order_value=minv)
        raise RuntimeError(f"broker real desconocido: {sc['live_broker']}")
    if sc["paper_broker"] == "alpaca_paper":
        try:
            return AlpacaBroker(paper=True, min_order_value=minv)
        except RuntimeError as exc:
            notes.append(f"Alpaca paper no disponible ({exc}); uso el simulado interno")
    st.setdefault("ledger", {"cash": float(sc["capital"]), "positions": {}})
    return SimBroker(st["ledger"], sc["fee"], sc["slippage"], minv)


# ------------------------------------------------------------------ replay
def replay(cfg: dict, name: str = "crypto", days: int = 365, prices: pd.DataFrame | None = None) -> pd.DataFrame:
    """Re-juega día por día con la lógica del bot y compara con simulate_portfolio."""
    from .portfolio import simulate_portfolio

    sc = cfg["sleeves"][name]
    P = offline_prices(name, sc) if prices is None else prices
    st: dict = {}
    broker = make_broker(name, sc, "paper", st, [])
    broker.min_order_value = 0.0
    rows, eq = [], pd.Series(dtype=float)
    for i in range(len(P) - days, len(P)):
        hist = P.iloc[: i + 1]
        now = hist.index[-1] + pd.Timedelta(days=1, minutes=10)
        r = run_sleeve(name, sc, hist, broker, st, now, "paper", eq, 10.0)
        if r["equity_row"]:
            eq.loc[hist.index[-1]] = r["equity_row"]["equity"]
            rows.append(r["equity_row"])
    df = pd.DataFrame(rows).set_index("date")
    df.index = pd.to_datetime(df.index)
    p = sleeve_params(sc)
    if sc["strategy"] == "tactical":
        W = target_weights(P, listed_universe(P, sc.get("min_history", 250)), p)
    else:
        p.dd_brake = False
        W = pd.DataFrame(0.0, index=P.index, columns=P.columns)
        for k, v in sc["mix"].items():
            W[k] = v / sum(sc["mix"].values())
    start = P.index[len(P) - days]
    bt = simulate_portfolio(P.loc[start:], W.loc[start:], p, sc["fee"] + sc["slippage"], sc["band"],
                            kill_dd=sc["kill_drawdown"])
    df["backtest_equity"] = ((1 + bt["ret"]).cumprod() * float(sc["capital"])).reindex(df.index).values
    return df


# ------------------------------------------------------------------ principal
def research_summary() -> dict:
    f = ROOT / "reports" / "multi_results.json"
    if not f.exists():
        return {}
    r = json.loads(f.read_text())
    out = {"generated": r.get("generated"), "combined": {k: r["combined"].get(k) for k in ("cagr", "max_dd", "p_loss_12m", "crypto_share")}}
    for sl in ("crypto", "stocks"):
        x = r[sl]
        rec = x["recommended"]
        bkey = next(k for k in x["oos"] if k.startswith("Comprar y aguantar"))
        out[sl] = {"label": x["label"], "oos_start": x["oos_start"], "recommended": rec,
                   "strategy": {k: x["oos"][rec][k] for k in ("cagr", "sharpe", "max_dd")},
                   "benchmark_name": bkey, "benchmark": {k: x["oos"][bkey][k] for k in ("cagr", "sharpe", "max_dd")},
                   "tactical": {k: x["oos"]["CANDIDATA: " + x["candidate"]][k] for k in ("cagr", "sharpe", "max_dd")},
                   "placebo_p": x["placebo"]["p_value"],
                   "p_loss_12m": (x["monte_carlo_12m"].get("passive") if x["recommended"] != "CANDIDATA: " + x["candidate"]
                                  else x["monte_carlo_12m"]["candidate"])["p_loss"]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bot multi-activo (simulado por defecto)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--replay", type=int, metavar="DIAS")
    ap.add_argument("--sleeve", choices=["crypto", "stocks"])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset-kill-switch", metavar="BLOQUE")
    args = ap.parse_args(argv)

    load_env(ROOT / ".env")
    cfg = load_config(Path(args.config))
    paths = {k: ROOT / v for k, v in cfg["paths"].items()}

    if args.replay:
        name = args.sleeve or "crypto"
        df = replay(cfg, name, args.replay)
        gap = (df["equity"] / df["backtest_equity"] - 1).abs().max()
        print(df[["equity", "backtest_equity", "exposure", "brake"]].tail(10).to_string())
        print(f"\nDiferencia máxima bot vs backtest ({name}): {gap:.3%}")
        return 0 if gap < 0.02 else 1

    mode = "live" if args.live else "paper"
    if mode == "live" and (cfg["mode"] != "live" or os.environ.get("CONFIRMO_DINERO_REAL", "").lower() != "si"):
        print("Bloqueado: para operar con dinero real necesitas mode: live en config.yaml, "
              "la bandera --live y CONFIRMO_DINERO_REAL=si.")
        return 2

    state = load_state(paths["state"])
    if args.status:
        snap = json.loads(paths["snapshot"].read_text()) if paths["snapshot"].exists() else {}
        for n, s in snap.get("sleeves", {}).items():
            print(f"{n}: capital {s.get('equity')} | caída {s.get('drawdown')} | exposición {s.get('exposure')} | "
                  f"kill {s.get('kill_switch')} | {s.get('status')} | {'; '.join(s.get('notes', []))}")
        return 0
    if args.reset_kill_switch:
        st = state["sleeves"].setdefault(args.reset_kill_switch, {})
        st["kill_switch"] = False
        st["peak"] = 0.0
        save_json(paths["state"], state)
        print(f"Kill switch de {args.reset_kill_switch} rearmado.")
        return 0

    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    snapshot = json.loads(paths["snapshot"].read_text()) if paths["snapshot"].exists() else {"sleeves": {}}
    eq_all = pd.read_csv(paths["equity"]) if paths["equity"].exists() else pd.DataFrame(columns=EQUITY_FIELDS)
    trades, eq_rows, failures = [], [], 0
    names = [args.sleeve] if args.sleeve else [n for n, s in cfg["sleeves"].items() if s.get("enabled")]
    for name in names:
        sc = cfg["sleeves"][name]
        st = state["sleeves"].setdefault(name, {})
        if st.get("mode") and st["mode"] != mode:
            st.clear()  # cambiar de simulado a real reinicia el historial del bloque
        st["mode"] = mode
        notes: list[str] = []
        try:
            P = offline_prices(name, sc) if args.offline else fetch_prices(name, sc, now, notes)
            run_now = P.index[-1] + pd.Timedelta(days=1, minutes=10) if args.offline else now
            broker = make_broker(name, sc, mode, st, notes)
            h = eq_all[(eq_all["sleeve"] == name) & (eq_all["mode"] == mode)] if len(eq_all) else eq_all
            eq_hist = pd.Series(h["equity"].astype(float).values, index=pd.to_datetime(h["date"])) if len(h) else pd.Series(dtype=float)
            r = run_sleeve(name, sc, P, broker, st, run_now, mode, eq_hist, cfg["max_price_jump"])
        except Exception as exc:  # noqa: BLE001  un bloque que falla no detiene al otro
            failures += 1
            r = {"status": "error", "notes": [f"error: {exc}"], "trades": [], "equity_row": None, "snapshot": None}
        r["notes"][:0] = notes
        trades += r["trades"]
        if r["equity_row"]:
            eq_rows.append(r["equity_row"])
        prev = snapshot["sleeves"].get(name, {})
        snap = r["snapshot"] or prev
        snap.update({"status": r["status"], "last_run_utc": now.strftime("%Y-%m-%d %H:%M"),
                     "notes": r["notes"] or snap.get("notes", [])})
        snapshot["sleeves"][name] = snap
        print(f"[{mode}] {name}: {r['status']} | operaciones {len(r['trades'])} | "
              f"capital {snap.get('equity', '-')} | {'; '.join(r['notes'])}")

    snapshot.update({"generated_utc": now.strftime("%Y-%m-%d %H:%M"), "mode": mode, "research": research_summary()})
    save_json(paths["state"], state)
    append_csv(paths["trades"], TRADE_FIELDS, trades)
    append_csv(paths["equity"], EQUITY_FIELDS, eq_rows)
    save_json(paths["snapshot"], snapshot)
    try:  # análisis de operaciones (FIFO) para el tablero; nunca debe tumbar la corrida
        from .analyze import run as analyze_run

        snapshot["analysis"] = analyze_run(write=paths["snapshot"].parent == ROOT / "state")["summary"]
        save_json(paths["snapshot"], snapshot)
    except Exception as exc:  # noqa: BLE001
        print(f"[aviso] análisis de operaciones: {exc}")
    return 1 if failures == len(names) else 0


if __name__ == "__main__":
    sys.exit(main())
