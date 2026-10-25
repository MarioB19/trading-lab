"""Arena en modo mantenimiento: solo lectura, sin worker y sin rotación de respaldos.

Lo activa la imagen `infra/arena/maintenance.Dockerfile` con ARENA_MAINTENANCE=read-only-backup
(variable de la imagen, no de Railway). `lab.arena_hosted run` lo detecta antes de cualquier otra
cosa, así que el comando de arranque del servicio no cambia.

Qué hace al arrancar, una sola vez y en este orden:
1. Inventario del volumen (archivos, tamaños y huellas SHA-256) antes de tocar nada.
2. Un respaldo consistente de la base con `lab.arena.backup` en una carpeta aparte
   `/data/arena-final-<UTC>/`. Nunca toca `/data/arena-backups/` ni borra nada.
3. Conteos por tabla de la base viva (solo lectura) y del respaldo.
4. Inventario después del respaldo.

Qué sirve por HTTP (Basic auth del panel y Host del dominio público):
- `/healthz` sin credenciales, para la sonda de Railway.
- `/maintenance/status`: fase, inventarios, respaldo y conteos.
- `/maintenance/part?path=&offset=&length=[&gzip=1]`: un tramo de un archivo del inventario,
  con su huella en la cabecera X-Part-Sha256. Solo GET; cualquier otro método responde 405.
"""
from __future__ import annotations

import base64
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlparse

from . import arena

MODE_ENV = 'ARENA_MAINTENANCE'
MODE_VALUE = 'read-only-backup'
FINAL_PREFIX = 'arena-final-'
FINAL_KIND = 'arena-final-backup-v1'
MIB = 1024 * 1024
MAX_PART = 64 * MIB
MARGIN = 256 * MIB
_FINAL = re.compile(r'arena-final-\d{8}T\d{6}Z')


def enabled() -> bool:
    return os.environ.get(MODE_ENV) == MODE_VALUE


def _now_ms() -> int:
    return int(time.time() * 1000)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(MIB):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path) -> dict:
    """Todos los archivos del volumen con tamaño y huella. Nunca sigue enlaces."""
    root = Path(root)
    files, unreadable = [], []

    def failed(error):
        unreadable.append(str(Path(error.filename).relative_to(root)) if error.filename else str(error))

    for current, dirs, names in os.walk(root, onerror=failed, followlinks=False):
        dirs.sort()
        for name in sorted(names):
            path = Path(current) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError(f'Enlace simbólico en el volumen: {rel}')
            if not path.is_file():
                continue
            stat = path.stat()
            try:
                sha = digest(path)
            except PermissionError:
                unreadable.append(rel)
                continue
            files.append({'path': rel, 'size': stat.st_size, 'mtime_ms': int(stat.st_mtime * 1000), 'sha256': sha})
    usage = shutil.disk_usage(root)
    return {'taken_ms': _now_ms(), 'root': str(root), 'files': files, 'unreadable': sorted(unreadable),
            'total_bytes': sum(f['size'] for f in files),
            'disk': {'total_bytes': usage.total, 'used_bytes': usage.used, 'free_bytes': usage.free}}


def table_counts(db_path: Path) -> dict:
    """Filas por tabla, en una sola transacción de solo lectura."""
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names}


def _finals(mount: Path) -> list[Path]:
    return sorted(p for p in mount.iterdir() if p.name.startswith(FINAL_PREFIX))


