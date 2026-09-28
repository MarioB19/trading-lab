"""Synthetic state only: no market prices, return calculations or broker calls."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from lab import paper_ops as ops
from lab.experiments import ResearchGateError, canonical_hash
from lab.storage import SQLiteStore, execution_lock


@pytest.fixture
def comparison(tmp_path):
    path = tmp_path / "paper"
    path.mkdir()
    plan = {"experiment_id": "aggressive-v1", "synthetic": True}
    proof = {"commit": "1" * 40, "code_commit": "2" * 40, "sha256": "3" * 64}
    manifest = {"type": ops.IDENTITY, "experiment_id": plan["experiment_id"], "plan": plan,
                "config_sha256": canonical_hash(plan), "code_commit": proof["code_commit"],
                "preregistration": proof, "run_id": "synthetic-only", "mode": "paper", "live_authorized": False}
    store = SQLiteStore(path / ops.DB_NAME)
    store.write_document("comparison_manifest", manifest)
    store.write_document("state", {"mode": "paper", "sleeves": {name: {"mode": "paper",
                         "ledger": {"cash": 500, "positions": {}}} for name in ops.SLEEVES}})
    store.write_document("comparison_health", {"status": "awaiting_first_pair"})
    store.write_document("comparison_history", [])
    store.write_document("comparison_ticks", {})
    (path / "inputs").mkdir()
    captures = {}
    for block in ops.BLOCKS:
        raw = f"date,{block}\n2026-09-25,100\n".encode()
        digest = hashlib.sha256(raw).hexdigest()
        relative = f"inputs/{block}-{digest}.csv"
        (path / relative).write_bytes(raw)
        captures[block] = {"file": relative, "sha256": digest}
    store.write_document("comparison_inputs", captures)
    return path, store, manifest


def test_backup_restore_preserves_all_evidence_and_never_enables(tmp_path, comparison):
    path, store, manifest = comparison
    with store.transaction() as db:
        store._rows(db, "trades", [{"execution_id": "synthetic", "mode": "paper", "sleeve": "control.crypto"}])
    bundle, restored = tmp_path / "bundle", tmp_path / "restored"
    before = ops.inspect(path)
    result = ops.backup(path, bundle)
    assert result["summary"] == {k: v for k, v in before.items() if k != "frozen_inputs"}
    assert ops.verify_backup(bundle)["verified"]
    restored_result = ops.restore(bundle, restored)
    assert not restored_result["scheduled"] and not restored_result["live_authorized"]
    assert ops.inspect(restored) == before
    assert not (restored / "worker.enabled").exists()
    assert SQLiteStore(restored / ops.DB_NAME).read_document("comparison_manifest") == manifest
    assert ops.inspect(path) == before


def test_snapshot_includes_uncheckpointed_wal(tmp_path, comparison):
    path, _, _ = comparison
    writer = sqlite3.connect(path / ops.DB_NAME)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO documents VALUES('wal-evidence','{\"value\":42}','synthetic')")
        writer.commit()
        assert (path / (ops.DB_NAME + "-wal")).stat().st_size > 0
        bundle = tmp_path / "bundle"
        ops.backup(path, bundle)
        with sqlite3.connect(bundle / ops.DB_NAME) as target:
            assert json.loads(target.execute("SELECT payload FROM documents WHERE name='wal-evidence'").fetchone()[0]) == {"value": 42}
    finally:
        writer.close()


def test_runner_lock_blocks_backup_and_restore(tmp_path, comparison):
    path, _, _ = comparison
    bundle = tmp_path / "bundle"
    with execution_lock(path / "comparison"):
        with pytest.raises(RuntimeError, match="bloqueo"):
            ops.backup(path, bundle)
    assert not bundle.exists()
    ops.backup(path, bundle)
    target = tmp_path / "restored"
    with execution_lock(target / "comparison"):
        with pytest.raises(RuntimeError, match="bloqueo"):
            ops.restore(bundle, target)
    assert not (target / ops.DB_NAME).exists()


@pytest.mark.parametrize("mutation", ("database", "input", "manifest", "extra", "traversal", "symlink"))
def test_tampered_backup_is_rejected_without_destination(tmp_path, comparison, mutation):
    path, _, _ = comparison
    bundle = tmp_path / "bundle"
    ops.backup(path, bundle)
    record = json.loads((bundle / "manifest.json").read_text())
    captured = bundle / next(name for name in record["files"] if name.startswith("inputs/"))
    if mutation == "database":
        with sqlite3.connect(bundle / ops.DB_NAME) as db:
            db.execute("DELETE FROM documents WHERE name='state'")
    elif mutation == "input":
        captured.write_text("modified")
    elif mutation == "manifest":
        record["summary"]["code_commit"] = "9" * 40
        (bundle / "manifest.json").write_text(json.dumps(record))
    elif mutation == "extra":
        (bundle / "unexpected").write_text("not evidence")
    elif mutation == "traversal":
        record["files"]["../outside.csv"] = "0" * 64
        (bundle / "manifest.json").write_text(json.dumps(record))
    else:
        raw = captured.read_bytes()
        captured.unlink()
        outside = tmp_path / "outside.csv"
        outside.write_bytes(raw)
        captured.symlink_to(outside)
    with pytest.raises(ResearchGateError):
        ops.restore(bundle, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


def test_no_overwrite_or_operational_directory(tmp_path, comparison):
    path, _, _ = comparison
    bundle = tmp_path / "bundle"
    ops.backup(path, bundle)
    with pytest.raises(ResearchGateError, match="existe"):
        ops.backup(path, bundle)
    with pytest.raises(ResearchGateError, match="vacío"):
        ops.restore(bundle, path)
    operational = tmp_path / "operational"
    operational.mkdir()
    (operational / "trading.sqlite3").write_text("active")
    with pytest.raises(ResearchGateError, match="runtime"):
        ops.restore(bundle, operational / "child")
    assert (operational / "trading.sqlite3").read_text() == "active"


@pytest.mark.parametrize("corrupt", ("mode", "namespace", "identity", "deployment", "orphan-ledger"))
def test_operational_or_mixed_identity_never_backed_up(tmp_path, comparison, corrupt):
    path, store, manifest = comparison
    if corrupt == "mode":
        state = store.read_document("state")
        state["mode"] = "live"
        store.write_document("state", state)
    elif corrupt == "namespace":
        state = store.read_document("state")
        state["sleeves"]["control.crypto"]["account_namespace"] = "external"
        store.write_document("state", state)
    elif corrupt == "identity":
        manifest["config_sha256"] = "0" * 64
        store.write_document("comparison_manifest", manifest)
    elif corrupt == "deployment":
        store.write_document("deployment", {"mode": "paper"})
    else:
        store.write_document("ledger:external", {"cash": 100})
    with pytest.raises(ResearchGateError):
        ops.backup(path, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_missing_historical_capture_blocks_backup(tmp_path, comparison):
    path, store, _ = comparison
    hashes = {block: "9" * 64 for block in ops.BLOCKS}
    store.write_document("comparison_ticks", {"old-pair": {"hashes": hashes}})
    with pytest.raises(ResearchGateError, match="falta una captura"):
        ops.backup(path, tmp_path / "bundle")


def test_restore_does_not_rewrite_attestation(tmp_path, comparison):
    path, store, manifest = comparison
    manifest["preregistration"].update(proof_kind="build_attestation", attestation_sha256="a" * 64)
    store.write_document("comparison_manifest", manifest)
    bundle = tmp_path / "bundle"
    ops.backup(path, bundle)
    ops.restore(bundle, tmp_path / "restored")
    assert SQLiteStore(tmp_path / "restored" / ops.DB_NAME).read_document("comparison_manifest") == manifest


def test_failed_restore_installs_database_last(tmp_path, comparison, monkeypatch):
    path, _, _ = comparison
    bundle, destination = tmp_path / "bundle", tmp_path / "restore"
    ops.backup(path, bundle)
    def fail(*args, **kwargs):
        raise OSError("synthetic disk full")
    monkeypatch.setattr(ops, "_write_json", fail)
    with pytest.raises(OSError, match="disk full"):
        ops.restore(bundle, destination)
    assert not (destination / ops.DB_NAME).exists()
    with pytest.raises(ResearchGateError, match="vacío"):
        ops.restore(bundle, destination)


def test_cli_never_initializes_a_missing_database(tmp_path, capsys):
    destination = tmp_path / "missing"
    assert ops.main(["inspect", "--data-dir", str(destination)]) == 2
    assert not destination.exists()
    assert "bloqueada" in capsys.readouterr().out
