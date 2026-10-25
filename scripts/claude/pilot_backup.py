#!/usr/bin/env python3
"""Copia externa del último respaldo verificado del piloto (solo biblioteca estándar).

El supervisor del piloto hace un respaldo SQLite verificado cada 24 h en su volumen. Este script
lo baja por `/api/backups/latest` y `/api/backups/part` (contraseña del panel, tramos con huella),
junto con su manifiesto, y comprueba la huella completa y el integrity_check antes de publicarlo.

    pilot_backup.py [--dest runtime-data/respaldos/piloto]

No borra copias anteriores. Restaurar es `lab.ops restore` a un destino vacío y desactivado.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.request
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tl  # noqa: E402

PART = 8 * 1024 * 1024


def _get(env: dict, path: str):
    """Cuerpo y cabeceras; las cabeceras no distinguen mayúsculas (el borde de Railway las pasa en minúsculas)."""
    req = urllib.request.Request(f"{tl.pilot_url()}{path}",
                                 headers={**tl._panel_headers(env), "User-Agent": "trading-lab-claude/1.0"})
    with urllib.request.urlopen(req, timeout=120, context=tl._ssl_context()) as r:
        return r.read(), r.headers


def download(env: dict, latest: dict, kind: str, size: int, target: Path) -> str:
    partial = target.with_name(target.name + ".descargando")
    h = hashlib.sha256()
    with partial.open("wb") as out:
        for offset in range(0, size, PART):
            length = min(PART, size - offset)
            for attempt in range(3):
                try:
                    data, head = _get(env, f"/api/backups/part?file={quote(latest['file'])}&kind={kind}"
                                           f"&offset={offset}&length={length}")
                    if len(data) != length or hashlib.sha256(data).hexdigest() != head.get("X-Part-Sha256"):
                        raise ValueError("tramo con huella distinta")
                    break
                except Exception:
                    if attempt == 2:
                        raise
            out.write(data)
            h.update(data)
        out.flush()
        os.fsync(out.fileno())
    return h.hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dest", type=Path, default=tl.REPO / "runtime-data" / "respaldos" / "piloto")
    a = p.parse_args()
    env = tl.load_env()
    raw, _ = _get(env, "/api/backups/latest")
    latest = json.loads(raw)
    a.dest.mkdir(parents=True, exist_ok=True)
    db, manifest = a.dest / latest["file"], a.dest / latest["manifest_file"]
    if db.exists() and manifest.exists():
        print(json.dumps({"status": "ya estaba", "file": latest["file"], "created_at_utc": latest["created_at_utc"]}))
        return
    sha_db = download(env, latest, "db", latest["bytes"], db)
    sha_manifest = download(env, latest, "manifest", latest["manifest_bytes"], manifest)
    if sha_db != latest["sha256"] or sha_manifest != latest["manifest_sha256"]:
        sys.exit("La huella completa no coincide con el manifiesto del servidor; no se publica.")
    partial = db.with_name(db.name + ".descargando")
    with closing(sqlite3.connect(partial.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            sys.exit("El respaldo descargado no pasa integrity_check; no se publica.")
    meta = json.loads(manifest.with_name(manifest.name + ".descargando").read_text())
    if meta.get("sha256") != sha_db or meta.get("file") != latest["file"]:
        sys.exit("El manifiesto no describe este archivo; no se publica.")
    os.replace(partial, db)
    os.replace(manifest.with_name(manifest.name + ".descargando"), manifest)
    print(json.dumps({"status": "verificado", "file": latest["file"], "bytes": latest["bytes"],
                      "sha256": sha_db, "created_at_utc": latest["created_at_utc"], "dest": str(a.dest)}))


if __name__ == "__main__":
    main()
