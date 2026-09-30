from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from lab import hosted, ops
from lab.runtime import DATABASE_NAME
from lab.storage import SQLiteStore


class FakeServer:
    def __init__(self, fail=False):
        self.end = threading.Event()
        self.started = threading.Event()
        self.closed = False
        self.fail = fail

    def serve_forever(self, **kwargs):
        self.started.set()
        if self.fail:
            raise OSError("synthetic API failure")
        self.end.wait()

    def shutdown(self):
        self.end.set()

    def server_close(self):
        self.closed = True


class FakeChild:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


def eventually(check, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        time.sleep(.005)
    assert check()


def harness(tmp_path, monkeypatch, *, env=None, fail_api=False, imported=False):
    data, backups = tmp_path / "runtime", tmp_path / "backups"
    data.mkdir()
    server, stop = FakeServer(fail_api), threading.Event()
    calls, stopped, statuses, result, factory_args = [], [], [], [], []

    def factory(*args, **kwargs):
        factory_args.append((args, kwargs))
        return server

    def spawn(command):
        child = FakeChild()
        calls.append((command, child))
        return child

    def terminate(children, **kwargs):
        for child in children:
            if child is not None:
                stopped.append(child)
                child.returncode = -15

    monkeypatch.setattr(hosted, "stop_processes", terminate)
    monkeypatch.setattr(hosted, "record_status", lambda directory, **kw: statuses.append(kw))
    if imported:
        monkeypatch.setattr(hosted, "read_document", lambda *a: {"mode": "paper", "imported_at_utc": "today"})
    thread = threading.Thread(target=lambda: result.append(hosted.supervise(
        tmp_path / "config.yaml", data, backups, port=4321, server_factory=factory,
        spawn=spawn, stop=stop, poll_seconds=.005, shutdown_grace=.1,
        environ={} if env is None else env)))
    return dict(data=data, server=server, stop=stop, calls=calls, stopped=stopped,
                statuses=statuses, result=result, factory_args=factory_args, thread=thread)


def finish(h):
    h["stop"].set()
    h["thread"].join(timeout=2)
    assert not h["thread"].is_alive()


def workers(h):
    return [(cmd, child) for cmd, child in h["calls"] if cmd[2] == "lab.runtime"]


@pytest.mark.parametrize("flag,marker", [(None, False), (None, True), ("false", True), ("TRUE", True), ("true", False)])
def test_api_boots_without_import_or_activation_and_both_worker_gates_are_required(tmp_path, monkeypatch, flag, marker):
    h = harness(tmp_path, monkeypatch, env={"TRADING_WORKER_ALLOWED": flag})
    if marker:
        (h["data"] / "worker.enabled").touch()
    h["thread"].start()
    try:
        assert h["server"].started.wait(timeout=1)
        time.sleep(.03)
        assert not workers(h)
        assert not (h["data"] / DATABASE_NAME).exists()
        assert (h["data"] / "worker.enabled").exists() is marker
        options = h["factory_args"][0][1]
        assert options["require_auth"] is True
        assert options["host"] == "0.0.0.0" and options["port"] == 4321
    finally:
        finish(h)
    assert h["server"].closed and h["result"] == [0]


def test_explicit_activation_starts_once_and_deactivation_keeps_api_available(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, env={"TRADING_WORKER_ALLOWED": "true"})
    h["thread"].start()
    try:
        assert h["server"].started.wait(timeout=1)
        (h["data"] / "worker.enabled").touch()
        eventually(lambda: len(workers(h)) == 1)
        command, child = workers(h)[0]
        assert "--live" not in command and "--if-due" not in command  # runtime owns scheduling.
        assert command[-2:] == ["--interval", "300"]
        time.sleep(.03)
        assert len(workers(h)) == 1
        (h["data"] / "worker.enabled").unlink()
        eventually(lambda: child in h["stopped"])
        assert h["thread"].is_alive() and not h["server"].closed
        assert not (h["data"] / "worker.enabled").exists()
    finally:
        finish(h)


def test_revoking_external_permission_stops_worker_even_if_restored_marker_remains(tmp_path, monkeypatch):
    env = {"TRADING_WORKER_ALLOWED": "true"}
    h = harness(tmp_path, monkeypatch, env=env)
    (h["data"] / "worker.enabled").touch()
    h["thread"].start()
    try:
        eventually(lambda: len(workers(h)) == 1)
        child = workers(h)[0][1]
        env["TRADING_WORKER_ALLOWED"] = "false"
        eventually(lambda: child in h["stopped"])
        assert (h["data"] / "worker.enabled").exists()
        assert h["thread"].is_alive()
    finally:
        finish(h)


def test_worker_crash_exits_nonzero_instead_of_healthy_api_only_process(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, env={"TRADING_WORKER_ALLOWED": "true"})
    (h["data"] / "worker.enabled").touch()
    h["thread"].start()
    eventually(lambda: len(workers(h)) == 1)
    workers(h)[0][1].returncode = 2
    h["thread"].join(timeout=2)
    assert h["result"] == [1] and h["server"].closed
    assert any(s.get("worker_returncode") == 2 and s["status"] == "error" for s in h["statuses"])


def test_api_thread_failure_is_visible_and_supervisor_fails(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, fail_api=True)
    h["thread"].start()
    h["thread"].join(timeout=2)
    assert h["result"] == [1]
    assert h["server"].closed
    assert any("synthetic API failure" in s.get("api_error", "") for s in h["statuses"])


def test_backup_process_failure_is_visible_and_does_not_claim_success(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, imported=True)
    h["thread"].start()
    try:
        eventually(lambda: len(h["calls"]) == 1)
        command, child = h["calls"][0]
        assert command[2:4] == ["lab.hosted", "--backup-once"]
        assert not workers(h)
        child.returncode = 1
        eventually(lambda: any(s.get("backup_status") == "error" for s in h["statuses"]))
        time.sleep(.03)
        assert len(h["calls"]) == 1  # Backoff, no busy retry loop.
        assert not any(s.get("backup_status") == "ok" for s in h["statuses"])
    finally:
        finish(h)


def test_mount_validation_prevents_ephemeral_and_nested_paths(tmp_path):
    mount = tmp_path / "data"
    env = {"RAILWAY_PROJECT_ID": "test"}
    with pytest.raises(ValueError, match="MOUNT_PATH"):
        hosted.validate_paths(mount / "runtime", mount / "backups", environ=env)
    env["RAILWAY_VOLUME_MOUNT_PATH"] = str(mount)
    with pytest.raises(ValueError, match="persistente"):
        hosted.validate_paths(mount / "runtime", mount / "backups", environ=env, ismount=lambda _: False)
    with pytest.raises(ValueError, match="persistente"):
        hosted.validate_paths(tmp_path / "ephemeral", mount / "backups", environ=env, ismount=lambda _: True)
    assert hosted.validate_paths(mount / "runtime", mount / "backups", environ=env, ismount=lambda p: p == mount) == (mount / "runtime", mount / "backups")
    with pytest.raises(ValueError, match="separados"):
        hosted.validate_paths(mount / "runtime", mount / "runtime" / "backups", environ={})
    assert not mount.exists()


def test_symlink_escape_from_volume_is_rejected(tmp_path):
    mount, outside = tmp_path / "volume", tmp_path / "outside"
    mount.mkdir(); outside.mkdir()
    (mount / "runtime").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="persistente"):
        hosted.validate_paths(mount / "runtime", mount / "backups",
                              environ={"RAILWAY_VOLUME_MOUNT_PATH": str(mount)}, ismount=lambda _: True)


