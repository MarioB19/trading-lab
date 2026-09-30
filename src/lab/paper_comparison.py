"""Paired forward paper portfolios, isolated from every operational account.

No environment loader or broker factory is used. Inputs are public downloads or
explicit daily-close CSVs (first column date, YYYY-MM-DD). Every pair uses exactly
one frozen dataset per market. Historical rows warm signals; only wall-clock
observations after registration count towards the paper observation period.
"""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from uuid import uuid4

import numpy as np
import pandas as pd

from .aggressive_plan import (EXPERIMENT_ID, EXPERIMENT_IDS, PLAN_PATH, PREREGISTRATION, assert_current_control,
                              comparison_plan, isolated_directory, preregistration_path, roles_for)
from .bot import equity_history, fetch_prices, latest_closed_candle, run_sleeve
from .brokers import SimBroker
from .data import ROOT
from .experiments import ResearchGateError, canonical_hash, verify_preregistration
from .storage import SQLiteStore, execution_lock, dumps

DB_NAME = "comparison.sqlite3"
ROLES = ("control", "aggressive")
BLOCKS = ("crypto", "stocks")
IDENTITY = "isolated-paired-paper-v1"


def _now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _read_only(path: Path, name: str, default=None):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        row = db.execute("SELECT payload FROM documents WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else default
    finally:
        db.close()


def _directory(path: Path) -> Path:
    path = isolated_directory(path)
    # Reject even an otherwise isolated copy of an operational deployment.
    if path.exists():
        forbidden = ("trading.sqlite3", "runtime.yaml", "worker.enabled", "runtime.lock",
                     "deployment.json", "state.json")
        if any((path / name).exists() for name in forbidden):
            raise ResearchGateError("el directorio contiene un runtime o estado operativo")
        for child in path.iterdir():
            if child.is_symlink():
                raise ResearchGateError("el directorio experimental no admite enlaces simbólicos")
        if not (path / DB_NAME).exists() and any(
                p.name != "comparison.execution.lock" for p in path.iterdir()):
            raise ResearchGateError("el primer arranque exige un directorio vacío y dedicado")
    return path


def _store(path: Path, plan: dict, variants: list[dict], proof: dict, now: pd.Timestamp) -> SQLiteStore:
    database = path / DB_NAME
    if database.exists():
        marker = _read_only(database, "comparison_manifest", {})
        if (marker.get("type") != IDENTITY or marker.get("experiment_id") != plan["experiment_id"]
                or marker.get("config_sha256") != canonical_hash(plan)
                or marker.get("code_commit") != proof["code_commit"]
                or marker.get("preregistration") != proof):
            raise ResearchGateError("la base no pertenece a este experimento y versión exactos")
        return SQLiteStore(database)
    store = SQLiteStore(database)
    manifest = {"type": IDENTITY, "experiment_id": plan["experiment_id"],
                "run_id": uuid4().hex, "created_at": now.isoformat(),
                "config_sha256": canonical_hash(plan), "code_commit": proof["code_commit"],
                "preregistration": proof, "plan": plan, "variants": variants,
                "mode": "paper", "live_authorized": False}
    state = {"mode": "paper", "sleeves": {f"{role}.{block}": {
        "mode": "paper", "capital_base": 500.0,
        "ledger": {"cash": 500.0, "positions": {}}}
        for role in roles_for(plan) for block in BLOCKS}}
    with store.transaction() as db:
        store._write(db, "comparison_manifest", manifest)
        store._write(db, "state", state)
        store._write(db, "comparison_ticks", {})
        store._write(db, "comparison_history", [])
        store._write(db, "comparison_health", {"status": "awaiting_first_pair", "unresolved_errors": 0})
    return store


def validate_prices(raw: bytes, block: str, sc: dict, now: pd.Timestamp) -> pd.DataFrame:
    """Validate without sorting, deduplicating or silently discarding future bars."""
    try:
        text = raw.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(text)))
        if len(header) < 2 or header[0] not in ("date", "", "Date") or len(set(header)) != len(header):
            raise ValueError("cabecera date/activos inválida o repetida")
        frame = pd.read_csv(io.StringIO(text), index_col=0)
        labels = frame.index.astype(str)
        if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) for date in labels):
            raise ValueError("se requieren fechas diarias YYYY-MM-DD")
        frame.index = pd.DatetimeIndex(pd.to_datetime(labels, errors="raise"), name="date")
        frame = frame.apply(pd.to_numeric, errors="raise").astype(float)
    except (ValueError, StopIteration, UnicodeError, pd.errors.ParserError) as exc:
        raise ResearchGateError(f"{block}: CSV inválido: {exc}") from exc
    if (frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing
            or frame.index.hasnans):
        raise ResearchGateError(f"{block}: fechas vacías, repetidas o desordenadas")
    required = sc["universe"] if sc["strategy"] == "tactical" else list(sc["mix"])
    if set(required) - set(frame.columns) or set(frame.columns) - set(sc["universe"]):
        raise ResearchGateError(f"{block}: activos distintos del universo declarado")
    if len(frame) < max(250, int(sc["min_history"])):
        raise ResearchGateError(f"{block}: faltan al menos 250 cierres de calentamiento")
    values = frame.to_numpy()
    if np.isinf(values).any() or (values[np.isfinite(values)] <= 0).any():
        raise ResearchGateError(f"{block}: precios no positivos o infinitos")
    if frame[required].iloc[-1].isna().any() or (frame[required].notna().sum() < 250).any():
        raise ResearchGateError(f"{block}: cada activo requiere 250 precios y cierre actual válido")
    for asset in required:
        first = frame[asset].first_valid_index()
        missing = frame.loc[first:, asset].isna()
        if missing.any():
            date = missing.index[missing][0].date().isoformat()
            raise ResearchGateError(f"{block}/{asset}: cierre ausente {date} tras el primer precio; no se imputan precios")
    expected = latest_closed_candle(sc, now.tz_convert("UTC").tz_localize(None))
    if frame.index[-1] > expected:
        raise ResearchGateError(f"{block}: hay velas futuras o todavía abiertas")
    if block == "crypto":
        if frame.index[-1] != expected:
            raise ResearchGateError("crypto: falta el último cierre UTC completo")
        if not frame.index.equals(pd.date_range(frame.index[0], frame.index[-1], name="date")):
            raise ResearchGateError("crypto: faltan fechas diarias en la captura")
    else:
        if (frame.index.dayofweek >= 5).any():
            raise ResearchGateError("stocks: una vela de fin de semana no es una sesión válida")
        # A supplied holiday has no bar; the configured freshness limit still applies.
        ny_close = frame.index[-1].tz_localize("America/New_York") + pd.Timedelta(hours=17)
        if (now - ny_close.tz_convert("UTC")).total_seconds() > sc["max_data_age_hours"] * 3600:
            raise ResearchGateError("stocks: el cierre está fuera del límite de frescura")
    return frame


