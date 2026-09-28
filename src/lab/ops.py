"""Explicit local import, consistent backups, verification and safe restore.

These commands never authenticate to GCP or place broker orders.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import tempfile

from .runtime import DATABASE_NAME, exclusive_lock, utc_now

# Contrato de SQLiteStore v1. Un cambio de esquema exige migración y revisión aquí.
SUPPORTED_SCHEMA_VERSION = 1
_RECORD_COLUMNS = [("id", "TEXT", 0, 1), ("payload", "TEXT", 1, 0), ("created_at", "TEXT", 1, 0)]
SCHEMA_V1 = {
    "documents": [("name", "TEXT", 0, 1), ("payload", "TEXT", 1, 0), ("updated_at", "TEXT", 1, 0)],
    "trades": _RECORD_COLUMNS, "equity": _RECORD_COLUMNS, "live_equity": _RECORD_COLUMNS,
    "orders": [("id", "TEXT", 0, 1), ("namespace", "TEXT", 1, 0), ("status", "TEXT", 1, 0),
               ("terminal", "INTEGER", 1, 0), ("payload", "TEXT", 1, 0), ("updated_at", "TEXT", 1, 0)],
    "events": [("id", "INTEGER", 0, 1), ("kind", "TEXT", 1, 0), ("payload", "TEXT", 1, 0),
               ("created_at", "TEXT", 1, 0)],
}
LEGACY_FILES = {"state.json", "snapshot.json", "live.json", "trades.csv", "equity.csv", "live_equity.csv"}


def validate_database(path: Path, *, expected_version: int = SUPPORTED_SCHEMA_VERSION,
                      standalone: bool = False) -> int:
    """Inspección de solo lectura antes de abrir SQLiteStore (que puede crear tablas)."""
    path = Path(path).resolve()
    if standalone:
        for suffix in ("-wal", "-journal"):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists() and sidecar.stat().st_size:
                raise ValueError("El respaldo no es autónomo: contiene WAL/journal externo")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite no pasó integrity_check")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != expected_version or version != SUPPORTED_SCHEMA_VERSION:
            raise ValueError("Versión de esquema SQLite no soportada o distinta del manifiesto")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables != set(SCHEMA_V1):
            raise ValueError("Esquema de Trading Lab incompleto o desconocido")
        for table, expected in SCHEMA_V1.items():
            columns = [(r[1], r[2].upper(), r[3], r[5]) for r in db.execute(f"PRAGMA table_info({table})")]
            if columns != expected:
                raise ValueError(f"Esquema incompatible en {table}")
        index = [r[2] for r in db.execute("PRAGMA index_info(orders_pending)")]
        if index != ["namespace", "terminal"]:
            raise ValueError("Falta el índice operativo de órdenes")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone():
            raise ValueError("El esquema contiene vistas o triggers no soportados")
    return version


def _reserve(path: Path) -> int:
    """Reserva atómica; rechaza archivos y symlinks preexistentes."""
    try:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"El destino ya existe; no se sobrescribe: {path.name}") from exc


def validate_legacy_paper(source: Path) -> None:
    state = json.loads((source / "state.json").read_text())
    sleeves = state.get("sleeves") if isinstance(state, dict) else None
    if not isinstance(sleeves, dict) or not sleeves:
        raise ValueError("El estado no contiene bloques válidos")
    for name, sleeve in sleeves.items():
        if not isinstance(sleeve, dict) or sleeve.get("mode") != "paper":
            raise ValueError("Solo se admite migración paper explícita")
        if "sleeve" in sleeve and sleeve["sleeve"] != name:
            raise ValueError("El identificador sleeve del estado es inconsistente")
    for filename in ("state.json", "snapshot.json", "live.json"):
        path = source / filename
        if not path.exists():
            continue
        document = json.loads(path.read_text())
        if not isinstance(document, dict) or ("mode" in document and document["mode"] != "paper"):
            raise ValueError(f"{filename} no es un documento paper")
        if "sleeves" in document:
            blocks = document["sleeves"]
            if not isinstance(blocks, dict):
                raise ValueError(f"Bloques inválidos en {filename}")
            for name, block in blocks.items():
                if name not in sleeves or not isinstance(block, dict):
                    raise ValueError(f"Bloque desconocido en {filename}")
                if "mode" in block and block["mode"] != "paper":
                    raise ValueError(f"Bloque no paper en {filename}")
                if "sleeve" in block and block["sleeve"] != name:
                    raise ValueError(f"Identificador sleeve inconsistente en {filename}")
    for filename in ("trades.csv", "equity.csv", "live_equity.csv"):
        path = source / filename
        if not path.exists():
            continue
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                if "mode" in row and row["mode"] != "paper":
                    raise ValueError(f"Fila no paper en {filename}")
                if "sleeve" in row and row["sleeve"] not in sleeves:
                    raise ValueError(f"Bloque desconocido en {filename}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temp.chmod(0o600)
    temp.replace(path)


def open_store(data_dir: Path):
    from .storage import SQLiteStore

    path = data_dir / DATABASE_NAME
    if not path.is_file():
        raise ValueError("No existe una base importada")
    validate_database(path)
    return SQLiteStore(path)


def inspect(data_dir: Path) -> dict:
    store = open_store(data_dir)
    return {"database": str(data_dir / DATABASE_NAME), "health": store.health(),
            "deployment": store.read_document("deployment", {}),
            "runtime": store.read_document("runtime_health", {}),
            "worker_enabled": (data_dir / "worker.enabled").is_file()}


def import_legacy(source: Path, data_dir: Path) -> dict:
    from .storage import SQLiteStore

    if source.resolve() == data_dir.resolve():
        raise ValueError("Importa a un directorio nuevo, separado del estado original")
    database = data_dir / DATABASE_NAME
    with exclusive_lock(data_dir / "runtime.lock"), exclusive_lock(Path(str(database) + ".execution.lock")):
        if database.exists():
            raise ValueError("El destino ya contiene una base; no se sobrescribe")
        source_files = sorted(p for p in source.iterdir() if p.name in LEGACY_FILES)
        with tempfile.TemporaryDirectory(prefix=".import-", dir=data_dir) as temporary:
            frozen = Path(temporary)
            hashes = {}
            for path in source_files:
                payload = path.read_bytes()
                (frozen / path.name).write_bytes(payload)
                hashes[path.name] = hashlib.sha256(payload).hexdigest()
            validate_legacy_paper(frozen)
            store = SQLiteStore(database)
            try:
                result = store.import_legacy(frozen)
                current_names = {p.name for p in source.iterdir() if p.name in LEGACY_FILES}
                if current_names != set(hashes) or any(sha256(p) != hashes[p.name] for p in source_files):
                    raise ValueError("El origen cambió durante la importación; usa una copia congelada")
                deployment = {"mode": "paper", "imported_at_utc": utc_now(),
                              "source_sha256": hashes, "import_summary": result,
                              "target_owner": "brandonmuro.work@gmail.com",
                              "cloud_connected": False}
                store.write_document("deployment", deployment)
                store.record_event("legacy_import", deployment)
                database.chmod(0o600)
                return deployment
            except Exception:
                # Preserve evidence, but runtime refuses without deployment marker.
                store.record_event("legacy_import_failed", {"time_utc": utc_now()})
                raise


def backup(data_dir: Path, destination: Path) -> dict:
    store = open_store(data_dir)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
    with exclusive_lock(Path(str(destination) + ".backup.lock")):
        if destination.exists() or manifest_path.exists():
            raise ValueError("El respaldo ya existe; elige otro nombre")
        os.close(_reserve(destination))
        with os.fdopen(_reserve(manifest_path), "w") as manifest_stream:
            # Conexiones cerradas explícitamente: `with sqlite3.connect` solo confirma transacciones.
            with closing(sqlite3.connect(store.path.resolve().as_uri() + "?mode=ro", uri=True)) as src, \
                    closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
            schema_version = validate_database(destination, standalone=True)
            manifest = {"format": "trading-lab-sqlite-backup-v1", "created_at_utc": utc_now(),
                        "file": destination.name, "sha256": sha256(destination),
                        "bytes": destination.stat().st_size, "schema_version": schema_version,
                        "build_id": os.environ.get("TRADING_LAB_BUILD_ID", "local-uncommitted")}
            manifest_stream.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            manifest_stream.flush()
            os.fsync(manifest_stream.fileno())
        store.write_document("last_backup", manifest)
        return manifest


def verify_backup(source: Path) -> dict:
    source = source.resolve()
    manifest_path = source.with_suffix(source.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or manifest.get("format") != "trading-lab-sqlite-backup-v1":
        raise ValueError("Formato de respaldo desconocido")
    if manifest.get("sha256") != sha256(source) or manifest.get("bytes") != source.stat().st_size:
        raise ValueError("El SHA256 o tamaño no coincide; no se restaura")
    if manifest.get("file") != source.name:
        raise ValueError("El nombre del respaldo no coincide con el manifiesto")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        raise ValueError("Versión de esquema del manifiesto no soportada")
    validate_database(source, expected_version=manifest["schema_version"], standalone=True)
    return manifest


def restore(source: Path, data_dir: Path) -> dict:
    source = source.resolve()
    database = data_dir / DATABASE_NAME
    with exclusive_lock(data_dir / "runtime.lock"), exclusive_lock(Path(str(database) + ".execution.lock")), \
            exclusive_lock(Path(str(source) + ".backup.lock")):
        manifest = verify_backup(source)
        if database.exists() or (data_dir / "worker.enabled").exists():
            raise ValueError("Restaurar requiere un destino vacío y desactivado")
        partial = database.with_suffix(".restore.tmp")
        if partial.exists():
            raise ValueError("Ya hay una restauración parcial; inspecciónala antes de continuar")
        with source.open("rb") as src, os.fdopen(_reserve(partial), "wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        # Copia de bytes de un backup autónomo: debe corresponder exactamente al archivo validado.
        if (sha256(partial) != manifest["sha256"] or partial.stat().st_size != manifest["bytes"]
                or sha256(source) != manifest["sha256"]):
            raise ValueError("El respaldo cambió durante la copia; no se publica la restauración")
        validate_database(partial, expected_version=manifest["schema_version"], standalone=True)
        # link crea el nombre final sin reemplazar un destino creado por otro proceso.
        try:
            os.link(partial, database)
        except FileExistsError as exc:
            raise ValueError("El destino ya existe; no se sobrescribe") from exc
        partial.unlink()
        store = open_store(data_dir)
        store.write_document("runtime_health", {"status": "stopped", "last_success_utc": None,
                                                "restored_at_utc": utc_now()})
        store.record_event("restore", {"time_utc": utc_now(), "source_sha256": manifest["sha256"]})
        return {"restored": str(database), "worker_enabled": False, "source_sha256": manifest["sha256"]}


def activate(data_dir: Path, confirmed: bool) -> dict:
    if not confirmed:
        raise ValueError("Confirma el corte de todos los ejecutores anteriores con --cutover-confirmed")
    with exclusive_lock(data_dir / "runtime.lock"):
        store = open_store(data_dir)
        deployment = store.read_document("deployment", {}) or {}
        if deployment.get("mode") != "paper" or not deployment.get("imported_at_utc"):
            raise ValueError("No hay importación paper verificada")
        state = store.read_document("state", {}) or {}
        if not state.get("sleeves") or any(s.get("mode") != "paper" for s in state["sleeves"].values()):
            raise ValueError("El estado no es exclusivamente paper")
        health = store.health()
        if health.get("integrity") != "ok":
            raise ValueError("La integridad de SQLite no permite activar el ejecutor")
        if health.get("unknown_orders", 0) or health.get("pending_orders", 0):
            raise ValueError("Hay órdenes pendientes; concilia antes de activar")
        write_json(data_dir / "worker.enabled", {"activated_at_utc": utc_now(), "mode": "paper",
                                                "cutover_confirmed": True})
        store.record_event("runtime_activated", {"time_utc": utc_now(), "mode": "paper"})
        return {"worker_enabled": True, "mode": "paper"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "import-legacy", "backup", "restore", "activate", "deactivate"):
        p = sub.add_parser(command)
        p.add_argument("--data-dir", type=Path, required=True)
        if command in {"import-legacy", "restore"}:
            p.add_argument("--source", type=Path, required=True)
        if command == "backup":
            p.add_argument("--destination", type=Path, required=True)
        if command == "activate":
            p.add_argument("--cutover-confirmed", action="store_true")
    verify = sub.add_parser("verify-backup")
    verify.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data_dir = args.data_dir.resolve() if hasattr(args, "data_dir") else None
        if args.command == "inspect":
            result = inspect(data_dir)
        elif args.command == "import-legacy":
            result = import_legacy(args.source.resolve(), data_dir)
        elif args.command == "backup":
            result = backup(data_dir, args.destination.resolve())
        elif args.command == "restore":
            result = restore(args.source.resolve(), data_dir)
        elif args.command == "verify-backup":
            result = verify_backup(args.source.resolve())
        elif args.command == "activate":
            result = activate(data_dir, args.cutover_confirmed)
        else:
            (data_dir / "worker.enabled").unlink(missing_ok=True)
            result = {"worker_enabled": False, "note": "La corrida en curso debe terminar antes del corte"}
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
