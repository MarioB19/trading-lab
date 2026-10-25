#!/usr/bin/env python3
"""Freeze an allowlisted deployment bundle; never upload the working tree."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def package(destination: Path) -> dict:
    if destination.exists():
        raise ValueError("El destino ya existe; no se sobrescribe")
    files = {"Dockerfile": ROOT / "infra/railway/Dockerfile",
             "requirements-runtime.txt": ROOT / "requirements-runtime.txt",
             "config.yaml": ROOT / "config.yaml"}
    for path in sorted((ROOT / "src/lab").rglob("*.py")):
        if "__pycache__" not in path.parts:
            files[str(path.relative_to(ROOT))] = path
    for name in ("operations.html", "operations.js", "tabs.js", "operations.css"):
        files[f"dashboard/{name}"] = ROOT / "dashboard" / name
    # Panel único (F3): investigación (fuente única del backlog) y archivo fijo de la arena.
    for name in ("backlog.yaml", "semaforo.yaml", "carriles.yaml"):
        files[f"research/{name}"] = ROOT / "research" / name
    for path in sorted((ROOT / "archive/arena-v1").rglob("*")):
        if path.is_file():
            files[str(path.relative_to(ROOT))] = path
    if any(path.is_symlink() or any(parent.is_symlink() for parent in path.parents
                                   if parent != ROOT and ROOT in parent.parents)
           for path in files.values()):
        raise ValueError("No se empaquetan enlaces simbólicos")
    destination.mkdir(parents=True)
    hashes = {}
    for name, source in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    tree_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {"build_id": f"railway-{tree_hash[:16]}", "source_head": head,
                "source_has_uncommitted_changes": bool(subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
                "payload_sha256": tree_hash, "files": hashes, "profile": "operational-paper"}
    (destination / "release.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.destination), indent=2))