def test_paper_validation_rejects_credentials_dotenv_and_live_without_reading_secrets(tmp_path, monkeypatch):
    from lab import data
    monkeypatch.setattr(data, "ROOT", tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text("mode: paper\n")
    assert hosted.validate_paper(config, environ={})["mode"] == "paper"
    with pytest.raises(ValueError, match="credenciales"):
        hosted.validate_paper(config, environ={"BITSO_API_KEY": "synthetic"})
    (tmp_path / ".env").touch()
    with pytest.raises(ValueError, match=".env"):
        hosted.validate_paper(config, environ={})
    (tmp_path / ".env").unlink()
    config.write_text("mode: live\n")
    with pytest.raises(ValueError, match="paper"):
        hosted.validate_paper(config, environ={})


def imported_store(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "state.json").write_text(json.dumps({"sleeves": {"crypto": {
        "mode": "paper", "capital_base": 500, "ledger": {"cash": 500, "positions": {}},
        "last_candle": "2026-09-27"}}}))
    target = tmp_path / "runtime"
    ops.import_legacy(source, target)
    return target, SQLiteStore(target / DATABASE_NAME)


def test_verified_backups_retain_seven_own_copies_preserve_others_and_restore(tmp_path):
    data, store = imported_store(tmp_path)
    backups = tmp_path / "backups"
    backups.mkdir()
    foreign = backups / "manual.sqlite3"
    ops.backup(data, foreign)
    foreign_hash = ops.sha256(foreign)
    incomplete = backups / "hosted-20200101T000000000000Z-aaaaaaaaaaaa.sqlite3"
    incomplete.write_bytes(b"incomplete evidence")
    for i in range(9):
        store.write_document("synthetic_counter", i)
        latest = hosted.perform_backup(data, backups)
    own = [p for p in backups.iterdir() if hosted.BACKUP_PATTERN.fullmatch(p.name) and p != incomplete]
    assert len(own) == 7
    assert incomplete.read_bytes() == b"incomplete evidence"
    assert ops.sha256(foreign) == foreign_hash
    assert not (data / "worker.enabled").exists()
    newest = backups / latest["file"]
    restored = tmp_path / "restored"
    ops.restore(newest, restored)
    assert SQLiteStore(restored / DATABASE_NAME).read_document("synthetic_counter") == 8
    assert not (restored / "worker.enabled").exists()
    health = store.read_document("hosted_health")
    assert health["backup_status"] == "ok" and health["last_backup_verified_utc"]


def test_backup_verification_failure_never_records_verified_success(tmp_path, monkeypatch):
    data, store = imported_store(tmp_path)
    monkeypatch.setattr(ops, "verify_backup", lambda _: (_ for _ in ()).throw(ValueError("synthetic corruption")))
    with pytest.raises(ValueError, match="corruption"):
        hosted.perform_backup(data, tmp_path / "backups")
    assert store.read_document("hosted_health") is None


def test_health_record_does_not_initialize_missing_or_unimported_database(tmp_path):
    data = tmp_path / "empty"
    hosted.record_status(data, status="paused")
    assert not data.exists()
    store = SQLiteStore(data / DATABASE_NAME)
    hosted.record_status(data, status="paused")
    assert store.read_document("hosted_health") is None


def test_health_reporting_cannot_block_shutdown_behind_a_busy_writer(tmp_path):
    data, store = imported_store(tmp_path)
    with store.transaction():
        began = time.monotonic()
        hosted.record_status(data, status="stopped")
        assert time.monotonic() - began < 1.5
    assert store.read_document("hosted_health") is None


def test_schema_creation_during_import_is_still_uninitialized_not_a_crash(tmp_path):
    data = tmp_path / "runtime"
    data.mkdir()
    db = sqlite3.connect(data / DATABASE_NAME)
    db.close()
    assert hosted.read_document(data, "deployment", {}) == {}
    hosted.record_status(data, status="paused")
    assert (data / DATABASE_NAME).stat().st_size == 0
    (data / DATABASE_NAME).write_bytes(b"invalid database content" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        hosted.read_document(data, "deployment", {})


@pytest.mark.skipif(os.name != "posix", reason="Process sessions require POSIX")
def test_shutdown_kills_grandchild_even_when_parent_has_already_exited(tmp_path):
    heartbeat = tmp_path / "heartbeat"
    grandchild = ("import signal,time,pathlib,sys; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                  "p=pathlib.Path(sys.argv[1]);\nwhile True:\n p.write_text(str(time.time_ns())); time.sleep(.01)\n")
    parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])"
    process = subprocess.Popen([sys.executable, "-c", parent, grandchild, str(heartbeat)], start_new_session=True)
    try:
        process.wait(timeout=2)
        eventually(heartbeat.exists)
        began = time.monotonic()
        hosted.stop_processes([process], grace=.15)
        assert time.monotonic() - began < 1.5
        time.sleep(.05)
        contents = heartbeat.read_text()
        time.sleep(.1)
        assert heartbeat.read_text() == contents
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_child_launch_always_creates_own_session(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    hosted.start_child(["synthetic"])
    assert calls[0][1]["start_new_session"] is True
    assert calls[0][1]["stdin"] == subprocess.DEVNULL


@pytest.mark.skipif(os.name != "posix", reason="Process sessions require POSIX")
def test_sigterm_to_supervisor_stops_worker_and_stubborn_grandchild(tmp_path):
    data = tmp_path / "runtime"
    data.mkdir()
    (data / "worker.enabled").touch()
    heartbeat = tmp_path / "heartbeat"
    # Every process is a synthetic Python fixture; no bot or market client runs.
    script = '''
import os,subprocess,sys,threading
from pathlib import Path
from lab import hosted
class Server:
    def __init__(self): self.end=threading.Event()
    def serve_forever(self, **kwargs): self.end.wait()
    def shutdown(self): self.end.set()
    def server_close(self): pass
hosted.validate_paper=lambda _: {}
hosted.validate_paths=lambda a,b: (a,b)
child="import pathlib,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); p=pathlib.Path(sys.argv[1]);\\nwhile True:\\n p.write_text(str(time.time_ns())); time.sleep(.01)"
worker="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(60)"
def spawn(command):
    return subprocess.Popen([sys.executable,'-c',worker,child,sys.argv[2]],start_new_session=True)
original=hosted.supervise
def supervise(*args,**kwargs):
    return original(*args,**kwargs,server_factory=lambda *a,**k: Server(),spawn=spawn,poll_seconds=.01,shutdown_grace=.2)
hosted.supervise=supervise
os.environ['TRADING_WORKER_ALLOWED']='true'
raise SystemExit(hosted.main(['--data-dir',sys.argv[1],'--backup-dir',sys.argv[1]+'-backups']))
'''
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PORT": "4321"}
    process = subprocess.Popen([sys.executable, "-c", script, str(data), str(heartbeat)], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        eventually(heartbeat.exists, timeout=4)
        process.send_signal(signal.SIGTERM)
        _, error = process.communicate(timeout=3)
        assert process.returncode == 0, error
        value = heartbeat.read_text()
        time.sleep(.1)
        assert heartbeat.read_text() == value
        assert (data / "worker.enabled").exists()  # A redeploy does not erase operator intent.
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


def test_main_honors_port_and_never_activates_data(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.touch()
    data, backups = tmp_path / "runtime", tmp_path / "backups"
    monkeypatch.setattr(hosted, "validate_paper", lambda _: {})
    monkeypatch.setattr(hosted, "validate_paths", lambda a, b: (a, b))
    monkeypatch.setenv("PORT", "4321")
    calls = []
    monkeypatch.setattr(hosted, "supervise", lambda *a, **kw: calls.append((a, kw)) or 0)
    argv = ["--config", str(config), "--data-dir", str(data), "--backup-dir", str(backups)]
    assert hosted.main(argv) == 0
    assert calls[0][1]["port"] == 4321
    assert not (data / DATABASE_NAME).exists()
    assert not (data / "worker.enabled").exists()
    monkeypatch.setenv("PORT", "0")
    assert hosted.main(argv) == 2
