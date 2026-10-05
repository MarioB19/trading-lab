"""Stopped-writer migration for the declared prospective cost amendment."""
from contextlib import closing
import fcntl
import hashlib
import json
from . import arena, arena_fees
from .arena_hosted import PREREG
from .arena_reporting_upgrade import FROZEN_FILES

SOURCE_COMMIT = '7e35212032ab604f1aabdc66d370a706af0685c9'


def upgrade(directory, *, cutover_confirmed=False):
    if not cutover_confirmed or (directory / 'arena.enabled').exists():
        raise ValueError('Detener ejecutor y confirmar corte antes de actualizar comisiones')
    # Signal mathematics and public capture source remain exactly the frozen version.
    for name in ['src/lab/portfolio.py', 'src/lab/arena_market.py']:
        if hashlib.sha256((arena.ROOT / name).read_bytes()).hexdigest() != FROZEN_FILES[name]:
            raise ValueError('Cambió una regla o fuente fuera de la enmienda de costos')
    proof = arena.execution_proof(PREREG)
    fee_proof = arena_fees.proof()
    cfg = arena_fees.plan()
    with (directory / 'arena-worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        arena.audit(directory)
        with closing(arena.connect(directory)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            manifest = json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
            old = manifest.get('proof', {})
            if manifest.get('fee_policy'):
                if old != proof or manifest['fee_policy']['proof'] != fee_proof:
                    raise ValueError('Ya existe otra versión de comisiones')
                return {'status': 'already_upgraded', 'policy': manifest['fee_policy']}
            if (old.get('code_commit') != SOURCE_COMMIT or old.get('commit') != PREREG
                    or manifest['kind'] != 'paper' or manifest['plan_sha256'] != arena.canonical_hash(arena.plan())):
                raise ValueError('Origen distinto de la arena auditada autorizada')
            ts = arena.now_ms()
            if ts <= (db.execute('SELECT MAX(observed_ms) FROM captures').fetchone()[0] or 0):
                raise ValueError('El corte debe ser posterior a las capturas')
            wallets = [(wid, json.loads(raw)) for wid, raw in db.execute('SELECT id,payload FROM wallets')]
            policy = {'model_id': cfg['model_id'], 'schedule_sha256': arena.canonical_hash(cfg),
                      'scope': cfg['scope'], 'proof': fee_proof, 'activated_ms': ts,
                      'after_fill_id': db.execute('SELECT COALESCE(MAX(id),0) FROM fills').fetchone()[0],
                      'opening_wallets': {wid: {k: w[k] for k in ('cash','qty','fees','equity','peak','realized','cost_basis')} for wid,w in wallets}}
            manifest['proof'] = proof
            manifest['fee_policy'] = policy
            db.execute("UPDATE meta SET value=? WHERE key='manifest'", (arena._json(manifest),))
            for wid, wallet in wallets:
                wallet['quotes'] = []
                db.execute('UPDATE wallets SET payload=? WHERE id=?', (arena._json(wallet), wid))
            event = {'action': 'fee_model_upgrade', 'previous_proof': old, 'new_proof': proof,
                     'fee_policy': policy, 'balances_reset': False, 'signal_rules_changed': False,
                     'cost_model_changed': True, 'historical_fees_rewritten': False}
            db.execute('INSERT INTO events(ts,payload) VALUES (?,?)', (ts, arena._json(event)))
    return {'status': 'upgraded', 'policy': policy, 'audit': arena.audit(directory)}
