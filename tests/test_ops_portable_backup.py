"""Backups portables reales; datos sintéticos y permisos del sistema operativo."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from threading import Event

import pytest

from lab import ops
from lab.runtime import DATABASE_NAME
from lab.storage import SQLiteStore


@pytest.fixture
def imported(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    state = {"sleeves": {"crypto": {"mode": "paper", "capital_base": 500,
             "peak": 500, "ledger": {"cash": 400, "positions": {"BTC": 1}},
             "last_candle": "2026-09-26"}}}
    snapshot = {"mode": "paper", "sleeves": {"crypto": {"mode": "paper", "equity": 500}}}
    for name, value in {"state": state, "snapshot": snapshot, "live": snapshot}.items():
        (legacy / f"{name}.json").write_text(json.dumps(value))
    (legacy / "trades.csv").write_text("sleeve,mode,asset,side,qty,price,status\ncrypto,paper,BTC,buy,1,100,filled\n")
    (legacy / "equity.csv").write_text("date,sleeve,mode,equity,cash\n2026-09-26,crypto,paper,500,400\n")
    target = tmp_path / "runtime"
    ops.import_legacy(legacy, target)
    return target


def _readonly_verify_in_child(source):
    """Root must drop privilege too: chmod alone is not a readonly test as root."""
    reader, writer = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(reader)
        try:
            if os.geteuid() == 0:
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
            try:
                (source.parent / "write-probe").write_text("must fail")
            except PermissionError:
                pass
            else:
                raise AssertionError("El directorio sigue siendo escribible")
            result = {"sha256": ops.verify_backup(source)["sha256"]}
        except BaseException as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        os.write(writer, json.dumps(result).encode())
        os.close(writer)
        os._exit(0)
    os.close(writer)
    with os.fdopen(reader) as stream:
        result = json.load(stream)
    _, status = os.waitpid(child, 0)
    assert status == 0
    assert "error" not in result, result
    return result


def test_downloaded_pair_verifies_without_sidecars_or_write_permission(imported, tmp_path):
    original = tmp_path / "backup.sqlite3"
    manifest = ops.backup(imported, original)
    with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    with closing(sqlite3.connect(imported / DATABASE_NAME)) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    # /tmp es atravesable por el hijo sin privilegios aunque pytest corra como root.
    # Copiar sólo estos dos archivos reproduce una descarga de GCS a un volumen RO.
    with tempfile.TemporaryDirectory(prefix="trading-backup-ro-", dir="/tmp") as name:
        downloaded = Path(name)
        for file in (original, original.with_suffix(".sqlite3.manifest.json")):
            copy = downloaded / file.name
            shutil.copyfile(file, copy)
            copy.chmod(0o444)
        expected_files = sorted(path.name for path in downloaded.iterdir())
        downloaded.chmod(0o555)
        try:
            result = _readonly_verify_in_child(downloaded / original.name)
            assert result["sha256"] == manifest["sha256"]
            assert sorted(path.name for path in downloaded.iterdir()) == expected_files
            assert ops.sha256(downloaded / original.name) == manifest["sha256"]
        finally:
            downloaded.chmod(0o700)


def test_backup_snapshots_committed_wal_during_write_and_restores_every_ledger(imported, tmp_path, monkeypatch):
    store = SQLiteStore(imported / DATABASE_NAME)
    store.commit_live({"mode": "paper", "observation": "committed"},
                      [{"time_utc": "2026-09-27T01:00:00Z", "sleeve": "crypto", "mode": "paper", "equity": 501}])
    expected_documents = {name: store.read_document(name) for name in ("state", "snapshot", "live", "deployment")}
    expected_rows = {table: store.rows(table) for table in ("trades", "equity", "live_equity")}
    destination = tmp_path / "concurrent.sqlite3"
    source_opened, allow_copy, copied = Event(), Event(), Event()
    real_open, real_validate = ops.open_store, ops.validate_database

    def open_before_writer(data_dir):
        opened = real_open(data_dir)
        source_opened.set()
        assert allow_copy.wait(10), "No se inició la escritura concurrente"
        return opened

    def record_copy(path, **kwargs):
        result = real_validate(path, **kwargs)
        if Path(path) == destination:
            copied.set()
        return result

    monkeypatch.setattr(ops, "open_store", open_before_writer)
    monkeypatch.setattr(ops, "validate_database", record_copy)
    with closing(sqlite3.connect(store.path)) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        # Mantener abierta esta conexión conserva frames WAL comprometidos.
        writer.execute("UPDATE documents SET updated_at='committed-in-wal' WHERE name='state'")
        writer.commit()
        assert Path(str(store.path) + "-wal").stat().st_size > 0
        future = pool.submit(ops.backup, imported, destination)
        try:
            assert source_opened.wait(10)
            writer.execute("BEGIN IMMEDIATE")
            changed = json.loads(json.dumps(expected_documents["state"]))
            changed["sleeves"]["crypto"]["ledger"] = {"cash": 300, "positions": {"BTC": 2}}
            writer.execute("UPDATE documents SET payload=? WHERE name='state'", (json.dumps(changed),))
            writer.execute("INSERT INTO trades VALUES(?,?,?)", ("new-inflight", json.dumps({"asset": "BTC", "qty": 1}), "now"))
            allow_copy.set()
            assert copied.wait(10), "El backup no pudo leer una instantánea durante la transacción WAL"
            writer.commit()
            manifest = future.result(timeout=10)
        finally:
            writer.rollback()
            allow_copy.set()
        assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    monkeypatch.setattr(ops, "open_store", real_open)
    assert store.read_document("state") == changed
    assert len(store.rows("trades")) == len(expected_rows["trades"]) + 1
    assert ops.verify_backup(destination)["sha256"] == manifest["sha256"]
    with closing(sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)) as snapshot:
        assert snapshot.execute("SELECT updated_at FROM documents WHERE name='state'").fetchone()[0] == "committed-in-wal"
    restored_dir = tmp_path / "restored"
    ops.restore(destination, restored_dir)
    restored = SQLiteStore(restored_dir / DATABASE_NAME)
    for name, expected in expected_documents.items():
        assert restored.read_document(name) == expected
    for table, expected in expected_rows.items():
        assert restored.rows(table) == expected
    assert restored.read_document("runtime_health")["last_success_utc"] is None
    assert not (restored_dir / "worker.enabled").exists()
    # Restaurar no revierte ni adopta la transacción más reciente del origen.
    assert store.read_document("state") == changed