def _capture(raw: bytes, frame: pd.DataFrame, block: str, provenance: dict,
             path: Path, now: pd.Timestamp) -> dict:
    digest = hashlib.sha256(raw).hexdigest()
    inputs = path / "inputs"
    inputs.mkdir(exist_ok=True)
    target = inputs / f"{block}-{digest}.csv"
    if target.exists():
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ResearchGateError("la captura congelada fue modificada")
    else:
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {"file": str(target.relative_to(path)), "sha256": digest,
            "first": frame.index[0].date().isoformat(), "candle": frame.index[-1].date().isoformat(),
            "rows": len(frame), "assets": list(frame.columns), "captured_at": now.isoformat(),
            "provenance": provenance}


def _frozen_input(path: Path, capture: dict) -> bytes:
    frozen = path / capture["file"]
    if frozen.is_symlink() or frozen.resolve().parent != (path / "inputs").resolve():
        raise ResearchGateError("ruta de captura congelada inválida")
    raw = frozen.read_bytes()
    if hashlib.sha256(raw).hexdigest() != capture["sha256"]:
        raise ResearchGateError("la captura congelada fue modificada")
    return raw


def _inputs(plan, now, path, store, paths, fetch, provenance):
    frames, captures = {}, {}
    previous = store.read_document("comparison_inputs", {})
    for block in BLOCKS:
        sc = plan["portfolios"]["control"][block]
        declared = copy.deepcopy(provenance.get(block, {}))
        if fetch:
            expected = latest_closed_candle(sc, now.tz_convert("UTC").tz_localize(None)).date().isoformat()
            old = previous.get(block)
            if old and old["candle"] == expected:
                raw = _frozen_input(path, old)
                declared = old["provenance"]
            else:
                notes = []
                fetch_sc = copy.deepcopy(sc)
                if block == "stocks":
                    fetch_sc["universe"] = list(sc["mix"])
                frame = fetch_prices(block, fetch_sc, now, notes)
                raw = frame.to_csv(index_label="date", date_format="%Y-%m-%d", float_format="%.17g").encode()
                declared = {"source": copy.deepcopy(sc["data"]), "quote": sc["quote"],
                            "price_basis": "adjusted_close" if block == "stocks" else "daily_close",
                            "transport": "public_endpoints_without_credentials", "notes": notes,
                            "fetched_at": now.isoformat()}
                if old and block == "stocks" and not frame.empty and frame.index[-1].date().isoformat() == old["candle"]:
                    # A market holiday can leave Friday as the newest bar while a rolling
                    # provider window drops old warmup rows. Preserve the original vintage
                    # only when all overlapping prices remain exactly unchanged.
                    received = validate_prices(raw, block, sc, now)
                    previous_raw = _frozen_input(path, old)
                    previous_frame = validate_prices(previous_raw, block, sc, now)
                    common = received.index.intersection(previous_frame.index)
                    if (len(common) < 250 or set(received.columns) != set(previous_frame.columns)
                            or not received.loc[common, previous_frame.columns].equals(previous_frame.loc[common])):
                        raise ResearchGateError("stocks: una vela ya procesada tiene datos revisados")
                    raw, declared = previous_raw, old["provenance"]
        else:
            source = Path(paths[block]).resolve()
            if source == (path / DB_NAME).resolve() or source.name in ("comparison.json", "comparison.md"):
                raise ResearchGateError("un resultado no puede ser fuente de precios")
            raw = source.read_bytes()
            declared = {"source": "user_supplied_csv", "path": str(source), "quote": "USD",
                        "price_basis": "unspecified_by_provider", **declared,
                        "provider_verified": False}
        frame = validate_prices(raw, block, sc, now)
        frames[block] = frame
        captures[block] = _capture(raw, frame, block, declared, path, now)
    return frames, captures


