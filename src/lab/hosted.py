"""One authenticated API and one explicitly activated paper worker on a volume.

Railway: mount /data; use /data/runtime and /data/backups. Import/restore and
``lab.ops activate --cutover-confirmed`` remain separate operator actions. Both
its marker and TRADING_WORKER_ALLOWED=true are required to start the worker. This
supervisor never imports, activates, reads .env, or places orders itself.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import closing

from .runtime import DATABASE_NAME, exclusive_lock, log, redact, utc_now, validate_config

BACKUP_PATTERN = re.compile(r"hosted-\d{8}T\d{12}Z-[0-9a-f]{12}\.sqlite3\Z")
BROKER_CREDENTIALS = ("BITSO_API_KEY", "BITSO_API_SECRET", "ALPACA_KEY_ID", "ALPACA_SECRET_KEY")


def validate_paths(data_dir: Path, backup_dir: Path, *, environ=None, ismount=os.path.ismount):
    """Require a real persistent mount in Railway, including before any mkdir."""
    env = os.environ if environ is None else environ
    data, backups = data_dir.resolve(), backup_dir.resolve()
    if data == backups or data in backups.parents or backups in data.parents:
        raise ValueError("Los datos y respaldos requieren directorios separados")
    railway = any(env.get(key) for key in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID"))
    declared = env.get("RAILWAY_VOLUME_MOUNT_PATH")
    if railway or declared:
        if not declared or not Path(declared).is_absolute():
            raise ValueError("Railway requiere RAILWAY_VOLUME_MOUNT_PATH absoluto")
        mount = Path(declared).resolve()
        if not ismount(mount) or any(mount not in path.parents for path in (data, backups)):
            raise ValueError("Datos y respaldos deben estar dentro del volumen persistente montado")
    return data, backups


def validate_paper(config: Path, *, environ=None):
    env = os.environ if environ is None else environ
    if not config.is_file():
        raise ValueError("Falta la configuración paper explícita")
    if any(env.get(name) for name in BROKER_CREDENTIALS):
        raise ValueError("El servicio alojado inicial requiere simulación sin credenciales de brokers")
    # bot/realtime load this file if it exists; do not allow an implicit private
    # connection even when the supervisor's own environment is credential-free.
    from .data import ROOT
    if (ROOT / ".env").exists():
        raise ValueError("La imagen alojada no debe contener .env")
    from .bot import load_config
    cfg = load_config(config)
    validate_config(cfg)
    return cfg


def read_document(data_dir: Path, name: str, default=None):
    database = data_dir / DATABASE_NAME
    if not database.is_file():
        return default
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        # import-legacy creates the SQLite file before publishing its schema and
        # deployment marker. Keep the paused API alive through that small window.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'").fetchone():
            return default
        row = db.execute("SELECT payload FROM documents WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else default


def record_status(data_dir: Path, **fields):
    """Report errors without accidentally creating an unimported database."""
    log("hosted_status", **fields)
    try:
        deployment = read_document(data_dir, "deployment", {}) or {}
        if deployment.get("mode") != "paper" or not deployment.get("imported_at_utc"):
            return
        from .storage import SQLiteStore
        # Health must not hold shutdown hostage behind SQLite's normal 30s
        # writer timeout. Reuse the document format, never initialize a store.
        with closing(sqlite3.connect((data_dir / DATABASE_NAME).as_uri() + "?mode=rw", uri=True, timeout=.5)) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Esquema no reconocido para registrar salud")
            with db:
                db.execute("BEGIN IMMEDIATE")
                previous = SQLiteStore._read(db, "hosted_health", {}) or {}
                SQLiteStore._write(db, "hosted_health", {**previous, **fields, "updated_at_utc": utc_now()})
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        log("hosted_status_write_failed", reason=redact(str(exc)))


def perform_backup(data_dir: Path, backup_dir: Path, *, keep=7):
    """Verified SQLite snapshots; only verified files bearing our name are pruned."""
    from . import ops

    if keep < 1:
        raise ValueError("La retención debe conservar al menos un respaldo")
    backup_dir.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(backup_dir / "hosted-backup.lock"):
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = backup_dir / f"hosted-{stamp}-{uuid.uuid4().hex[:12]}.sqlite3"
        ops.backup(data_dir, path)
        verified = ops.verify_backup(path)
        candidates = []
        for candidate in backup_dir.iterdir():
            if not BACKUP_PATTERN.fullmatch(candidate.name) or candidate.is_symlink():
                continue
            manifest = candidate.with_suffix(candidate.suffix + ".manifest.json")
            if manifest.is_symlink():
                continue
            try:
                proof = ops.verify_backup(candidate)
                candidates.append((proof["created_at_utc"], candidate))
            except (OSError, ValueError, sqlite3.Error):
                # Preserve corrupt/incomplete evidence for inspection.
                continue
        for _, candidate in sorted(candidates, reverse=True)[keep:]:
            candidate.unlink()
            candidate.with_suffix(candidate.suffix + ".manifest.json").unlink()
            Path(str(candidate) + ".backup.lock").unlink(missing_ok=True)
        record_status(data_dir, backup_status="ok", last_backup_verified_utc=utc_now(),
                      backup_sha256=verified["sha256"], backup_error=None)
        return verified


def process_group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_processes(processes, *, grace=18.0):
    """Bounded stop of child sessions, including descendants after parent exit."""
    processes = [process for process in processes if process is not None]
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        for process in processes:
            process.poll()  # Reap direct children before probing the whole group.
        if not any(process_group_alive(process.pid) for process in processes):
            break
        time.sleep(min(.05, max(0, deadline - time.monotonic())))
    # A runtime can exit before a stubborn grandchild. Never use only poll() to
    # decide whether its group still needs SIGKILL.
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            log("hosted_child_stop_failed", pid=process.pid)


def start_child(command):
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True)


def supervise(config: Path, data_dir: Path, backup_dir: Path, *, port: int,
              interval=300, backup_interval=86400, stop=None, server_factory=None,
              spawn=start_child, poll_seconds=.5, shutdown_grace=18.0, environ=None):
    """Serve while paused; notice an explicit activation without redeploying."""
    from .service import make_server

    stop = stop if stop is not None else threading.Event()
    env = os.environ if environ is None else environ
    factory = server_factory or make_server
    server = factory(data_dir, host="0.0.0.0", port=port, config_path=config, require_auth=True)
    server.daemon_threads = True
    server.block_on_close = False
    api_error = []

    def serve():
        try:
            server.serve_forever(poll_interval=.1)
        except BaseException as exc:
            api_error.append(redact(str(exc)))

    thread = threading.Thread(target=serve, name="hosted-api", daemon=True)
    worker = backup = None
    next_backup = 0.0
    exit_code = 0
    thread.start()
    record_status(data_dir, status="paused", worker_status="paused")
    try:
        while not stop.is_set():
            if not thread.is_alive():
                record_status(data_dir, status="error", api_error=api_error[0] if api_error else "El servidor terminó inesperadamente")
                exit_code = 1
                break
            enabled = env.get("TRADING_WORKER_ALLOWED") == "true" and (data_dir / "worker.enabled").is_file()
            if worker is not None and not enabled:
                # Deactivation is a pause, not a redeploy. Do not add another
                # full shutdown grace if SIGTERM arrives during this operation.
                stop_processes([worker], grace=min(1.0, shutdown_grace))
                worker = None
                record_status(data_dir, status="paused", worker_status="paused")
            elif worker is not None and worker.poll() is not None:
                record_status(data_dir, status="error", worker_status="error", worker_returncode=worker.returncode)
                exit_code = 1
                break
            if worker is None and enabled:
                worker = spawn([sys.executable, "-m", "lab.runtime", "--config", str(config),
                                "--data-dir", str(data_dir), "--interval", str(interval)])
                record_status(data_dir, status="running", worker_status="running", worker_returncode=None)
            if backup is not None and backup.poll() is not None:
                failed = backup.returncode != 0
                record_status(data_dir, backup_status="error" if failed else "ok",
                              backup_error=f"Proceso de respaldo terminó con código {backup.returncode}" if failed else None)
                # Clean up a surviving descendant even after a failed parent.
                stop_processes([backup], grace=0)
                backup = None
                next_backup = time.monotonic() + (min(300, backup_interval) if failed else backup_interval)
            if backup is None and time.monotonic() >= next_backup:
                deployment = read_document(data_dir, "deployment", {}) or {}
                if deployment.get("mode") == "paper" and deployment.get("imported_at_utc"):
                    record_status(data_dir, status="running" if worker else "paused",
                                  worker_status="running" if worker else "paused")
                    # Every supervisor restart creates a fresh backup before relying
                    # on its own interval; no cached success is assumed.
                    backup = spawn([sys.executable, "-m", "lab.hosted", "--backup-once", "--config", str(config),
                                    "--data-dir", str(data_dir), "--backup-dir", str(backup_dir)])
            stop.wait(poll_seconds)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        record_status(data_dir, status="error", supervisor_error=redact(str(exc)))
        exit_code = 1
    finally:
        stop_processes([worker, backup], grace=shutdown_grace)
        # shutdown() deadlocks if serve_forever exited before setting its internal
        # event; invoke it in a bounded daemon thread and still close the socket.
        if thread.is_alive():
            shutdown = threading.Thread(target=server.shutdown, daemon=True)
            shutdown.start()
            shutdown.join(timeout=1)
        server.server_close()
        thread.join(timeout=1)
        record_status(data_dir, status="stopped" if not exit_code else "error", worker_status="stopped")
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/app/config.yaml"))
    parser.add_argument("--data-dir", type=Path, default=Path("/data/runtime"))
    parser.add_argument("--backup-dir", type=Path, default=Path("/data/backups"))
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--backup-interval", type=int, default=86400)
    parser.add_argument("--backup-once", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = args.config.resolve()
        validate_paper(config)
        data, backups = validate_paths(args.data_dir, args.backup_dir)
        if not 60 <= args.interval <= 3600 or args.backup_interval < 60:
            raise ValueError("Intervalo operativo o de respaldo inválido")
        port = int(os.environ.get("PORT", "8080"))
        if not 1 <= port <= 65535:
            raise ValueError("PORT inválido")
        data.mkdir(parents=True, exist_ok=True)
        backups.mkdir(parents=True, exist_ok=True)
        if args.backup_once:
            try:
                perform_backup(data, backups)
                return 0
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                record_status(data, backup_status="error", backup_error=redact(str(exc)))
                return 1
        stop = threading.Event()
        previous = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
        try:
            with exclusive_lock(data / "hosted.lock"):
                return supervise(config, data, backups, port=port, interval=args.interval,
                                 backup_interval=args.backup_interval, stop=stop)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        log("hosted_refused", reason=redact(str(exc)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
