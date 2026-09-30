"""Prepare an attached Railway volume, then permanently drop root privileges."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

UID = GID = 10001


def prepare_volume(mount: Path) -> None:
    if mount != Path("/data") or mount.is_symlink() or not mount.is_mount():
        raise ValueError("Falta el volumen persistente en /data; no se inicia")
    for name in ("runtime", "backups", "imports"):
        directory = mount / name
        if directory.is_symlink():
            raise ValueError("Directorio operativo no puede ser un enlace")
        directory.mkdir(mode=0o700, exist_ok=True)
        if os.geteuid() == 0:
            os.chown(directory, UID, GID)
            directory.chmod(0o700)


def main() -> None:
    os.umask(0o077)
    prepare_volume(Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "")))
    release = json.loads(Path("/app/release.json").read_text())
    os.environ["TRADING_LAB_BUILD_ID"] = release["build_id"]
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(GID)
        os.setuid(UID)
    if os.geteuid() != UID:
        raise ValueError("UID operativo incorrecto")
    os.execv(sys.executable, [sys.executable, "-m", "lab.hosted", "--config", "/app/config.yaml",
                            "--data-dir", "/data/runtime", "--backup-dir", "/data/backups"])


if __name__ == "__main__":
    main()