def _metrics(snapshot: dict, trades: list[dict], name: str) -> dict:
    fills = [r for r in trades if r["sleeve"] == name and r["status"] in ("filled", "partial")]
    fees = sum(float(r["fee"]) for r in fills)
    slippage = sum(float(r["qty"]) * (float(r["price"]) - float(r["ref_price"]))
                   * (1 if r["side"] == "buy" else -1) for r in fills)
    return {"equity_usd": snapshot["equity"], "pnl_usd": round(snapshot["equity"] - 500, 2),
            "return_pct": round((snapshot["equity"] / 500 - 1) * 100, 4),
            "cash_usd": snapshot["cash"], "exposure": snapshot["exposure"],
            "drawdown_pct": round(snapshot["drawdown"] * 100, 4),
            "fees_usd": round(fees, 6), "slippage_usd": round(slippage, 6),
            "modeled_cost_usd": round(fees + slippage, 6), "fills": len(fills),
            "traded_notional_usd": round(sum(float(r["value"]) for r in fills), 2),
            "kill_switch": snapshot["kill_switch"], "candle": snapshot["candle"]}


def _report(manifest, state, snapshots, trades, history, now, captures):
    plan = manifest["plan"]
    portfolios = {}
    for role in roles_for(plan):
        blocks = {block: _metrics(snapshots[f"{role}.{block}"], trades, f"{role}.{block}") for block in BLOCKS}
        for block, metrics in blocks.items():
            observed = [500.0] + [row["portfolios"][role]["blocks"][block]["equity_usd"] for row in history]
            observed.append(metrics["equity_usd"])
            metrics["max_drawdown_pct"] = round(float(min(np.array(observed) / np.maximum.accumulate(observed) - 1)) * 100, 4)
        value = sum(x["equity_usd"] for x in blocks.values())
        values = [1000.0] + [r["portfolios"][role]["equity_usd"] for r in history] + [value]
        peaks = np.maximum.accumulate(values)
        current_dd = value / peaks[-1] - 1
        worst = min(np.array(values) / peaks - 1)
        portfolios[role] = {"equity_usd": round(value, 2), "pnl_usd": round(value - 1000, 2),
                            "return_pct": round((value / 1000 - 1) * 100, 4),
                            "drawdown_pct": round(current_dd * 100, 4),
                            "max_drawdown_pct": round(float(worst) * 100, 4),
                            "fees_usd": round(sum(x["fees_usd"] for x in blocks.values()), 6),
                            "modeled_cost_usd": round(sum(x["modeled_cost_usd"] for x in blocks.values()), 6),
                            "kill_switch": any(x["kill_switch"] for x in blocks.values()), "blocks": blocks}
    started = history[0]["observed_at"] if history else now.isoformat()
    observed_days = len({r["observed_at"][:10] for r in history} | {now.date().isoformat()})
    elapsed = max(0., (now - pd.Timestamp(started)).total_seconds() / 86400)
    observations = history + [{"candles": {block: captures[block]["candle"] for block in BLOCKS}}]
    gaps = []
    for previous, current in zip(observations, observations[1:]):
        left, right = previous["candles"]["crypto"], current["candles"]["crypto"]
        missing = (pd.Timestamp(right) - pd.Timestamp(left)).days - 1
        if missing > 0:
            gaps.append({"after_candle": left, "before_candle": right, "missing_daily_decisions": missing})
    paper_complete = observed_days >= 28 and elapsed >= 28 and not gaps
    return {"experiment_id": manifest["experiment_id"], "run_id": manifest["run_id"], "mode": "paper",
            "config_sha256": manifest["config_sha256"], "code_commit": manifest["code_commit"],
            "preregistration": manifest["preregistration"],
            "generated_at": now.isoformat(), "started_at": started, "ended_at": now.isoformat(),
            "status": ("incomplete_observation_gaps" if gaps else "paper_observed_28_days"
                       if paper_complete else "collecting_forward_observations"),
            "observed_days": observed_days, "elapsed_days": round(elapsed, 4),
            "remaining_observed_days": max(0, 28 - observed_days),
            "remaining_elapsed_days": round(max(0, 28 - elapsed), 4),
            "complete": paper_complete, "unresolved_errors": len(gaps), "observation_gaps": gaps,
            "ready_for_human_review": False, "live_authorized": False,
            "promotion_note": "28 días observados no sustituyen los gates cuantitativos ni autorización humana",
            "execution_model": plan["execution_model"],
            "cost_model": {block: {"fee": plan["portfolios"]["control"][block]["fee"],
                                    "slippage": plan["portfolios"]["control"][block]["slippage"],
                                    "approx_one_way_bps": plan["costs"][block]["base"] * 10000}
                           for block in BLOCKS},
            "limitations": ["Fills ideales al cierre más deslizamiento; no simula libro, colas ni órdenes maker.",
                            "Los CSV y ajustes del proveedor no son verificados externamente.",
                            "ETFs a precios ajustados: sin contabilidad independiente de dividendos/splits.",
                            "El historial previo calienta señales; no cuenta como tiempo observado.",
                            "Sincronía entre carteras; cada mercado conserva la fecha de su propio cierre."],
            "datasets": captures, "portfolios": portfolios,
            "paired_pnl_difference_usd": round(portfolios[roles_for(plan)[1]]["pnl_usd"] - portfolios["control"]["pnl_usd"], 2),
            "sleeves": snapshots}