def final_backup(mount: Path, *, stamp: str | None = None) -> dict:
    """Crea (o verifica, si ya existe) el respaldo final en una carpeta aparte.

    Un solo intento por carpeta: si encuentra una carpeta a medias, no crea otra (para no llenar
    el volumen tras un reinicio) y devuelve el error para que lo revise una persona.
    """
    mount = Path(mount)
    directory = mount / 'arena'
    source = directory / arena.DB_NAME
    for folder in _finals(mount):
        if not _FINAL.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
            raise ValueError(f'Carpeta de respaldo final no reconocida: {folder.name}')
        manifest_path = folder / 'manifest.json'
        if not manifest_path.is_file():
            raise ValueError(f'Respaldo final a medias en {folder.name}; no se reintenta solo')
        manifest = json.loads(manifest_path.read_text())
        data = folder / arena.DB_NAME
        if (manifest.get('kind') != FINAL_KIND or data.stat().st_size != manifest['sqlite_bytes']
                or digest(data) != manifest['sqlite_sha256']):
            raise ValueError(f'El respaldo final {folder.name} no coincide con su manifiesto')
        return {**manifest, 'directory': folder.name, 'reused': True}
    if not source.is_file():
        raise ValueError('Base de la arena ausente')
    needed = source.stat().st_size + MARGIN
    if shutil.disk_usage(mount).free < needed:
        raise ValueError(f'Espacio insuficiente para el respaldo final ({needed} bytes)')
    stamp = stamp or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = mount / f'{FINAL_PREFIX}{stamp}'
    folder.mkdir(mode=0o700)
    target = folder / arena.DB_NAME
    started = _now_ms()
    result = arena.backup(directory, target)  # lab.arena backup: API de respaldo de SQLite + integrity_check
    target.chmod(0o600)
    manifest = {'kind': FINAL_KIND, 'method': 'lab.arena.backup', 'created_ms': started,
                'finished_ms': _now_ms(), 'sqlite_bytes': target.stat().st_size,
                'sqlite_sha256': result['sha256'], 'integrity_check': 'ok',
                'source': f'arena/{arena.DB_NAME}', 'counts': table_counts(target)}
    with (folder / 'manifest.json').open('x') as stream:
        stream.write(json.dumps(manifest, sort_keys=True, indent=1) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    (folder / 'manifest.json').chmod(0o600)
    return {**manifest, 'directory': folder.name, 'reused': False}


def prepare(mount: Path, state: dict, lock: threading.Lock) -> None:
    """Inventario → respaldo final → conteos → inventario. Registra el error sin reintentar."""
    def update(**values):
        with lock:
            state.update(values)
        if 'phase' in values:
            print(json.dumps({'maintenance_phase': values['phase'], 'error': values.get('error')}), flush=True)

    try:
        update(phase='inventory_before', started_ms=_now_ms())
        update(inventory_before=inventory(mount), phase='backup')
        backup = final_backup(mount)
        update(backup=backup, phase='counts')
        live = mount / 'arena' / arena.DB_NAME
        update(counts={'live': table_counts(live), 'backup': backup['counts']}, phase='inventory_after')
        update(inventory_after=inventory(mount), phase='ready', finished_ms=_now_ms())
    except Exception as exc:  # El servicio sigue sano y de solo lectura; lo revisa una persona.
        update(phase='error', error=f'{type(exc).__name__}: {exc}'[:500], finished_ms=_now_ms())


def _allowed(state: dict) -> dict:
    files = {}
    for key in ('inventory_before', 'inventory_after'):
        for item in (state.get(key) or {}).get('files', []):
            files[item['path']] = item
    return files


def make_server(mount: Path, port: int, *, public_domain: str, username: str, password: str,
                state: dict, lock: threading.Lock) -> ThreadingHTTPServer:
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.[a-z]{2,}', public_domain or '') or not username or not password:
        raise ValueError('Dominio y credenciales del panel obligatorios')
    expected = ('Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()).encode()
    mount = Path(mount)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'TradingArenaMaintenance'

        def log_message(self, *_):
            pass

        def send(self, code, body, content_type='application/json; charset=utf-8', headers=None):
            raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Strict-Transport-Security', 'max-age=31536000')
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            if code == 401:
                self.send_header('WWW-Authenticate', 'Basic realm="Trading Lab Arena", charset="UTF-8"')
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/healthz':
                return self.send(200, {'status': 'ok', 'mode': 'maintenance', 'worker': False})
            if self.headers.get('Host') != public_domain:
                return self.send(403, {'error': 'Host no permitido'})
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected):
                return self.send(401, {'error': 'Acceso protegido'})
            with lock:
                snapshot = json.loads(json.dumps(state))
            if url.path == '/maintenance/status':
                return self.send(200, snapshot)
            if url.path != '/maintenance/part':
                return self.send(404, {'error': 'No encontrado'})
            if snapshot.get('phase') != 'ready':
                return self.send(409, {'error': 'Inventario o respaldo en curso', 'phase': snapshot.get('phase')})
            query = parse_qs(url.query)
            try:
                rel = query['path'][0]
                offset, length = int(query['offset'][0]), int(query['length'][0])
            except (KeyError, IndexError, ValueError):
                return self.send(400, {'error': 'path, offset y length obligatorios'})
            item = _allowed(snapshot).get(rel)
            if item is None:
                return self.send(404, {'error': 'Archivo fuera del inventario'})
            path = mount / rel
            if (offset < 0 or not 0 < length <= MAX_PART or offset + length > item['size']
                    or path.is_symlink() or not path.is_file() or path.stat().st_size != item['size']):
                return self.send(416, {'error': 'Tramo inválido o archivo cambiado'})
            with path.open('rb') as stream:
                stream.seek(offset)
                data = stream.read(length)
            if len(data) != length:
                return self.send(416, {'error': 'Lectura incompleta'})
            headers = {'X-Part-Sha256': hashlib.sha256(data).hexdigest(), 'X-Part-Offset': str(offset),
                       'X-Part-Length': str(length), 'X-File-Size': str(item['size'])}
            if query.get('gzip', ['0'])[0] == '1':
                data = gzip.compress(data, compresslevel=1, mtime=0)
                headers['X-Part-Encoding'] = 'gzip'
            return self.send(200, data, 'application/octet-stream', headers)

        def refuse(self):
            self.send(405, {'error': 'Mantenimiento de solo lectura'})

        do_POST = do_PUT = do_PATCH = do_DELETE = refuse

    return ThreadingHTTPServer(('0.0.0.0', port), Handler)


def serve(mount: Path = Path('/data')) -> None:
    """Punto de entrada de la imagen de mantenimiento (ya con UID 10001 y volumen comprobado)."""
    state = {'phase': 'starting', 'mode': 'maintenance', 'worker': False, 'backup_rotation': False,
             'build_id': os.environ.get('TRADING_LAB_BUILD_ID', 'sin-dato')}
    lock = threading.Lock()
    server = make_server(mount, int(os.environ.get('PORT', '8080')),
                         public_domain=os.environ.get('RAILWAY_PUBLIC_DOMAIN', ''),
                         username=os.environ.get('TRADING_DASHBOARD_USER', ''),
                         password=os.environ.get('TRADING_DASHBOARD_PASSWORD', ''),
                         state=state, lock=lock)
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    http = threading.Thread(target=server.serve_forever, daemon=True)
    http.start()
    threading.Thread(target=prepare, args=(mount, state, lock), daemon=True).start()
    print(json.dumps({'maintenance': 'started', 'worker': False, 'backup_rotation': False}), flush=True)
    try:
        while not stopped.wait(1):
            if not http.is_alive():
                raise RuntimeError('Servidor HTTP detenido')
    finally:
        server.shutdown()
        server.server_close()
