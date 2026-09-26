"""Motor en tiempo real: revisa el portafolio cada hora (GitHub) o cada pocos minutos (servidor).

    python -m lab.realtime --once                     # una revisión: lo que corre GitHub cada hora
    python -m lab.realtime --loop --every 300         # proceso continuo, para un servidor 24/7
    python -m lab.realtime --loop --every 300 --git-push   # además sube el estado al repositorio

Qué hace lo decide `realtime.action` en config.yaml, fijado con evidencia
(reports/tiempo_real_informe.md):

  observe   Valúa las posiciones con el precio de este momento, mide la caída contra el máximo,
            calcula qué pesos daría la señal si el día cerrara ahora (cierre provisional, con las
            mismas funciones de lab.portfolio) y avisa si el bloque se acerca al kill switch.
            No opera: comprar y rebalancear sigue siendo tarea de la corrida diaria.
  watch     Lo anterior y, si el freno por caída se aprieta o se cruza el kill switch, vende.
            Solo reduce. Se activa únicamente si la variante R3 pasa la prueba pre-registrada.

La corrida diaria (`python -m lab.bot --if-due`) es idempotente: la revisión de cada hora la
llama primero, así que si GitHub no lanzó la corrida de las 00:20 UTC, se pone al día sola.
Escribe state/live.json (foto del momento) y state/live_equity.csv (una fila por revisión).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .bot import (EQUITY_FIELDS, ROOT, append_csv, book_value, compute_targets, fetch_prices,
                  is_capped, load_config, load_env, load_state, make_broker, research_summary, save_json,
                  sleeve_params)
from .data import make_exchange, yahoo_last
from .portfolio import drawdown_multiplier, with_provisional_close

LIVE_FIELDS = ["time_utc", "sleeve", "mode", "equity", "drawdown", "exposure", "brake_now", "action"]
REALTIME_DEFAULTS = {"enabled": True, "action": "observe", "every_minutes": 60, "alert_kill_margin": 0.05,
                     "max_price_age_minutes": 90}


# ------------------------------------------------------------------ precios del momento
def live_prices(sc: dict, assets: list[str], notes: list[str]) -> tuple[pd.Series, pd.Timestamp | None]:
    """Último precio de cada activo y la hora del dato más viejo (UTC)."""
    px, times = {}, []
    if sc["data"]["source"] == "ccxt":
        for ex_name in [sc["data"]["exchange"], sc["data"].get("fallback_exchange")]:
            missing = [a for a in assets if a not in px]
            if not ex_name or not missing:
                continue
            try:
                ex = make_exchange(ex_name)
                ex.load_markets()
                syms = [f"{a}/{sc['quote']}" for a in missing if f"{a}/{sc['quote']}" in ex.markets]
                if not syms:
                    continue
                tick = ex.fetch_tickers(syms)
                for sym, t in tick.items():
                    last = t.get("last") or t.get("close")
                    if last and last > 0:
                        px[sym.split("/")[0]] = float(last)
                        times.append(pd.Timestamp(t["timestamp"], unit="ms") if t.get("timestamp")
                                     else pd.Timestamp.now(tz="UTC").tz_localize(None))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"precios de {ex_name} no disponibles: {str(exc)[:80]}")
    else:
        for a in assets:
            try:
                p, t = yahoo_last(a)
                px[a] = p
                times.append(t)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"sin precio de {a}: {str(exc)[:60]}")
    oldest = min(times) if times else None
    return pd.Series(px, dtype=float), oldest


# ------------------------------------------------------------------ una revisión de un bloque
def check_sleeve(name: str, sc: dict, st: dict, rt: dict, mode: str, now: pd.Timestamp,
                 eq_hist: pd.Series, broker=None, daily: pd.DataFrame | None = None,
                 live: pd.Series | None = None, ref_prices: pd.Series | None = None) -> dict:
    """Foto del bloque a precio de mercado. No opera (acción observe)."""
    notes: list[str] = []
    alerts: list[str] = []
    broker = broker or make_broker(name, sc, mode, st, notes)
    positions, cash = broker.positions(), broker.cash()
    tactical = sc["strategy"] == "tactical"
    want = sorted(set(positions) | (set(sc["universe"]) if tactical else set(sc.get("mix", {}))))
    price_time = None
    if live is None:
        live, price_time = live_prices(sc, want, notes)
    last_daily = pd.Series(dtype=float)
    if daily is None and tactical:
        daily = fetch_prices(name, sc, now, notes)
    if daily is not None and len(daily):
        last_daily = daily.iloc[-1]
    elif ref_prices is not None:
        last_daily = ref_prices  # precios de la última corrida diaria (foto del bot)
    px = live.reindex(want)
    # si falta un precio en vivo se usa el último cierre diario (nunca se valúa en cero)
    fallback = [a for a in positions if not np.isfinite(px.get(a, np.nan))]
    for a in fallback:
        if np.isfinite(last_daily.get(a, np.nan)):
            px[a] = float(last_daily[a])
    no_price = [a for a in positions if not np.isfinite(px.get(a, np.nan))]
    if fallback:
        notes.append("sin precio en vivo para " + ", ".join(fallback) + ("; uso el último cierre" if not no_price else ""))
    if no_price:
        return {"status": "blocked", "notes": notes + [f"sin ningún precio para {', '.join(no_price)}: no se valúa"],
                "alerts": alerts, "updated_utc": now.strftime("%Y-%m-%d %H:%M")}

    capped = is_capped(broker, mode)
    value, equity, cash_in = book_value(positions, cash, px, sc["capital"], capped)
    peak = max(float(st.get("peak") or 0.0), equity)
    dd = equity / peak - 1 if peak > 0 else 0.0
    p = sleeve_params(sc)
    recent = pd.concat([eq_hist.iloc[-(p.dd_peak_window - 1):], pd.Series([equity], index=[now.normalize()])])
    dd_roll = equity / recent.max() - 1 if len(recent) else 0.0
    brake_now = drawdown_multiplier(dd_roll, p) if tactical else 1.0
    kill = sc["kill_drawdown"]
    kill_equity = peak * (1 - kill)
    if st.get("kill_switch"):
        alerts.append("kill switch activado: el bloque está apagado")
    elif dd <= -kill:
        alerts.append(f"el bloque cayó {-dd:.1%} desde su máximo: la corrida diaria activará el kill switch")
    elif dd <= -(kill - rt["alert_kill_margin"]):
        alerts.append(f"a {kill + dd:.1%} del kill switch ({-dd:.1%} de caída; se activa en {kill:.0%})")
    if tactical and brake_now < float(st.get("last_brake", 1.0)) - 1e-9:
        alerts.append(f"el freno por caída se apretaría a {brake_now:.0%} de exposición")
    if price_time is not None and (now - price_time).total_seconds() / 60 > rt["max_price_age_minutes"] \
            and sc["data"]["source"] == "ccxt":
        alerts.append(f"el precio más viejo es de {price_time:%H:%M} UTC")

    daily_value = {a: q * float(last_daily[a]) for a, q in positions.items()
                   if np.isfinite(last_daily.get(a, np.nan))}
    rows = []
    for a, q in sorted(positions.items(), key=lambda kv: -value.get(kv[0], 0.0)):
        if a not in value:
            continue
        ref = float(last_daily[a]) if np.isfinite(last_daily.get(a, np.nan)) else None
        rows.append({"asset": a, "qty": round(q, 8), "price": round(float(px[a]), 6),
                     "value": round(value[a], 2), "weight": round(value[a] / equity, 4) if equity > 0 else 0.0,
                     "change_since_close": round(float(px[a]) / ref - 1, 4) if ref else None})
    out = {"status": "ok", "label": sc["label"], "strategy": sc["strategy"], "broker": broker.name,
           "updated_utc": now.strftime("%Y-%m-%d %H:%M"),
           "prices_as_of_utc": price_time.strftime("%Y-%m-%d %H:%M") if price_time is not None else None,
           "equity": round(equity, 2), "cash": round(cash_in, 2),
           "exposure": round(sum(value.values()) / equity, 4) if equity > 0 else 0.0,
           "peak": round(peak, 2), "drawdown": round(dd, 4), "kill_drawdown": kill,
           "kill_at_equity": round(kill_equity, 2), "brake_now": round(brake_now, 3),
           "kill_switch": bool(st.get("kill_switch")),
           "change_since_close": (round(sum(value.values()) / sum(daily_value.values()) - 1, 4)
                                  if daily_value and len(daily_value) == len(value) and sum(daily_value.values()) > 0 else None),
           "positions": rows, "alerts": alerts, "notes": notes, "action": rt["action"]}

    if tactical and daily is not None and len(daily):
        # ¿qué haría la señal si el día cerrara ahora? (solo informativo)
        today = now.normalize()
        panel = with_provisional_close(daily, live.reindex(daily.columns), today) if daily.index[-1] < today else daily
        target, _ = compute_targets(sc, panel)
        w_now = {a: v / equity for a, v in value.items()} if equity > 0 else {}
        sig = []
        for a in sorted(set(target.index[target > 0]) | set(w_now), key=lambda x: -float(target.get(x, 0))):
            t_, w_ = float(target.get(a, 0.0)), float(w_now.get(a, 0.0))
            move = "entraría" if w_ == 0 and t_ > sc["band"] else "saldría" if t_ == 0 and w_ > 0 else (
                "subiría" if t_ - w_ > sc["band"] else "bajaría" if w_ - t_ > sc["band"] else "igual")
            sig.append({"asset": a, "target_now": round(t_ * brake_now, 4), "weight_now": round(w_, 4), "move": move})
        out["signal_now"] = sig
    return out


# ------------------------------------------------------------------ ciclo
def tick(cfg: dict, mode: str, now: pd.Timestamp | None = None) -> dict:
    rt = {**REALTIME_DEFAULTS, **(cfg.get("realtime") or {})}
    paths = {k: ROOT / v for k, v in cfg["paths"].items()}
    live_path, live_csv = paths["state"].parent / "live.json", paths["state"].parent / "live_equity.csv"
    now = now or pd.Timestamp.now(tz="UTC").tz_localize(None)
    state = load_state(paths["state"])
    eq_all = pd.read_csv(paths["equity"]) if paths["equity"].exists() else pd.DataFrame(columns=EQUITY_FIELDS)
    snap = json.loads(paths["snapshot"].read_text()) if paths["snapshot"].exists() else {}
    out = {"updated_utc": now.strftime("%Y-%m-%d %H:%M"), "mode": mode, "action": rt["action"],
           "every_minutes": rt["every_minutes"], "sleeves": {}, "research": research_summary()}
    rows = []
    for name, sc in cfg["sleeves"].items():
        if not sc.get("enabled"):
            continue
        st = json.loads(json.dumps(state["sleeves"].get(name, {})))  # copia: observar no cambia el estado
        if st.get("mode") and st["mode"] != mode:
            out["sleeves"][name] = {"status": "skip", "notes": [f"el bloque está en modo {st['mode']}"]}
            continue
        h = eq_all[(eq_all["sleeve"] == name) & (eq_all["mode"] == mode)] if len(eq_all) else eq_all
        eq_hist = pd.Series(h["equity"].astype(float).values, index=pd.to_datetime(h["date"])) if len(h) else pd.Series(dtype=float)
        try:
            ref = pd.Series({a["asset"]: a["price"] for a in snap.get("sleeves", {}).get(name, {}).get("assets", [])
                             if a.get("price")}, dtype=float)
            r = check_sleeve(name, sc, st, rt, mode, now, eq_hist, ref_prices=ref)
        except Exception as exc:  # noqa: BLE001  un bloque que falla no detiene al otro
            r = {"status": "error", "notes": [f"error: {str(exc)[:160]}"], "alerts": []}
        out["sleeves"][name] = r
        if r.get("status") == "ok":
            rows.append({"time_utc": out["updated_utc"], "sleeve": name, "mode": mode, "equity": r["equity"],
                         "drawdown": r["drawdown"], "exposure": r["exposure"], "brake_now": r["brake_now"],
                         "action": rt["action"]})
        print(f"[{mode} · {rt['action']}] {name}: {r.get('status')} | capital {r.get('equity', '-')} | "
              f"caída {r.get('drawdown', '-')} | {'; '.join(r.get('alerts', []) + r.get('notes', []))}")
    save_json(live_path, out)
    append_csv(live_csv, LIVE_FIELDS, rows)
    trim_csv(live_csv, now - pd.Timedelta(days=rt.get("keep_days", 90)))
    return out


def trim_csv(path: Path, since: pd.Timestamp) -> None:
    """Conserva solo las revisiones recientes (el historial diario completo está en equity.csv)."""
    if not path.exists():
        return
    df = pd.read_csv(path)
    keep = pd.to_datetime(df["time_utc"]) >= since
    if not keep.all():
        df[keep].to_csv(path, index=False)


def git_push(message: str) -> None:
    """Sube state/ al repositorio (para un servidor con credenciales de git configuradas)."""
    def run(*a):
        return subprocess.run(a, cwd=ROOT, capture_output=True, text=True)
    run("git", "add", "state/")
    if run("git", "commit", "-m", message).returncode == 0:
        run("git", "pull", "--rebase")
        run("git", "push")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Revisión en tiempo real (simulado por defecto)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--once", action="store_true", help="una sola revisión")
    ap.add_argument("--loop", action="store_true", help="revisar sin parar")
    ap.add_argument("--every", type=int, default=None, help="segundos entre revisiones (con --loop)")
    ap.add_argument("--git-push", action="store_true", help="con --loop: sube state/ tras cada revisión")
    ap.add_argument("--live", action="store_true", help="leer las cuentas reales (mismos tres candados)")
    args = ap.parse_args(argv)
    load_env(ROOT / ".env")
    cfg = load_config(Path(args.config))
    rt = {**REALTIME_DEFAULTS, **(cfg.get("realtime") or {})}
    if not rt["enabled"]:
        print("Tiempo real apagado en config.yaml (realtime.enabled).")
        return 0
    mode = "live" if args.live else "paper"
    if mode == "live" and (cfg["mode"] != "live" or os.environ.get("CONFIRMO_DINERO_REAL", "").lower() != "si"):
        print("Bloqueado: para leer u operar cuentas reales necesitas mode: live en config.yaml, "
              "la bandera --live y CONFIRMO_DINERO_REAL=si.")
        return 2
    if rt["action"] not in ("observe",):
        print(f"Acción '{rt['action']}' no disponible: la prueba pre-registrada no la aprobó. Uso observe.")
        cfg["realtime"] = {**rt, "action": "observe"}
    if not args.loop:
        tick(cfg, mode)
        return 0
    every = args.every or int(rt["every_minutes"]) * 60
    while True:  # pragma: no cover  (proceso de servidor)
        from .bot import main as bot_main
        try:
            bot_main(["--config", args.config, "--if-due"] + (["--live"] if args.live else []))
            tick(cfg, mode)
            if args.git_push:
                git_push(f"tiempo real: {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M}")
        except Exception as exc:  # noqa: BLE001  el proceso sigue vivo
            print(f"[error] {exc}", file=sys.stderr)
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main())