def _markdown(report):
    lines = ["# Comparación de carteras simuladas", "",
             "Capital virtual inicial: USD 1,000 por cartera; USD 500 por bloque.", "",
             "| Cartera | Capital USD | Resultado USD | Caída máxima | Coste modelado USD | Estado |",
             "|---|---:|---:|---:|---:|---|"]
    for role, values in report["portfolios"].items():
        lines.append(f"| {role} | {values['equity_usd']:.2f} | {values['pnl_usd']:+.2f} | "
                     f"{values['max_drawdown_pct']:.2f}% | {values['modeled_cost_usd']:.4f} | "
                     f"{'Kill switch activo' if values['kill_switch'] else 'Paper'} |")
    lines += ["", "| Bloque | Capital USD | Resultado USD | Caída máxima | Comisión modelada USD | Cierre |",
              "|---|---:|---:|---:|---:|---|"]
    for role, values in report["portfolios"].items():
        for block, value in values["blocks"].items():
            lines.append(f"| {role}.{block} | {value['equity_usd']:.2f} | {value['pnl_usd']:+.2f} | "
                         f"{value['max_drawdown_pct']:.2f}% | {value['fees_usd']:.4f} | {value['candle']} |")
    lines += ["", f"Días observados: {report['observed_days']}; tiempo transcurrido: {report['elapsed_days']:.2f} días.",
              f"Pendientes: {report['remaining_observed_days']} días con observación y "
              f"{report['remaining_elapsed_days']:.2f} días completos de calendario.",
              f"Estado: {report['status']}. Incidencias pendientes: {report['unresolved_errors']}.", "",
              "Comisión/deslizamiento por orden: cripto 36 + 9 bps; ETFs 0 + 5 bps.",
              "Son costes simulados, no costes medidos en un broker. Cada compra y venta paga su coste.",
              "", report["promotion_note"], "Dinero real autorizado: NO.", ""]
    lines += [f"- {note}" for note in report["limitations"]]
    if report.get("observation_gaps"):
        lines += ["", "Hay decisiones diarias omitidas. Este periodo no acredita observación continua;"]
        lines += ["los huecos no se rellenan retrospectivamente ni se borran al reintentar."]
    if report.get("last_error"):
        lines += ["", f"Último error: {report['last_error']}"]
    return "\n".join(lines) + "\n"


