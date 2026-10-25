import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from lab import hosted
from test_service_panel import credentials, serving  # noqa: F401
from test_hosted import imported_store

ROOT = Path(__file__).resolve().parents[1]


def test_pilot_backup_script_downloads_verifies_and_never_overwrites(tmp_path, credentials, monkeypatch):
    data, store = imported_store(tmp_path)
    backups = tmp_path / "backups"
    hosted.perform_backup(data, backups)
    sys.path.insert(0, str(ROOT / "scripts/claude"))
    spec = importlib.util.spec_from_file_location("pilot_backup_cli", ROOT / "scripts/claude/pilot_backup.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "PART", 4096)
    monkeypatch.setenv("TL_PANEL_USER", "tester")
    monkeypatch.setenv("TL_PANEL_PASSWORD", "test-only")
    dest = tmp_path / "usb"
    with serving(data, tmp_path, backup_dir=backups) as port:
        monkeypatch.setenv("TL_PILOT_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setattr(sys, "argv", ["pilot_backup.py", "--dest", str(dest)])
        cli.main()
        cli.main()  # la segunda vez no reescribe
    files = sorted(p.name for p in dest.iterdir())
    assert len(files) == 2 and not any(name.endswith(".descargando") for name in files)
    manifest = json.loads((dest / [f for f in files if f.endswith(".manifest.json")][0]).read_text())
    assert hashlib.sha256((dest / manifest["file"]).read_bytes()).hexdigest() == manifest["sha256"]
