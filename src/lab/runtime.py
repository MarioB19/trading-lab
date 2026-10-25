"""Single-writer, paper-only runtime. No cloud account is required to prepare it."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import yaml

DATABASE_NAME = "trading.sqlite3"
_STOP = threading.Event()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def redact(message: str) -> str:
    for name, value in os.environ.items():
        if len(value) >= 8 and any(word in name.upper() for word in ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "KEY_ID")):
            message = message.replace(value, "[REDACTED]")
    return message[:2000]


def log(event: str, **fields) -> None:
    print(json.dumps({"event": event, "time_utc": utc_now(), **fields}, default=str), flush=True)


@contextlib.contextmanager
def exclusive_lock(path: Path):
    """Kernel lock, released on crashes too. Never delete a lock inode while in use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Otro proceso conserva el bloqueo operativo") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_config(cfg: dict) -> None:
    if cfg.get("mode") != "paper":
        raise ValueError("Este runtime admite exclusivamente mode: paper")
    if cfg.get("realtime", {}).get("action", "observe") != "observe":
        raise ValueError("La observación no puede activar otra estrategia")
    if cfg.get("realtime", {}).get("enabled", True) is not True:
        raise ValueError("Este runtime requiere observación habilitada para comprobar su salud")
    active = [s for s in cfg.get("sleeves", {}).values() if s.get("enabled")]
    if not active:
        raise ValueError("No hay bloques habilitados")
    for sleeve in active:
        if sleeve.get("params", {}).get("rotation_buffer", 0.0) != 0.0:
            raise ValueError("La variante de menor rotación requiere validación y promoción; no está habilitada")
        if sleeve.get("paper_broker") not in {"sim", "bitso_book", "alpaca_paper"}:
            raise ValueError("Broker paper desconocido")
        for key in ("capital", "max_order_value", "min_order_value"):
            value = float(sleeve[key])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Valor inválido para {key}")
        if not 0 < float(sleeve["kill_drawdown"]) < 1:
            raise ValueError("kill_drawdown debe estar entre cero y uno")
        if not 0 <= float(sleeve["band"]) < 1:
            raise ValueError("Banda inválida")
        if sleeve.get("strategy") == "passive":
            weights = [float(v) for v in sleeve.get("mix", {}).values()]
            if not weights or any(not math.isfinite(w) or w < 0 for w in weights) or sum(weights) > 1.000001:
                raise ValueError("La mezcla debe ser long-only y sin apalancamiento")


def prepare_config(source: Path, data_dir: Path, interval: int) -> tuple[Path, str]:
    from .bot import load_config

    if not source.is_file():
        raise ValueError("Falta la configuración explícita")
    cfg = load_config(source)
    validate_config(cfg)
    if not 60 <= interval <= 3600:
        raise ValueError("El intervalo de observación debe estar entre 60 y 3600 segundos")
    data_dir = data_dir.resolve()
    cfg["paths"] = {name: str(data_dir / filename) for name, filename in {
        "state": "state.json", "trades": "trades.csv", "equity": "equity.csv",
        "snapshot": "snapshot.json", "database": DATABASE_NAME,
    }.items()}
    cfg["realtime"] = {**cfg.get("realtime", {}), "every_minutes": interval / 60}
    encoded = yaml.safe_dump(cfg, sort_keys=True, allow_unicode=True).encode()
    target = data_dir / "runtime.yaml"
    temporary = target.with_suffix(".yaml.tmp")
    temporary.write_bytes(encoded)
    temporary.chmod(0o600)
    temporary.replace(target)
    return target, hashlib.sha256(encoded).hexdigest()


