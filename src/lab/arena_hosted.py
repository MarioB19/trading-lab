"""Railway supervisor and explicit, balance-preserving arena cutover."""
import argparse
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from . import arena
from . import arena_storage
from .arena_service import make_server

PREREG = '61c6ac319f9f5421a4c1b9ad80e5d5165b2fcc72'
LOCAL_SOURCE = '7c3afe42cffaa87d2e19c8f0de48723ea3d8ab63'
UID = GID = 10001


def migrate(directory, *, cutover_confirmed=False):
    """Requires a stopped local owner; only version proof and quotes change."""
    if not cutover_confirmed:
        raise ValueError('Se requiere corte local confirmado')
    proof = arena.execution_proof(PREREG)
    with (directory / 'arena-worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verified = arena.audit(directory)
        with closing(arena.connect(directory)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            manifest = json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
            old = manifest.get('proof', {})
            if manifest['kind'] != 'paper' or manifest['plan_sha256'] != arena.canonical_hash(arena.plan()):
                raise ValueError('La migración requiere el mismo protocolo paper')
            if old == proof:
                return {'status': 'already_migrated', 'audit': verified}
            if old.get('code_commit') != LOCAL_SOURCE or old.get('commit') != PREREG:
                raise ValueError('Origen distinto de la arena local autorizada')
            event = {'action': 'railway_cutover', 'previous_proof': old, 'new_proof': proof,
                     'rule_change': False, 'balances_reset': False}
            manifest['proof'] = proof
            manifest['hosting_migration'] = {'from_code': LOCAL_SOURCE, 'to_code': proof['code_commit'],
                                             'at': arena.iso(arena.now_ms()), 'local_cutover_confirmed': True}
            db.execute("UPDATE meta SET value=? WHERE key='manifest'", (arena._json(manifest),))
            for wid, raw in db.execute('SELECT id,payload FROM wallets').fetchall():
                wallet = json.loads(raw)
                wallet['quotes'] = []
                db.execute('UPDATE wallets SET payload=? WHERE id=?', (arena._json(wallet), wid))
            db.execute('INSERT INTO events(ts,payload) VALUES (?,?)', (arena.now_ms(), arena._json(event)))
    return {'status': 'migrated', 'audit': arena.audit(directory)}


def activate(directory, *, cutover_confirmed=False):
    if not cutover_confirmed:
        raise ValueError('Activación requiere corte local confirmado')
    state = arena.status(directory)
    if state['manifest'].get('proof') != arena.execution_proof(PREREG):
        raise ValueError('Primero migrar y verificar la versión')
    from .arena_fees import verify_policy
    verify_policy(state['manifest'])
    arena.audit(directory)
    (directory / 'arena.enabled').write_text('railway-paper-only\n')


def prepare_volume(mount):
    if mount != Path('/data') or mount.is_symlink() or not mount.is_mount():
        raise ValueError('Volumen persistente propio requerido en /data')
    for name in ('arena', 'arena-backups', 'arena-imports'):
        target = mount / name
        if target.is_symlink():
            raise ValueError('No se admiten enlaces en el volumen')
        target.mkdir(mode=0o700, exist_ok=True)
        if os.geteuid() == 0:
            os.chown(target, UID, GID)
            target.chmod(0o700)


def run():
    os.umask(0o077)
    prepare_volume(Path(os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '')))
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(GID)
        os.setuid(UID)
    if os.geteuid() != UID:
        raise ValueError('UID incorrecto')
    from . import arena_maintenance
    if arena_maintenance.enabled():
        # Imagen de mantenimiento: volumen y salud, sin worker ni rotación de respaldos.
        return arena_maintenance.serve(Path('/data'))
    arena.execution_proof(PREREG)
    directory, backups = Path('/data/arena'), Path('/data/arena-backups')
    server = make_server(directory, int(os.environ.get('PORT', '8080')),
                         public_domain=os.environ.get('RAILWAY_PUBLIC_DOMAIN', ''),
                         username=os.environ.get('TRADING_DASHBOARD_USER'),
                         password=os.environ.get('TRADING_DASHBOARD_PASSWORD'))
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    http = threading.Thread(target=server.serve_forever, daemon=True)
    http.start()
    worker = None
    last_backup = arena_storage.latest_backup_time(backups)
    backup_retry_after = 0
    storage_blocked = None
    try:
        while not stopped.wait(1):
            if not http.is_alive():
                raise RuntimeError('Servidor HTTP detenido')
            enabled = os.environ.get('ARENA_WORKER_ALLOWED') == 'true' and (directory / 'arena.enabled').is_file()
            enough_space = arena_storage.worker_space_available(directory)
            if storage_blocked != (not enough_space):
                storage_blocked = not enough_space
                print(json.dumps({'storage_blocked': storage_blocked,
                                  'storage': arena_storage.limits(directory)}), flush=True)
            enabled = enabled and enough_space
            if worker is not None and worker.poll() is not None:
                raise RuntimeError('Worker detenido; Railway debe reiniciar el supervisor')
            if worker is not None and not enabled:
                worker.terminate()
                worker.wait(timeout=30)
                worker = None
            if ((directory / arena.DB_NAME).is_file() and time.time() - last_backup >= 86400
                    and time.time() >= backup_retry_after):
                try:
                    result = arena_storage.backup_once(directory, backups)
                    print(json.dumps({'backup': result}), flush=True)
                    last_backup = result['created_ms'] / 1000
                except (OSError, ValueError, sqlite3.Error, arena_storage.StoragePressure) as exc:
                    # Retain the last verified copy; no restart loop or partial DBs.
                    print(json.dumps({'backup_failed': type(exc).__name__,
                                      'retry_seconds': 3600}), flush=True)
                    backup_retry_after = time.time() + 3600
            if enabled and worker is None:
                if arena.status(directory)['manifest'].get('proof') != arena.execution_proof(PREREG):
                    raise ValueError('Versión migrada no coincide con imagen')
                worker = subprocess.Popen([sys.executable, '-m', 'lab.arena', 'run', '--directory', str(directory),
                                           '--preregistration-commit', PREREG])
                print(json.dumps({'worker_started': worker.pid, 'mode': 'paper'}), flush=True)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()
        server.shutdown()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'migrate', 'activate', 'deactivate', 'upgrade-reporting', 'upgrade-fees', 'upgrade-storage'])
    parser.add_argument('--directory', type=Path, default=Path('/data/arena'))
    parser.add_argument('--cutover-confirmed', action='store_true')
    args = parser.parse_args()
    if args.action == 'run':
        run()
    elif args.action == 'migrate':
        print(json.dumps(migrate(args.directory, cutover_confirmed=args.cutover_confirmed)))
    elif args.action == 'activate':
        activate(args.directory, cutover_confirmed=args.cutover_confirmed)
        print('Arena paper activada')
    elif args.action == 'upgrade-fees':
        from .arena_fees_upgrade import upgrade
        print(json.dumps(upgrade(args.directory, cutover_confirmed=args.cutover_confirmed)))
    elif args.action == 'upgrade-storage':
        from .arena_storage_upgrade import upgrade
        print(json.dumps(upgrade(args.directory, cutover_confirmed=args.cutover_confirmed)))
    elif args.action == 'upgrade-reporting':
        from .arena_reporting_upgrade import upgrade
        print(json.dumps(upgrade(args.directory, cutover_confirmed=args.cutover_confirmed)))
    else:
        (args.directory / 'arena.enabled').unlink(missing_ok=True)
        print('Arena paper desactivada; esperar detención del worker')


if __name__ == '__main__':
    main()
