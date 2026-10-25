#!/usr/bin/env python3
"""Descarga verificada del respaldo final de la arena (F1). Solo biblioteca estándar.

Requiere la arena en modo mantenimiento (`lab.arena_maintenance`). Usa las credenciales del
panel que carga `tl.py` (nunca las imprime). Cada tramo trae su huella SHA-256 desde el
contenedor; se escribe en su posición del archivo final y queda anotado en `<archivo>.partes.json`.
Si una llamada se corta, la siguiente retoma desde el primer tramo que falte.

    arena_backup.py status   --dest DIR        guarda el inventario del contenedor
    arena_backup.py download --dest DIR [--budget 150] [--part-mib 32]
    arena_backup.py verify   --dest DIR        huella completa de cada archivo contra el contenedor

Archivos que baja: el respaldo final nuevo (`arena-final-*/`), los respaldos que ya existían
(`arena-backups/`) y lo que haya en `arena-imports/`. La base viva (`arena/`) no se baja: el
respaldo consistente es su copia.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tl  # noqa: E402

ARENA = tl.ARENA_URL
PREFIXES = ('arena-final-', 'arena-backups/', 'arena-imports/')


def fetch_status(env: dict) -> dict:
    code, body = tl._request(f'{ARENA}/maintenance/status', headers=tl._panel_headers(env), timeout=60)
    try:
        payload = json.loads(body or b'null')
    except json.JSONDecodeError:
        payload = None
    if code != 200 or not isinstance(payload, dict):
        sys.exit(f'La arena no está en mantenimiento o no responde (HTTP {code}).')
    return payload


def wanted(status: dict) -> list[dict]:
    files = (status.get('inventory_after') or {}).get('files', [])
    return [f for f in files if f['path'].startswith(PREFIXES)]


def _write_json(path: Path, value) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def cmd_status(env: dict, dest: Path) -> dict:
    status = fetch_status(env)
    dest.mkdir(parents=True, exist_ok=True)
    if status.get('phase') == 'ready':
        _write_json(dest / 'inventario-contenedor.json', status)
    files = wanted(status)
    print(json.dumps({'phase': status.get('phase'), 'error': status.get('error'),
                      'backup': {k: status.get('backup', {}).get(k) for k in ('directory', 'sqlite_bytes', 'reused')},
                      'files_to_download': len(files), 'bytes_to_download': sum(f['size'] for f in files),
                      'counts': status.get('counts')}, indent=1, ensure_ascii=False))
    return status


def _part(env: dict, rel: str, offset: int, length: int, compress: bool) -> bytes:
    url = (f'{ARENA}/maintenance/part?path={quote(rel)}&offset={offset}&length={length}'
           f'&gzip={1 if compress else 0}')
    import urllib.request
    req = urllib.request.Request(url, headers={**tl._panel_headers(env), 'User-Agent': 'trading-lab-claude/1.0'})
    with urllib.request.urlopen(req, timeout=120, context=tl._ssl_context()) as r:
        body, head = r.read(), r.headers
    raw = gzip.decompress(body) if head.get('X-Part-Encoding') == 'gzip' else body
    if len(raw) != length or int(head['X-Part-Offset']) != offset:
        raise ValueError('Tramo incompleto')
    if hashlib.sha256(raw).hexdigest() != head['X-Part-Sha256']:
        raise ValueError('La huella del tramo no coincide')
    return raw


def cmd_download(env: dict, dest: Path, budget: float, part_mib: int) -> None:
    started = time.monotonic()
    inventory = json.loads((dest / 'inventario-contenedor.json').read_text(encoding='utf-8'))
    part = part_mib * 1024 * 1024
    done_total = parts_total = 0
    for item in wanted(inventory):
        target = dest / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        ledger_path = target.with_name(target.name + '.partes.json')
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
            'path': item['path'], 'size': item['size'], 'sha256': item['sha256'], 'part_bytes': part, 'parts': {}}
        if ledger['sha256'] != item['sha256'] or ledger['part_bytes'] != part:
            sys.exit(f'{item["path"]}: el registro de tramos no corresponde a este inventario.')
        partial = target.with_name(target.name + '.descargando')
        if target.exists():
            n = -(-item['size'] // part)
            done_total += n; parts_total += n
            continue
        if not partial.exists():
            with partial.open('xb') as stream:
                stream.truncate(item['size'])
        offsets = list(range(0, item['size'], part)) or [0]
        parts_total += len(offsets)
        compress = not item['path'].endswith('.gz')
        fd = os.open(partial, os.O_RDWR)
        try:
            for index, offset in enumerate(offsets):
                if str(index) in ledger['parts']:
                    done_total += 1
                    continue
                if time.monotonic() - started > budget:
                    break
                length = min(part, item['size'] - offset)
                for attempt in range(3):
                    try:
                        raw = _part(env, item['path'], offset, length, compress)
                        break
                    except Exception as exc:  # reintento acotado del tramo fallido
                        if attempt == 2:
                            print(f'{item["path"]} tramo {index}: falló ({type(exc).__name__})', flush=True)
                            raw = None
                if raw is None:
                    break
                os.pwrite(fd, raw, offset)
                os.fsync(fd)
                ledger['parts'][str(index)] = {'offset': offset, 'length': length,
                                               'sha256': hashlib.sha256(raw).hexdigest()}
                _write_json(ledger_path, ledger)
                done_total += 1
        finally:
            os.close(fd)
        if len(ledger['parts']) == len(offsets):
            sha = tl_digest(partial)
            if sha != item['sha256']:
                sys.exit(f'{item["path"]}: huella completa distinta a la del contenedor; no se publica.')
            os.replace(partial, target)
            print(f'{item["path"]}: completo y verificado', flush=True)
        if time.monotonic() - started > budget:
            break
    print(json.dumps({'parts_done': done_total, 'parts_total_seen': parts_total,
                      'seconds': round(time.monotonic() - started, 1)}))


def tl_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def cmd_verify(dest: Path) -> int:
    inventory = json.loads((dest / 'inventario-contenedor.json').read_text(encoding='utf-8'))
    rows, ok = [], True
    for item in wanted(inventory):
        target = dest / item['path']
        if not target.exists():
            rows.append({'path': item['path'], 'status': 'falta'}); ok = False
            continue
        sha = tl_digest(target)
        same = sha == item['sha256'] and target.stat().st_size == item['size']
        ok &= same
        rows.append({'path': item['path'], 'size': item['size'], 'sha256': sha, 'status': 'igual' if same else 'DISTINTO'})
    print(json.dumps({'ok': ok, 'files': rows}, indent=1))
    return 0 if ok else 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('cmd', choices=['status', 'download', 'verify'])
    p.add_argument('--dest', type=Path, required=True)
    p.add_argument('--budget', type=float, default=150, help='segundos máximos por llamada')
    p.add_argument('--part-mib', type=int, default=32)
    a = p.parse_args()
    if a.cmd == 'verify':
        sys.exit(cmd_verify(a.dest))
    env = tl.load_env()
    if a.cmd == 'status':
        cmd_status(env, a.dest)
    else:
        cmd_download(env, a.dest, a.budget, a.part_mib)


if __name__ == '__main__':
    main()
