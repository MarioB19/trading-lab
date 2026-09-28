"""Pruebas offline de importación, respaldo y restauración; solo directorios temporales."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from threading import Barrier
from types import SimpleNamespace

import pytest

from lab import ops
from lab.runtime import DATABASE_NAME
from lab.storage import SQLiteStore


@pytest.fixture
def legacy(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "state.json").write_text(json.dumps({"sleeves": {"crypto": {
        "mode": "paper", "ledger": {"cash": 500, "positions": {}}, "capital_base": 500}}}))
    # Los documentos legacy válidos pueden omitir los campos mode opcionales.
    (source / "snapshot.json").write_text(json.dumps({"sleeves": {"crypto": {"status": "ok"}}}))
    (source / "live.json").write_text(json.dumps({"mode": "paper", "sleeves": {"crypto": {"status": "ok"}}}))
    (source / "trades.csv").write_text("sleeve,mode,asset,qty,price\ncrypto,paper,BTC,1,100\n")
    (source / "equity.csv").write_text("date,sleeve,mode,equity\n2026-09-27,crypto,paper,500\n")
    return source


@pytest.fixture
def saved(legacy, tmp_path):
    directory = tmp_path / "runtime"
    ops.import_legacy(legacy, directory)
    backup = tmp_path / "backup.sqlite3"
    ops.backup(directory, backup)
    return directory, backup


def _rehash(path, **overrides):
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    manifest.update(sha256=ops.sha256(path), bytes=path.stat().st_size, **overrides)
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("damage", ["future_version", "missing_table", "wrong_column", "missing_index"])
def test_verify_rejects_incompatible_schema_even_with_matching_hash(saved, damage):
    _, backup = saved
    with closing(sqlite3.connect(backup)) as db:
        if damage == "future_version":
            db.execute("PRAGMA user_version=2")
        elif damage == "missing_table":
            db.execute("DROP TABLE trades")
        elif damage == "wrong_column":
            db.execute("ALTER TABLE trades RENAME COLUMN payload TO wrong")
        else:
            db.execute("DROP INDEX orders_pending")
        db.commit()
    _rehash(backup)
    with pytest.raises(ValueError, match="esquema|Esquema|índice"):
        ops.verify_backup(backup)
    if damage == "future_version":
        with closing(sqlite3.connect(backup)) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_manifest_schema_and_external_wal_rejected(saved):
    _, backup = saved
    _rehash(backup, schema_version=2)
    with pytest.raises(ValueError, match="manifiesto"):
        ops.verify_backup(backup)
    _rehash(backup, schema_version=1)
    Path(str(backup) + "-wal").write_bytes(b"external-data")
    with pytest.raises(ValueError, match="WAL"):
        ops.verify_backup(backup)


def test_backup_destination_is_reserved_against_concurrent_overwrite(legacy, tmp_path):
    directory = tmp_path / "runtime"
    ops.import_legacy(legacy, directory)
    destination = tmp_path / "concurrent.sqlite3"
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=5)
        try:
            return "ok", ops.backup(directory, destination)
        except (ValueError, RuntimeError) as exc:
            return "refused", str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(status for status, _ in results) == ["ok", "refused"]
    winner = next(value for status, value in results if status == "ok")
    assert ops.verify_backup(destination)["sha256"] == winner["sha256"]


def test_restore_rejects_source_changed_during_copy(saved, tmp_path, monkeypatch):
    _, backup = saved
    real_copy = ops.shutil.copyfileobj
    target = tmp_path / "restored"

    def altered(src, dst):
        real_copy(src, dst)
        with backup.open("ab") as stream:
            stream.write(b"changed-after-validation")

    monkeypatch.setattr(ops.shutil, "copyfileobj", altered)
    with pytest.raises(ValueError, match="cambió"):
        ops.restore(backup, target)
    assert not (target / DATABASE_NAME).exists()
    assert (target / DATABASE_NAME).with_suffix(".restore.tmp").exists()
    assert not (target / "worker.enabled").exists()


def test_restore_publication_never_overwrites_racing_destination(saved, tmp_path, monkeypatch):
    _, backup = saved
    real_copy = ops.shutil.copyfileobj
    target = tmp_path / "restored"

    def racing_writer(src, dst):
        real_copy(src, dst)
        (target / DATABASE_NAME).write_bytes(b"someone-elses-data")

    monkeypatch.setattr(ops.shutil, "copyfileobj", racing_writer)
    with pytest.raises(ValueError, match="no se sobrescribe"):
        ops.restore(backup, target)
    assert (target / DATABASE_NAME).read_bytes() == b"someone-elses-data"


def test_backup_and_verification_close_every_connection(saved, tmp_path, monkeypatch):
    directory, backup = saved
    connections = []
    real_sqlite = sqlite3

    class TrackedConnection:
        def __init__(self, *args, **kwargs):
            self.inner = real_sqlite.connect(*args, **kwargs)
            self.closed = False
            connections.append(self)

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def backup(self, target):
            self.inner.backup(target.inner)

        def close(self):
            self.closed = True
            self.inner.close()

    monkeypatch.setattr(ops, "sqlite3", SimpleNamespace(connect=TrackedConnection, Error=sqlite3.Error))
    ops.verify_backup(backup)
    ops.backup(directory, tmp_path / "other.sqlite3")
    assert len(connections) >= 5 and all(connection.closed for connection in connections)


@pytest.mark.parametrize("document,level", [("snapshot.json", "root"), ("snapshot.json", "sleeve"),
                                            ("live.json", "root"), ("live.json", "sleeve")])
def test_import_rejects_live_mode_in_all_documents(legacy, tmp_path, document, level):
    path = legacy / document
    value = json.loads(path.read_text())
    if level == "root":
        value["mode"] = "live"
    else:
        value["sleeves"]["crypto"]["mode"] = "live"
    path.write_text(json.dumps(value))
    target = tmp_path / "target"
    with pytest.raises(ValueError, match="paper"):
        ops.import_legacy(legacy, target)
    assert not (target / DATABASE_NAME).exists()


@pytest.mark.parametrize("filename", ["trades.csv", "equity.csv", "live_equity.csv"])
def test_import_rejects_live_rows(legacy, tmp_path, filename):
    (legacy / filename).write_text("sleeve,mode\ncrypto,live\n")
    with pytest.raises(ValueError, match="paper"):
        ops.import_legacy(legacy, tmp_path / "target")


def test_import_rejects_unknown_sleeve_but_keeps_valid_legacy_fields_optional(legacy, tmp_path):
    ops.import_legacy(legacy, tmp_path / "valid")
    (legacy / "trades.csv").write_text("sleeve,mode\nunknown,paper\n")
    with pytest.raises(ValueError, match="Bloque desconocido"):
        ops.import_legacy(legacy, tmp_path / "invalid")


def test_import_uses_validated_frozen_bytes_and_refuses_source_drift(legacy, tmp_path, monkeypatch):
    original = SQLiteStore.import_legacy

    def drift(self, frozen):
        result = original(self, frozen)
        (legacy / "trades.csv").write_text("sleeve,mode\ncrypto,live\n")
        return result

    monkeypatch.setattr(SQLiteStore, "import_legacy", drift)
    target = tmp_path / "runtime"
    with pytest.raises(ValueError, match="origen cambió"):
        ops.import_legacy(legacy, target)
    store = SQLiteStore(target / DATABASE_NAME)
    assert store.read_document("deployment") is None
    assert store.rows("trades")[0]["mode"] == "paper"


def test_activation_requires_storage_integrity_ok(saved, monkeypatch):
    directory, _ = saved
    monkeypatch.setattr(SQLiteStore, "health", lambda _: {"integrity": "corrupt", "pending_orders": 0, "unknown_orders": 0})
    with pytest.raises(ValueError, match="integridad"):
        ops.activate(directory, True)
    assert not (directory / "worker.enabled").exists()
