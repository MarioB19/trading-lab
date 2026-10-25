"""Local-only checks for Railway's volume boundary and source-only delivery."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from lab import railway_entrypoint as entrypoint


PACKAGE_PATH = Path(__file__).resolve().parents[1] / "scripts/railway/package.py"
SPEC = importlib.util.spec_from_file_location("railway_delivery_package", PACKAGE_PATH)
assert SPEC is not None and SPEC.loader is not None
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


@pytest.mark.parametrize("mount", [Path("."), Path("relative/data"), Path("/tmp/data"), Path("/data/runtime")])
def test_rejects_missing_or_wrong_mount_before_any_write(monkeypatch, mount):
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: pytest.fail("unexpected mkdir"))
    with pytest.raises(ValueError, match="volumen persistente"):
        entrypoint.prepare_volume(mount)


def test_unset_mount_environment_does_not_prepare_or_execute(monkeypatch):
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    monkeypatch.setattr(entrypoint.os, "umask", lambda _: None)
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: pytest.fail("unexpected mkdir"))
    monkeypatch.setattr(entrypoint.os, "execv", lambda *_: pytest.fail("unexpected exec"))
    with pytest.raises(ValueError, match="volumen persistente"):
        entrypoint.main()


@pytest.mark.parametrize("symlink,mounted", [(False, False), (True, True)])
def test_rejects_non_mount_and_mount_symlink_without_writes(monkeypatch, symlink, mounted):
    monkeypatch.setattr(Path, "is_symlink", lambda _: symlink)
    monkeypatch.setattr(Path, "is_mount", lambda _: mounted)
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: pytest.fail("unexpected mkdir"))
    with pytest.raises(ValueError, match="volumen persistente"):
        entrypoint.prepare_volume(Path("/data"))


@pytest.mark.parametrize("directory", ["runtime", "backups", "imports"])
def test_rejects_operational_directory_symlinks(monkeypatch, directory):
    writes = []
    monkeypatch.setattr(Path, "is_mount", lambda path: path == Path("/data"))
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == Path("/data") / directory)
    monkeypatch.setattr(Path, "mkdir", lambda path, **_: writes.append(path))
    monkeypatch.setattr(Path, "chmod", lambda *_: None)
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entrypoint.os, "chown", lambda *_: None)
    with pytest.raises(ValueError, match="enlace"):
        entrypoint.prepare_volume(Path("/data"))
    assert Path("/data") / directory not in writes


def test_prepares_only_three_private_directories_without_recursive_chown(monkeypatch):
    events = []
    monkeypatch.setattr(Path, "is_mount", lambda path: path == Path("/data"))
    monkeypatch.setattr(Path, "is_symlink", lambda _: False)
    monkeypatch.setattr(Path, "mkdir", lambda path, **kwargs: events.append(("mkdir", path, kwargs)))
    monkeypatch.setattr(Path, "chmod", lambda path, mode: events.append(("chmod", path, mode)))
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entrypoint.os, "chown", lambda path, uid, gid: events.append(("chown", path, uid, gid)))
    entrypoint.prepare_volume(Path("/data"))
    expected = []
    for name in ("runtime", "backups", "imports"):
        path = Path("/data") / name
        expected.extend([("mkdir", path, {"mode": 0o700, "exist_ok": True}),
                         ("chown", path, 10001, 10001), ("chmod", path, 0o700)])
    assert events == expected


@pytest.mark.parametrize("initial_uid", [0, 10001, 10002])
def test_privilege_drop_happens_after_prepare_and_before_exec(monkeypatch, initial_uid):
    events = []
    identity = {"uid": initial_uid}
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
    monkeypatch.setenv("TRADING_LAB_BUILD_ID", "wrong-build")
    monkeypatch.setattr(entrypoint.os, "umask", lambda mode: events.append(("umask", mode)))
    monkeypatch.setattr(entrypoint, "prepare_volume", lambda mount: events.append(("prepare", mount)))
    monkeypatch.setattr(Path, "read_text", lambda path: json.dumps({"build_id": "railway-0123456789abcdef"}))
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: identity["uid"])
    monkeypatch.setattr(entrypoint.os, "setgroups", lambda groups: events.append(("groups", groups)))
    monkeypatch.setattr(entrypoint.os, "setgid", lambda gid: events.append(("gid", gid)))

    def setuid(uid):
        events.append(("uid", uid))
        identity["uid"] = uid

    class ExecObserved(Exception):
        pass

    def execv(executable, argv):
        events.append(("exec", executable, argv, identity["uid"]))
        assert entrypoint.os.environ["TRADING_LAB_BUILD_ID"] == "railway-0123456789abcdef"
        raise ExecObserved

    monkeypatch.setattr(entrypoint.os, "setuid", setuid)
    monkeypatch.setattr(entrypoint.os, "execv", execv)
    if initial_uid == 10002:
        with pytest.raises(ValueError, match="UID operativo"):
            entrypoint.main()
        assert not any(event[0] == "exec" for event in events)
        return
    with pytest.raises(ExecObserved):
        entrypoint.main()
    assert events[:2] == [("umask", 0o077), ("prepare", Path("/data"))]
    assert events[2:-1] == ([('groups', []), ('gid', 10001), ('uid', 10001)] if initial_uid == 0 else [])
    assert events[-1] == ("exec", entrypoint.sys.executable,
                          [entrypoint.sys.executable, "-m", "lab.hosted", "--config", "/app/config.yaml",
                           "--data-dir", "/data/runtime", "--backup-dir", "/data/backups"], 10001)


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    root = tmp_path / "source"
    permitted = {
        "infra/railway/Dockerfile": "FROM example\n",
        "requirements-runtime.txt": "some-package==1.0\n",
        "config.yaml": "mode: paper\n",
        "src/lab/__init__.py": "",
        "src/lab/hosted.py": "VALUE = 1\n",
        "src/lab/nested/module.py": "VALUE = 2\n",
        "dashboard/operations.html": "<main>panel</main>\n",
        "dashboard/operations.js": "console.log('panel');\n",
        "dashboard/operations.css": "main { color: black; }\n",
        "dashboard/tabs.js": "console.log('tabs');\n",
        "research/backlog.yaml": "version: 1\n",
        "research/semaforo.yaml": "version: 1\n",
        "research/carriles.yaml": "version: 1\n",
        "archive/arena-v1/manifest.json": "{}\n",
        "archive/arena-v1/preregistros/plan.md": "plan\n",
    }
    excluded = [".env", ".env.local", ".git/config", "state/equity.csv",
                "runtime-data/trading.sqlite3", "state/worker.enabled", "reports/evidence.json",
                "configs/experiments/candidate.yaml", ".venv/bin/python", "data/history.csv",
                "dashboard/data.json", "dashboard/index.html", "src/lab/__pycache__/bad.py",
                "src/lab/hidden.sqlite3", "src/lab/private.env", "src/lab/native.so",
                "research/notes.md", "archive/other/x.json"]
    for name, content in {**permitted, **{name: "excluded-synthetic-marker" for name in excluded}}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setattr(packager, "ROOT", root)

    def git_output(command, **kwargs):
        assert kwargs == {"cwd": root, "text": True}
        if command == ["git", "rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        assert command == ["git", "status", "--porcelain"]
        return " M src/lab/hosted.py\n"

    monkeypatch.setattr(packager.subprocess, "check_output", git_output)
    return root, permitted


def test_bundle_is_source_only_and_identifies_actual_dirty_payload(tmp_path, source_tree):
    root, permitted = source_tree
    target = tmp_path / "bundle"
    manifest = packager.package(target)
    expected = {("Dockerfile" if name == "infra/railway/Dockerfile" else name) for name in permitted}
    actual = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
    assert actual == expected | {"release.json"}
    assert all("excluded-synthetic-marker" not in path.read_text() for path in target.rglob("*") if path.is_file())
    hashes = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in expected}
    tree_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    assert manifest["files"] == hashes
    assert manifest["payload_sha256"] == tree_hash
    assert manifest["build_id"] == "railway-" + tree_hash[:16]
    assert manifest["build_id"] != manifest["source_head"]
    assert manifest["source_head"] == "a" * 40
    assert manifest["source_has_uncommitted_changes"] is True
    assert manifest["profile"] == "operational-paper"
    assert json.loads((target / "release.json").read_text()) == manifest
    assert (root / "state/equity.csv").read_text() == "excluded-synthetic-marker"


def test_content_identity_is_stable_and_changes_with_included_source(tmp_path, source_tree):
    root, _ = source_tree
    first = packager.package(tmp_path / "first")
    second = packager.package(tmp_path / "second")
    assert first["build_id"] == second["build_id"]
    (root / "src/lab/hosted.py").write_text("VALUE = 3\n")
    third = packager.package(tmp_path / "third")
    assert first["build_id"] != third["build_id"]
    assert first["source_head"] == third["source_head"]


def test_existing_destination_is_never_overwritten(tmp_path, source_tree):
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError, match="no se sobrescribe"):
        packager.package(target)
    assert list(target.iterdir()) == [sentinel]
    assert sentinel.read_text() == "preserve"


@pytest.mark.parametrize("relative", ["config.yaml", "src/lab/hosted.py", "dashboard/operations.js"])
def test_symlinked_payload_file_is_rejected_before_creating_bundle(tmp_path, source_tree, relative):
    root, _ = source_tree
    external = tmp_path / "external.txt"
    external.write_text("not from the source tree")
    path = root / relative
    path.unlink()
    path.symlink_to(external)
    target = tmp_path / "bundle"
    with pytest.raises(ValueError, match="enlaces simbólicos"):
        packager.package(target)
    assert not target.exists()


def test_symlinked_source_directory_is_rejected(tmp_path, source_tree):
    root, _ = source_tree
    external = tmp_path / "external-lab"
    (root / "src/lab").rename(external)
    (root / "src/lab").symlink_to(external, target_is_directory=True)
    target = tmp_path / "bundle"
    with pytest.raises(ValueError, match="enlaces simbólicos"):
        packager.package(target)
    assert not target.exists()
