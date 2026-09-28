"""Offline backups of isolated forward-paper evidence; never runs a strategy.

Bundles contain a consistent SQLite snapshot plus frozen input files. Restore
preserves the original experiment/code/preregistration and never enables a job.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from .aggressive_plan import EXPERIMENT_IDS, isolated_directory
from .experiments import ResearchGateError, canonical_hash
from .storage import execution_lock

DB_NAME = "comparison.sqlite3"
IDENTITY = "isolated-paired-paper-v1"
BUNDLE_TYPE = "paired-paper-backup-v1"
BLOCKS = ("crypto", "stocks")
SLEEVES = {f"{role}.{block}" for role in ("control", "aggressive") for block in BLOCKS}


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def _path(path):
    original = Path(path).absolute()
    if any(item.is_symlink() for item in (original, *original.parents)):
        raise ResearchGateError("no se admiten enlaces simbólicos en rutas de comparación")
    return isolated_directory(original)


def _file(path):
    if path.is_symlink() or not path.is_file():
        raise ResearchGateError("falta un archivo regular de evidencia")


@contextmanager
def _read_db(path):
    _file(path)
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ResearchGateError("versión SQLite no soportada para este respaldo")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ResearchGateError("integridad SQLite inválida")
        yield db
    finally:
        db.close()


def _doc(db, name, default=None):
    row = db.execute("SELECT payload FROM documents WHERE name=?", (name,)).fetchone()
    return json.loads(row[0]) if row else default


def _identity(db):
    manifest = _doc(db, "comparison_manifest", {})
    if not isinstance(manifest, dict) or not isinstance(manifest.get("plan"), dict):
        raise ResearchGateError("manifiesto de comparación inválido")
    proof = manifest.get("preregistration", {})
    if not isinstance(proof, dict):
        raise ResearchGateError("prueba de preregistro inválida")
    if (manifest.get("type") != IDENTITY or manifest.get("experiment_id") not in EXPERIMENT_IDS
            or manifest.get("mode") != "paper" or manifest.get("live_authorized") is not False
            or manifest["plan"].get("experiment_id") != manifest["experiment_id"]
            or manifest.get("config_sha256") != canonical_hash(manifest.get("plan"))
            or manifest.get("code_commit") != proof.get("code_commit")
            or not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("code_commit", "")))
            or not re.fullmatch(r"[0-9a-f]{40}", str(proof.get("commit", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(proof.get("sha256", "")))
            or not manifest.get("run_id")):
        raise ResearchGateError("identidad/plan/preregistro de comparación inválidos")
    state = _doc(db, "state", {})
    if (state.get("mode") != "paper" or set(state.get("sleeves", {})) != SLEEVES
            or any(sleeve.get("mode") != "paper" or "ledger" not in sleeve or "account_namespace" in sleeve
                   for sleeve in state["sleeves"].values())
            or _doc(db, "deployment") is not None
            or db.execute("SELECT count(*) FROM documents WHERE name LIKE 'ledger:%'").fetchone()[0]
            or db.execute("SELECT count(*) FROM orders").fetchone()[0]):
        raise ResearchGateError("la base contiene estado operativo o cuentas externas")
    report = _doc(db, "comparison", {})
    if report and (report.get("experiment_id") != manifest["experiment_id"]
                   or report.get("run_id") != manifest["run_id"]
                   or report.get("mode") != "paper" or report.get("live_authorized") is not False):
        raise ResearchGateError("resultado y manifiesto no corresponden")
    return manifest


def _required_inputs(db):
    required = {}
    for capture in _doc(db, "comparison_inputs", {}).values():
        required[capture["file"]] = capture["sha256"]
    # Historical ticks retain the exact input hashes, even after latest input changed.
    for tick in _doc(db, "comparison_ticks", {}).values():
        for block in BLOCKS:
            digest = tick["hashes"][block]
            required[f"inputs/{block}-{digest}.csv"] = digest
    for name, digest in required.items():
        if (not re.fullmatch(r"inputs/(crypto|stocks)-[0-9a-f]{64}\.csv", name)
                or not re.fullmatch(r"[0-9a-f]{64}", str(digest))
                or not name.endswith(f"-{digest}.csv")):
            raise ResearchGateError("ruta/hash de captura inválidos")
    return required


def _input_hashes(path, required):
    inputs = path / "inputs"
    found = {}
    if inputs.exists():
        if inputs.is_symlink() or not inputs.is_dir():
            raise ResearchGateError("directorio de capturas inválido")
        for child in inputs.iterdir():
            name = child.relative_to(path).as_posix()
            if not re.fullmatch(r"inputs/(crypto|stocks)-[0-9a-f]{64}\.csv", name):
                raise ResearchGateError("archivo inesperado en capturas")
            _file(child)
            digest = _hash(child)
            if not name.endswith(f"-{digest}.csv"):
                raise ResearchGateError("una captura congelada fue modificada")
            found[name] = digest
    if any(found.get(name) != digest for name, digest in required.items()):
        raise ResearchGateError("falta una captura referenciada por la base")
    return found


def _summary(db, manifest):
    return {"experiment_id": manifest["experiment_id"], "run_id": manifest["run_id"],
            "config_sha256": manifest["config_sha256"], "code_commit": manifest["code_commit"],
            "preregistration": manifest["preregistration"], "mode": "paper", "live_authorized": False,
            "counts": {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                       for table in ("documents", "trades", "equity", "orders", "events")},
            "health": _doc(db, "comparison_health", {}),
            "observations": len(_doc(db, "comparison_history", []))}


def inspect(data_dir: Path) -> dict:
    path = _path(data_dir)
    _file(path / DB_NAME)
    with execution_lock(path / "comparison"), _read_db(path / DB_NAME) as db:
        manifest = _identity(db)
        inputs = _input_hashes(path, _required_inputs(db))
        return {**_summary(db, manifest), "frozen_inputs": len(inputs)}


def _write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def _fsync(path):
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup(data_dir: Path, destination: Path) -> dict:
    source, destination = _path(data_dir), _path(destination)
    _file(source / DB_NAME)
    if destination == source or source in destination.parents or destination in source.parents:
        raise ResearchGateError("el respaldo debe quedar fuera del directorio de comparación")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with execution_lock(source / "comparison"), execution_lock(destination.parent / (destination.name + ".backup")):
        if destination.exists():
            raise ResearchGateError("el destino del respaldo ya existe")
        with tempfile.TemporaryDirectory(prefix=".paper-backup-", dir=destination.parent) as temporary:
            staged = Path(temporary) / "bundle"
            staged.mkdir(mode=0o700)
            with _read_db(source / DB_NAME) as db:
                manifest = _identity(db)
                inputs = _input_hashes(source, _required_inputs(db))
                target = sqlite3.connect(staged / DB_NAME)
                try:
                    db.backup(target)
                    target.execute("PRAGMA journal_mode=DELETE")
                finally:
                    target.close()
                summary = _summary(db, manifest)
            for name, digest in inputs.items():
                target = staged / name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(source / name, target)
                if _hash(target) != digest:
                    raise ResearchGateError("la captura cambió durante el respaldo")
                target.chmod(0o600)
                _fsync(target)
            (staged / DB_NAME).chmod(0o600)
            _fsync(staged / DB_NAME)
            record = {"type": BUNDLE_TYPE, "created_at": _utc(), "summary": summary,
                      "files": {DB_NAME: _hash(staged / DB_NAME), **inputs}}
            _write_json(staged / "manifest.json", record)
            verify_backup(staged)
            if (staged / "inputs").is_dir():
                _fsync_dir(staged / "inputs")
            _fsync_dir(staged)
            os.rename(staged, destination)
            _fsync_dir(destination.parent)
    return {"bundle": str(destination), **record}


def verify_backup(bundle: Path) -> dict:
    path = _path(bundle)
    _file(path / "manifest.json")
    record = json.loads((path / "manifest.json").read_text())
    if record.get("type") != BUNDLE_TYPE or not isinstance(record.get("files"), dict) or DB_NAME not in record["files"]:
        raise ResearchGateError("manifiesto de respaldo inválido")
    actual = set()
    for child in path.iterdir():
        if child.name == "inputs" and child.is_dir() and not child.is_symlink():
            actual.update("inputs/" + entry.name for entry in child.iterdir())
        elif child.name != "manifest.json":
            actual.add(child.name)
    if actual != set(record["files"]):
        raise ResearchGateError("el bundle tiene archivos faltantes o inesperados")
    for name, digest in record["files"].items():
        if name != DB_NAME and not re.fullmatch(r"inputs/(crypto|stocks)-[0-9a-f]{64}\.csv", name):
            raise ResearchGateError("ruta de respaldo inválida")
        _file(path / name)
        if _hash(path / name) != digest:
            raise ResearchGateError("hash del respaldo no coincide")
    with _read_db(path / DB_NAME) as db:
        summary = _summary(db, _identity(db))
        _input_hashes(path, _required_inputs(db))
        if summary != record.get("summary"):
            raise ResearchGateError("identidad/conteos del respaldo no coinciden")
    return {"verified": True, **record}


def restore(bundle: Path, data_dir: Path) -> dict:
    source, destination = _path(bundle), _path(data_dir)
    if destination == source or source in destination.parents or destination in source.parents:
        raise ResearchGateError("restaurar exige otro directorio dedicado")
    verified = verify_backup(source)
    destination.mkdir(parents=True, exist_ok=True)
    with execution_lock(destination / "comparison"):
        if any(child.name != "comparison.execution.lock" for child in destination.iterdir()):
            raise ResearchGateError("restaurar exige un destino vacío y desactivado")
        with tempfile.TemporaryDirectory(prefix=".paper-restore-", dir=destination.parent) as temporary:
            staged = Path(temporary) / "bundle"
            shutil.copytree(source, staged, symlinks=True)
            # Revalidate the copied bytes: a concurrent change cannot reach destination.
            verified_copy = verify_backup(staged)
            if verified_copy != verified:
                raise ResearchGateError("el respaldo cambió durante la restauración")
            for name in verified_copy["files"]:
                _fsync(staged / name)
            result = {"restored_at": _utc(), "backup_manifest_sha256": _hash(staged / "manifest.json"),
                      "summary": verified["summary"], "scheduled": False, "live_authorized": False}
            if (staged / "inputs").exists():
                _fsync_dir(staged / "inputs")
                os.rename(staged / "inputs", destination / "inputs")
            _write_json(destination / "restore.json", result)
            _fsync_dir(destination)
            # Install DB last. A crash before here leaves no resumable comparison;
            # the runner rejects a nonempty directory without its database.
            os.rename(staged / DB_NAME, destination / DB_NAME)
            _fsync(destination / DB_NAME)
            _fsync_dir(destination)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "backup", "restore", "verify-backup"):
        command = commands.add_parser(name)
        if name != "verify-backup":
            command.add_argument("--data-dir", type=Path, required=True)
        if name == "backup":
            command.add_argument("--output", type=Path, required=True)
        if name in ("restore", "verify-backup"):
            command.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect(args.data_dir)
        elif args.command == "backup":
            result = backup(args.data_dir, args.output)
        elif args.command == "restore":
            result = restore(args.backup, args.data_dir)
        else:
            result = verify_backup(args.backup)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error, KeyError, TypeError) as exc:
        print(f"Operación paper bloqueada: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
