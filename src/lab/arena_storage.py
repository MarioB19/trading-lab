"""Bounded, compressed arena backups; never trims trading history."""
from contextlib import closing
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import uuid

MIB = 1024 * 1024
KIND = 'arena-compressed-backup-v1'
NAME = re.compile(r'arena-\d{13}-[0-9a-f]{8}')


class StoragePressure(RuntimeError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(MIB):
            h.update(chunk)
    return h.hexdigest()


def limits(path):
    usage = shutil.disk_usage(path)
    return {'free_bytes': usage.free, 'total_bytes': usage.total,
            'reserve_bytes': max(256 * MIB, min(1024 * MIB, usage.total // 5)),
            'backup_budget_bytes': min(1024 * MIB, usage.total // 5)}


def worker_space_available(path):
    value = limits(path)
    return value['free_bytes'] >= value['reserve_bytes']


def _physical(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('El almacenamiento requiere rutas físicas')
    return path


def snapshots(backups):
    """Only verified snapshots count towards the persisted backup schedule."""
    backups = _physical(backups)
    found = []
    for folder in sorted(backups.iterdir()):
        if not NAME.fullmatch(folder.name):
            continue
        _physical(folder)
        if not folder.is_dir() or {p.name for p in folder.iterdir()} != {'manifest.json', 'snapshot.sqlite3.gz'}:
            raise ValueError('Respaldo publicado no reconocido')
        meta_path, data = folder / 'manifest.json', folder / 'snapshot.sqlite3.gz'
        _physical(meta_path); _physical(data)
        meta = json.loads(meta_path.read_text())
        if (meta.get('kind') != KIND or meta.get('compressed_bytes') != data.stat().st_size
                or meta.get('compressed_sha256') != digest(data)
                or not isinstance(meta.get('created_ms'), int)):
            raise ValueError('Integridad del respaldo publicado incorrecta')
        found.append((folder, meta))
    return sorted(found, key=lambda pair: pair[1]['created_ms'])


def latest_backup_time(backups):
    items = snapshots(backups)
    return items[-1][1]['created_ms'] / 1000 if items else 0


def _cleanup_partial(backups):
    # This runs only while holding the single backup lock. Never glob legacy DBs.
    for folder in backups.glob('.arena-backup-*.part'):
        _physical(folder)
        marker = folder / 'work.json'
        if not marker.exists(): marker = folder / 'manifest.json'
        _physical(marker)
        if not folder.is_dir() or not marker.is_file():
            raise ValueError('Temporal de respaldo no reconocido')
        if json.loads(marker.read_text()).get('kind') != KIND:
            raise ValueError('Temporal ajeno')
        for p in folder.iterdir():
            _physical(p)
            if not p.is_file() or p.name not in {'work.json', 'manifest.json', 'snapshot.sqlite3.gz'}:
                raise ValueError('Contenido temporal ajeno')
        shutil.rmtree(folder)


class _BoundedFile:
    def __init__(self, raw, budget):
        self.raw, self.budget, self.written = raw, budget, 0

    def write(self, data):
        if self.written + len(data) > self.budget:
            raise StoragePressure('Respaldo comprimido excede presupuesto')
        result = self.raw.write(data)
        self.written += result
        return result

    def flush(self):
        self.raw.flush()


def backup_once(directory, backups, *, now=None):
    """Use ephemeral disk for SQLite's consistent copy; atomically publish gzip."""
    directory, backups = _physical(directory), _physical(backups)
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = backups / '.backup.lock'
    _physical(lock_path)
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _cleanup_partial(backups)
        items = snapshots(backups)
        # Keep the newest verified copy even when making room before a new one.
        for folder, _ in items[:-1]:
            shutil.rmtree(folder)
        policy = limits(backups)
        contents = list(backups.rglob('*'))
        for p in contents: _physical(p)
        occupied = sum(p.stat().st_size for p in contents if p.is_file())
        allowance = min(policy['backup_budget_bytes'] - occupied,
                        policy['free_bytes'] - policy['reserve_bytes']) - 64 * 1024
        if allowance <= 0:
            raise StoragePressure('Sin reserva para un respaldo seguro')
        source = directory / 'arena.sqlite3'
        _physical(source)
        if not source.is_file():
            raise ValueError('Base de arena ausente')
        stamp = int((time.time() if now is None else now) * 1000)
        name = f'arena-{stamp:013d}-{uuid.uuid4().hex[:8]}'
        pending = backups / ('.arena-backup-' + uuid.uuid4().hex + '.part')
        pending.mkdir(mode=0o700)
        (pending / 'work.json').write_text(json.dumps({'kind': KIND}))
        try:
            with tempfile.TemporaryDirectory(prefix='arena-snapshot-') as temp:
                raw_copy = Path(temp) / 'snapshot.sqlite3'
                with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
                    size = src.execute('PRAGMA page_count').fetchone()[0] * src.execute('PRAGMA page_size').fetchone()[0]
                    if shutil.disk_usage(temp).free < size + 256 * MIB:
                        raise StoragePressure('Sin espacio temporal para SQLite')
                    deadline = time.monotonic() + 300
                    def progress(*_):
                        if time.monotonic() > deadline:
                            raise StoragePressure('Respaldo SQLite excede tiempo seguro')
                    with closing(sqlite3.connect(raw_copy)) as dst:
                        src.backup(dst, pages=256, progress=progress)
                        if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                            raise ValueError('Copia SQLite inválida')
                raw_sha = digest(raw_copy)
                compressed = pending / 'snapshot.sqlite3.gz'
                with raw_copy.open('rb') as reader, compressed.open('xb') as writer:
                    with gzip.GzipFile(filename='', fileobj=_BoundedFile(writer, allowance), mode='wb', compresslevel=6, mtime=0) as gz:
                        shutil.copyfileobj(reader, gz, MIB)
                    writer.flush(); os.fsync(writer.fileno())
                h = hashlib.sha256()
                with gzip.open(compressed, 'rb') as check:
                    while chunk := check.read(MIB): h.update(chunk)
                if h.hexdigest() != raw_sha:
                    raise ValueError('Copia comprimida no reproduce SQLite')
                meta = {'kind': KIND, 'created_ms': stamp, 'sqlite_sha256': raw_sha,
                        'sqlite_bytes': raw_copy.stat().st_size,
                        'compressed_sha256': digest(compressed), 'compressed_bytes': compressed.stat().st_size}
                with (pending / 'manifest.json').open('x') as stream:
                    stream.write(json.dumps(meta, sort_keys=True) + '\n'); stream.flush(); os.fsync(stream.fileno())
                (pending / 'work.json').unlink()
                for p in pending.iterdir(): p.chmod(0o600)
                fd = os.open(pending, os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
                # Rename publishes both files together on the same filesystem.
                os.rename(pending, backups / name)
                fd = os.open(backups, os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
                return {**meta, 'directory': str(backups / name)}
        finally:
            if pending.exists(): shutil.rmtree(pending)