def _export(path, report):
    for name, contents in (("comparison.json", json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"),
                           ("comparison.md", _markdown(report))):
        target = path / name
        if target.is_symlink():
            raise ResearchGateError("una exportación no puede ser un enlace simbólico")
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("w") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)


def status(data_dir: Path, plan_path: Path | None = None) -> dict:
    """Read existing evidence only. Does not initialize or run any strategy."""
    path = isolated_directory(data_dir)
    selected = comparison_plan(plan_path)[0] if plan_path is not None else None
    database = path / DB_NAME
    if not database.is_file():
        return {"experiment_id": selected["experiment_id"] if selected else EXPERIMENT_ID,
                "status": "not_started", "live_authorized": False}
    manifest = _read_only(database, "comparison_manifest", {})
    if manifest.get("type") != IDENTITY or manifest.get("experiment_id") not in EXPERIMENT_IDS:
        raise ResearchGateError("no es una comparación paper registrada")
    if (manifest.get("config_sha256") != canonical_hash(manifest.get("plan"))
            or manifest.get("code_commit") != manifest.get("preregistration", {}).get("code_commit")
            or (selected is not None and (manifest["experiment_id"] != selected["experiment_id"]
                                          or manifest["config_sha256"] != canonical_hash(selected)))):
        raise ResearchGateError("identidad, plan o prueba de preregistro de la base no coinciden")
    result = _read_only(database, "comparison", {"experiment_id": manifest["experiment_id"],
                                                "status": "awaiting_first_pair", "live_authorized": False})
    for field in ("config_sha256", "code_commit", "preregistration"):
        if field in result and result[field] != manifest[field]:
            raise ResearchGateError("el resultado no corresponde al manifiesto de la comparación")
        result[field] = manifest[field]
    if result["experiment_id"] != manifest["experiment_id"]:
        raise ResearchGateError("el resultado pertenece a otro experimento")
    health = _read_only(database, "comparison_health", {})
    result["health"] = health
    if health.get("status") == "error":
        result.update(status="error", complete=False, unresolved_errors=max(1, result.get("unresolved_errors", 0)),
                      last_error=health.get("last_error"), ready_for_human_review=False)
    return result


