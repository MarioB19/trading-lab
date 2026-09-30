"""Instala el observador macOS de un paquete congelado, separado de Railway."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess


LABEL = "com.tradinglab.rotation-paper-v1"


def configuration(bundle, python, data_dir, backups, commit, code_commit):
    log_dir = data_dir.parent / "rotation-paper-logs"
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "lab.rotation_observer",
                             "--preregistration-commit", commit, "--data-dir", str(data_dir),
                             "--backups", str(backups)],
        "WorkingDirectory": str(bundle),
        "EnvironmentVariables": {"PYTHONPATH": str(bundle / "src"),
                                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                                 "TRADING_LAB_BUILD_ID": code_commit},
        "RunAtLoad": True, "StartInterval": 900, "ThrottleInterval": 60,
        "ProcessType": "Background", "Nice": 5,
        "StandardOutPath": str(log_dir / "observer.stdout.log"),
        "StandardErrorPath": str(log_dir / "observer.stderr.log"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "python", "data-dir", "backups"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--preregistration-commit", required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    cfg = configuration(args.bundle.resolve(), args.python.absolute(), args.data_dir.resolve(),
                        args.backups.resolve(), args.preregistration_commit, args.code_commit)
    target = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = plistlib.dumps(cfg, sort_keys=True)
    if target.exists():
        if target.is_symlink() or target.read_bytes() != payload:
            raise ValueError("ya existe otro observador con este nombre; no se sobrescribe")
    else:
        target.write_bytes(payload)
        target.chmod(0o600)
    Path(cfg["StandardOutPath"]).parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    loaded = subprocess.run(["launchctl", "print", domain + "/" + LABEL], capture_output=True)
    if loaded.returncode:
        subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    else:
        subprocess.run(["launchctl", "kickstart", domain + "/" + LABEL], check=True)
    print(target)
    subprocess.run(["launchctl", "print", domain + "/" + LABEL], check=True)


if __name__ == "__main__":
    main()