def run_cycle(config: Path, store, interval: int, *, timeout: int = 900, runner=subprocess.run) -> dict:
    previous = store.read_document("runtime_health", {}) or {}
    health = {
        "status": "running", "last_attempt_utc": utc_now(),
        "last_success_utc": previous.get("last_success_utc"), "interval_seconds": interval,
        "build_id": os.environ.get("TRADING_LAB_BUILD_ID", "local-uncommitted"),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    }
    store.write_document("runtime_health", health)
    start = time.monotonic()
    errors = []
    for module, args in (("lab.bot", ["--if-due"]), ("lab.realtime", ["--once"])):
        try:
            result = runner([sys.executable, "-m", module, "--config", str(config), *args],
                            timeout=timeout, capture_output=True, text=True, check=False)
            if result.returncode:
                errors.append({"component": module, "returncode": result.returncode,
                               "detail": redact(result.stderr or result.stdout or "Falló el componente")})
        except subprocess.TimeoutExpired:
            errors.append({"component": module, "detail": "Tiempo máximo agotado; conciliar antes de reintentar"})
        except OSError as exc:
            errors.append({"component": module, "detail": redact(str(exc))})
    snapshot = store.read_document("snapshot", {}) or {}
    live = store.read_document("live", {}) or {}
    cfg = yaml.safe_load(config.read_text()) or {}
    expected = {name for name, sleeve in cfg.get("sleeves", {}).items() if sleeve.get("enabled")}
    if not expected:
        errors.append({"component": "config", "detail": "Sin bloques activos declarados"})
    for kind, document in (("snapshot", snapshot), ("live", live)):
        if not expected.issubset(document.get("sleeves", {})):
            errors.append({"component": kind, "detail": "Faltan bloques activos por observar"})
        if document.get("mode") != "paper":
            errors.append({"component": kind, "detail": "Modo paper no verificado"})
        for name, sleeve in document.get("sleeves", {}).items():
            allowed = {"ok", "skip"} if kind == "snapshot" else {"ok"}
            if name in expected and sleeve.get("status") not in allowed:
                errors.append({"component": f"{kind}.{name}", "detail": sleeve.get("status")})
    # The daily snapshot can legitimately stay unchanged between closes. The
    # observation must actually have been committed by this cycle, even if its
    # minute-resolution payload happens to equal the previous one.
    with store.connect() as db:
        observed = db.execute("SELECT updated_at FROM documents WHERE name='live'").fetchone()
    try:
        written = dt.datetime.fromisoformat(observed[0]) if observed else None
        began = dt.datetime.fromisoformat(health["last_attempt_utc"])
        if written is None or written.tzinfo is None or written < began:
            errors.append({"component": "live", "detail": "No se produjo una observación nueva en este ciclo"})
    except (ValueError, TypeError):
        errors.append({"component": "live", "detail": "Fecha de observación inválida"})
    storage_health = store.health()
    if storage_health.get("integrity") != "ok" or storage_health.get("pending_orders"):
        errors.append({"component": "storage", "detail": "Integridad o conciliación pendiente"})
    health.update(status="error" if errors else "ok", last_completed_utc=utc_now(),
                  duration_seconds=round(time.monotonic() - start, 3), errors=errors)
    if not errors:
        health["last_success_utc"] = health["last_completed_utc"]
    store.write_document("runtime_health", health)
    store.record_event("runtime_cycle", health)
    log("runtime_cycle", **health)
    # Carriles de candidatas (F4): después de cerrar el ciclo del piloto, en procesos y bases aparte.
    # Sin carriles activos no corre nada; un carril que falla no cambia el ciclo ya escrito.
    try:
        from .lanes import run_active
        for item in run_active(Path(store.path).parent.parent / "lanes", runner=runner, timeout=min(timeout, 600)):
            log("lane_cycle", **item)
    except Exception as exc:  # noqa: BLE001 - un carril nunca tumba el ciclo del piloto
        log("lane_cycle", status="error", detail=type(exc).__name__)
    # Public data collection has its own health and retry budget. It cannot
    # authorize trading or turn a healthy operational ledger into an error.
    try:
        result = runner([sys.executable, "-m", "lab.evidence", "--config", str(config), "--once"],
                        timeout=min(timeout, 240), capture_output=True, text=True, check=False)
        if result.returncode:
            previous_capture = store.read_document("evidence_collection", {}) or {}
            if previous_capture.get("status") not in {"error", "partial"}:
                store.write_document("evidence_collection", {"status": "error", "attempted_at_utc": utc_now(),
                                      "error": "collector_process_failed"})
    except (subprocess.TimeoutExpired, OSError) as exc:
        store.write_document("evidence_collection", {"status": "error", "attempted_at_utc": utc_now(),
                              "error": type(exc).__name__})
    return health


def readiness(health: dict | None, enabled: bool, *, now: dt.datetime | None = None) -> tuple[bool, str]:
    if not enabled:
        return False, "Ejecución desactivada; pendiente de migración o pausa manual"
    if not health or not health.get("last_success_utc"):
        return False, "Sin ciclo completo verificado"
    # A running cycle may retain the preceding success only within its bounded
    # freshness window. Missing/unknown/pending states never imply readiness.
    if health.get("status") not in {"ok", "running"}:
        return False, "El último ciclo no está sano"
    try:
        last = dt.datetime.fromisoformat(health["last_success_utc"])
        now = now or dt.datetime.now(dt.timezone.utc)
        if last.tzinfo is None:
            return False, "Heartbeat sin zona horaria"
        age = (now - last).total_seconds()
        limit = max(180, int(health.get("interval_seconds", 300)) * 2 + 60)
        if age < -60 or age > limit:
            return False, "Heartbeat vencido"
    except (ValueError, TypeError, OverflowError):
        return False, "Heartbeat inválido"
    return True, "Operación paper verificada"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ejecutor único Trading Lab, exclusivamente paper")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--cycle-timeout", type=int, default=900)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    data_dir = args.data_dir.resolve()
    database = data_dir / DATABASE_NAME
    try:
        if not database.is_file():
            raise ValueError("Importa el estado primero con lab.ops import-legacy")
        if not (data_dir / "worker.enabled").is_file():
            raise ValueError("El ejecutor permanece desactivado; completa el corte operativo primero")
        if args.cycle_timeout < 1:
            raise ValueError("Timeout inválido")
        with exclusive_lock(data_dir / "runtime.lock"):
            from .storage import SQLiteStore

            store = SQLiteStore(database)
            deployment = store.read_document("deployment", {}) or {}
            if deployment.get("mode") != "paper" or not deployment.get("imported_at_utc"):
                raise ValueError("Falta una importación paper verificada")
            config, _ = prepare_config(args.config, data_dir, args.interval)
            os.environ["TRADING_LAB_DATA_DIR"] = str(data_dir / "market-data")
            _STOP.clear()
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGTERM, signal.SIGINT):
                    signal.signal(sig, lambda *_: _STOP.set())
            log("runtime_started", status="paper", database=str(database))
            while not _STOP.is_set() and (data_dir / "worker.enabled").is_file():
                result = run_cycle(config, store, args.interval, timeout=args.cycle_timeout)
                if args.once:
                    return 0 if result["status"] == "ok" else 1
                _STOP.wait(args.interval)
            health = store.read_document("runtime_health", {}) or {}
            health.update(status="stopped", stopped_at_utc=utc_now())
            store.write_document("runtime_health", health)
            log("runtime_stopped", status="stopped")
            return 0
    except (ValueError, RuntimeError, OSError) as exc:
        log("runtime_refused", status="error", reason=redact(str(exc)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