def run_once(preregistration_commit: str, data_dir: Path, crypto_prices: Path | None = None,
             stocks_prices: Path | None = None, provenance: dict | None = None, *, fetch: bool = False,
             plan_path: Path | None = None, attestation: Path | None = None) -> dict:
    """Run one current pair. No historical date override is accepted."""
    plan, variants = comparison_plan(plan_path) if plan_path is not None else comparison_plan()
    if attestation is None:
        proof = verify_preregistration(ROOT, preregistration_path(plan), preregistration_commit, plan["experiment_id"],
                                       plan, [variant["id"] for variant in variants])
    else:
        if (ROOT / ".git").exists():
            raise ResearchGateError("attestation es exclusiva de imágenes sin .git; el checkout exige su gate Git")
        from .research_attestation import verify_attestation
        proof = verify_attestation(ROOT, attestation, plan_path if plan_path is not None else PLAN_PATH,
                                   preregistration_path(plan), preregistration_commit, plan,
                                   [variant["id"] for variant in variants])
    assert_current_control(plan)
    if provenance is not None and (not isinstance(provenance, dict)
            or set(provenance) - set(BLOCKS)
            or any(not isinstance(value, dict) for value in provenance.values())):
        raise ResearchGateError("provenance debe contener objetos crypto/stocks")
    if provenance and any(value.get("quote", "USD") != "USD" for value in provenance.values()):
        raise ResearchGateError("todos los precios de la comparación deben estar en USD")
    if (fetch and (crypto_prices or stocks_prices)) or (not fetch and not (crypto_prices and stocks_prices)):
        raise ResearchGateError("elige --fetch o ambos CSV, sin combinarlos")
    path = _directory(Path(data_dir))
    now = _now().tz_convert("UTC")
    with execution_lock(path / "comparison"):
        store = _store(path, plan, variants, proof, now)
        try:
            frames, captures = _inputs(plan, now, path, store,
                                       {"crypto": crypto_prices, "stocks": stocks_prices}, fetch, provenance or {})
            history = store.read_document("comparison_history", [])
            if history and now < pd.Timestamp(history[-1]["observed_at"]):
                raise ResearchGateError("el reloj retrocedió desde la última observación")
            ticks = store.read_document("comparison_ticks", {})
            candles = {block: captures[block]["candle"] for block in BLOCKS}
            hashes = {block: captures[block]["sha256"] for block in BLOCKS}
            pair = canonical_hash(candles)
            # Revised same-candle inputs cannot rewrite trades or compare different vintages.
            for old in ticks.values():
                for block in BLOCKS:
                    if old["candles"][block] == candles[block] and old["hashes"][block] != hashes[block]:
                        raise ResearchGateError(f"{block}: una vela ya procesada tiene datos revisados")
            if pair in ticks:
                report = store.read_document("comparison")
                # A valid identical retry resolves input/transport errors without counting another day.
                store.write_document("comparison_health", {"status": "ok", "last_attempt": now.isoformat(),
                                      "last_success": report["generated_at"], "unresolved_errors": report["unresolved_errors"]})
                _export(path, report)
                return report
            state = store.read_document("state")
            snapshots = store.read_document("snapshot", {}).get("sleeves", {})
            if history:
                for block in BLOCKS:
                    if candles[block] < history[-1]["candles"][block]:
                        raise ResearchGateError(f"{block}: no se permite retroceder la vela")
            manifest = store.read_document("comparison_manifest")
            all_equity = pd.DataFrame(store.rows("equity"))
            trades, equity_rows = [], []
            for role in roles_for(plan):
                for block in BLOCKS:
                    name = f"{role}.{block}"
                    sc = copy.deepcopy(plan["portfolios"][role][block])
                    sleeve = state["sleeves"][name]
                    broker = SimBroker(sleeve["ledger"], sc["fee"], sc["slippage"], sc["min_order_value"])
                    result = run_sleeve(name, sc, frames[block].copy(deep=True), broker, sleeve, now,
                                        "paper", equity_history(all_equity, name, "paper"), plan["max_price_jump"])
                    if result["status"] not in ("ok", "skip") or sleeve.get("execution_pending"):
                        raise ResearchGateError(f"{name}: {result['status']}: {'; '.join(result['notes'])}")
                    if result["snapshot"] is not None:
                        snapshots[name] = result["snapshot"]
                    if result["equity_row"] is not None:
                        equity_rows.append(result["equity_row"])
                    for index, trade in enumerate(result["trades"]):
                        trade["execution_id"] = canonical_hash({"run": manifest["run_id"],
                                                                  "pair": pair, "sleeve": name, "index": index})
                        trades.append(trade)
                    if broker.cash() < -1e-8 or any(q < 0 for q in broker.positions().values()):
                        raise ResearchGateError("el simulador produjo efectivo negativo o una posición corta")
            if snapshots["control.stocks"] != snapshots[f"{roles_for(plan)[1]}.stocks"]:
                raise ResearchGateError("las carteras ETF idénticas divergieron")
            report = _report(manifest, state, snapshots, store.rows("trades") + trades, history, now, captures)
            entry = {"observed_at": now.isoformat(), "candles": candles, "hashes": hashes,
                     "portfolios": report["portfolios"]}
            history.append(entry)
            ticks[pair] = entry
            snapshot = {"generated": now.isoformat(), "mode": "paper", "sleeves": snapshots,
                        "experiment_id": plan["experiment_id"], "live_authorized": False}
            with store.transaction() as db:
                store._write(db, "state", state)
                store._rows(db, "trades", trades)
                store._rows(db, "equity", equity_rows)
                store._write(db, "snapshot", snapshot)
                store._write(db, "comparison", report)
                store._write(db, "comparison_ticks", ticks)
                store._write(db, "comparison_history", history)
                store._write(db, "comparison_inputs", captures)
                store._write(db, "comparison_health", {"status": "ok", "last_attempt": now.isoformat(),
                                                       "last_success": now.isoformat(), "unresolved_errors": report["unresolved_errors"]})
                db.execute("INSERT INTO events(kind,payload,created_at) VALUES(?,?,?)",
                           ("comparison_pair_committed", dumps({"pair": pair, "candles": candles, "hashes": hashes}), now.isoformat()))
            _export(path, report)
            return report
        except Exception as exc:
            store.write_document("comparison_health", {"status": "error", "last_attempt": now.isoformat(),
                                  "last_error": f"{type(exc).__name__}: {exc}", "unresolved_errors": 1})
            store.record_event("comparison_pair_failed", {"observed_at": now.isoformat(), "error": str(exc)})
            existing = status(path)
            if "portfolios" in existing:
                _export(path, existing)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--once", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--describe", action="store_true")
    parser.add_argument("--preregistration-commit")
    parser.add_argument("--plan", type=Path, help="plan preregistrado v1/v2; por defecto aggressive_v1.yaml")
    parser.add_argument("--attestation", type=Path, help="prueba Git de imagen sin .git; exige BUILD_ID exacto")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--crypto-prices", type=Path)
    parser.add_argument("--stocks-prices", type=Path)
    parser.add_argument("--fetch", action="store_true", help="descarga pública después del gate; no usa llaves")
    parser.add_argument("--provenance", type=Path, help="JSON opcional con metadatos crypto/stocks de los CSV")
    args = parser.parse_args(argv)
    try:
        if args.describe:
            plan, variants = comparison_plan(args.plan) if args.plan is not None else comparison_plan()
            print(json.dumps({"plan": plan, "variants": variants, "config_sha256": canonical_hash(plan),
                              "status": "declared_not_run", "live_authorized": False}, ensure_ascii=False, indent=2))
            return 0
        if not args.data_dir:
            parser.error("se requiere --data-dir dedicado")
        if args.status:
            print(json.dumps(status(args.data_dir, args.plan), ensure_ascii=False, indent=2))
            return 0
        if not args.preregistration_commit:
            parser.error("se requiere --preregistration-commit")
        # Only descriptive provenance is read here; market CSVs and network remain behind the gate.
        provenance = json.loads(args.provenance.read_text()) if args.provenance else None
        report = run_once(args.preregistration_commit, args.data_dir, args.crypto_prices,
                          args.stocks_prices, provenance, fetch=args.fetch, plan_path=args.plan,
                          attestation=args.attestation)
        print(_markdown(report))
        print(f"Evidencia: {args.data_dir / 'comparison.json'}")
        return 0
    except (ResearchGateError, ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"Comparación bloqueada: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
