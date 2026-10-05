"""Four independent, cash-funded paper portfolios. No broker or secret imports."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import zlib

from .experiments import canonical_hash, verify_preregistration
from .portfolio import arena_directional_signal as directional_signal

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / 'configs/arena/four_strategies_v1.json'
PREREG_PATH = ROOT / 'reports/four_strategy_arena_v1_preregistro.md'
DB_NAME = 'arena.sqlite3'
INTERVALS = {'5m': 300_000, '1h': 3_600_000, '1d': 86_400_000}
NAMES = {'scalping-v1': 'Day trading / scalping', 'swing-v1': 'Swing / tendencias',
         'mean-reversion-v1': 'Reversión a la media', 'market-making-v1': 'Creación de mercado'}


def plan():
    value = json.loads(PLAN_PATH.read_text())
    if value['mode'] != 'paper' or value['initial_cash_usd'] != 1000 or value['book'] != 'btc_usd':
        raise ValueError('Contrato de simulación no reconocido')
    if [v['id'] for v in value['variants']] != list(NAMES):
        raise ValueError('Se requieren exactamente cuatro estrategias registradas')
    return value


def now_ms():
    return int(time.time() * 1000)


def execution_proof(commit):
    """Same protocol gate, with a Git content/ancestry proof for immutable images."""
    cfg = plan()
    attestation = os.environ.get('ARENA_ATTESTATION')
    if attestation:
        from .research_attestation import verify_attestation
        return verify_attestation(ROOT, Path(attestation), PLAN_PATH, PREREG_PATH,
                                  commit, cfg, list(NAMES))
    return verify_preregistration(ROOT, PREREG_PATH, commit, cfg['experiment_id'], cfg, list(NAMES))


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def arena_path(directory):
    directory = Path(directory).absolute()
    if any(p.is_symlink() for p in [directory, *directory.parents]):
        raise ValueError('La arena requiere ruta física propia')
    if any((directory / f).exists() for f in ['trading.sqlite3', 'comparison.sqlite3', 'worker.enabled', 'state.json']):
        raise ValueError('La arena no puede compartir el directorio del piloto')
    directory.mkdir(parents=True, exist_ok=True)
    return directory / DB_NAME


def connect(directory):
    db = sqlite3.connect(arena_path(directory), timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    return db


def initialize(directory, kind='paper'):
    if kind not in ('paper', 'synthetic'):
        raise ValueError('Solo paper o demostración artificial')
    cfg = plan()
    with closing(connect(directory)) as db, db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS wallets (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inputs (sha TEXT PRIMARY KEY, payload BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS captures (id TEXT PRIMARY KEY, observed_ms INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fills (id INTEGER PRIMARY KEY, strategy TEXT NOT NULL, ts INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, strategy TEXT NOT NULL, ts INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS equity (id INTEGER PRIMARY KEY, strategy TEXT NOT NULL, ts INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS equity_strategy_ts ON equity(strategy,ts);
        ''')
        db.execute('BEGIN IMMEDIATE')
        old = db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()
        if old:
            manifest = json.loads(old[0])
            if manifest['plan_sha256'] != canonical_hash(cfg) or manifest['kind'] != kind:
                raise ValueError('La base pertenece a otro protocolo o tipo de datos')
            return manifest
        manifest = {'created_at': iso(now_ms()), 'plan_sha256': canonical_hash(cfg), 'kind': kind,
                    'mode': 'paper', 'initial_cash_usd': 1000, 'live_authorized': False, 'plan': cfg}
        db.execute('INSERT INTO meta VALUES (?,?)', ('manifest', _json(manifest)))
        for variant in cfg['variants']:
            wallet = {'id': variant['id'], 'cash': 1000., 'qty': 0., 'cost_basis': 0.,
                      'fees': 0., 'realized': 0., 'peak': 1000., 'equity': 1000., 'drawdown': 0.,
                      'paused': False, 'risk_stopped': False, 'day': '', 'day_start': 1000.,
                      'entries_today': 0, 'entry_ms': None, 'last_bar': None, 'quotes': [],
                      'fills': 0, 'reason': 'Esperando el primer ciclo', 'status': 'waiting',
                      'maker_cursor': None, 'mm_seeded': False, 'daily_paused': False}
            db.execute('INSERT INTO wallets VALUES (?,?)', (variant['id'], _json(wallet)))
        return manifest


def validate_frame(frame, expected_kind):
    if frame.get('kind') != expected_kind or frame.get('book') != 'btc_usd':
        raise ValueError('Origen de captura incompatible')
    ts = frame['observed_ms']
    if not isinstance(ts, int) or (expected_kind == 'paper' and abs(now_ms() - ts) > 60_000):
        raise ValueError('Captura fuera del tiempo permitido')
    book = frame['order_book']
    if not 0 <= ts - book['updated_ms'] <= 60_000:
        raise ValueError('Libro viejo o futuro')
    for side in ('bids', 'asks'):
        levels = book[side]
        if not levels or any(len(x) != 2 or not all(math.isfinite(v) and v > 0 for v in x) for x in levels):
            raise ValueError('Profundidad inválida')
        prices = [x[0] for x in levels]
        if prices != sorted(prices, reverse=side == 'bids'):
            raise ValueError('Libro desordenado')
    if book['bids'][0][0] >= book['asks'][0][0]:
        raise ValueError('Libro cruzado')
    if set(frame['candles']) != set(INTERVALS):
        raise ValueError('Faltan intervalos')
    for interval, rows in frame['candles'].items():
        if not rows:
            raise ValueError('Velas vacías')
        last = -1
        for row in rows:
            if len(row) != 6 or not all(math.isfinite(x) for x in row):
                raise ValueError('Vela inválida')
            t, o, h, l, c, volume = row
            if t <= last or t % INTERVALS[interval] or t + INTERVALS[interval] > ts:
                raise ValueError('Vela repetida, futura, abierta o desalineada')
            if last >= 0 and t - last != INTERVALS[interval]:
                raise ValueError('Hueco en velas; no se rellenan precios')
            if min(o, h, l, c) <= 0 or volume < 0 or h < max(o, c, l) or l > min(o, c, h):
                raise ValueError('OHLC inválido')
            last = t
        if ts - (last + INTERVALS[interval]) >= INTERVALS[interval] + 120_000:
            raise ValueError('Señales desactualizadas')
    ids = set()
    for trade in frame['trades']:
        if trade['tid'] in ids or trade['side'] not in ('buy', 'sell'):
            raise ValueError('Trade duplicado o lado desconocido')
        ids.add(trade['tid'])
        if trade['ts'] > ts or not all(math.isfinite(trade[x]) and trade[x] > 0 for x in ('price', 'qty')):
            raise ValueError('Trade público inválido')
    return (book['bids'][0][0] + book['asks'][0][0]) / 2



def _fill(db, wallet, side, qty, price, fee_rate, ts, liquidity, reason, capture, trade_id=None):
    qty = math.floor(qty * 1e8 + 1e-7) / 1e8
    if qty <= 0:
        return None
    value, fee = qty * price, qty * price * fee_rate
    if side == 'buy':
        if value + fee > wallet['cash'] + 1e-8:
            raise ValueError('Efectivo insuficiente; prohibido endeudarse')
        if wallet['qty'] * price < 5.0:
            wallet['entry_ms'], wallet['entry_day'] = ts, iso(ts)[:10]
            wallet['entries_today'] += 1
        wallet['cash'] -= value + fee
        wallet['qty'] += qty
        wallet['cost_basis'] += value + fee
        realized = 0.
    else:
        if qty > wallet['qty'] + 1e-10:
            raise ValueError('Inventario insuficiente; prohibido vender en corto')
        basis = wallet['cost_basis'] * qty / wallet['qty']
        wallet['cash'] += value - fee
        wallet['qty'] -= qty
        wallet['cost_basis'] -= basis
        realized = value - fee - basis
        wallet['realized'] += realized
        if wallet['qty'] < 1e-10:
            wallet['qty'], wallet['cost_basis'], wallet['entry_ms'] = 0., 0., None
    wallet['fees'] += fee
    wallet['fills'] += 1
    fill = {'strategy': wallet['id'], 'ts': ts, 'side': side, 'qty': qty, 'price': price,
            'value': value, 'fee': fee, 'realized': realized, 'liquidity': liquidity,
            'reason': reason, 'capture': capture, 'public_trade_id': trade_id, 'mode': 'paper'}
    db.execute('INSERT INTO fills(strategy,ts,payload) VALUES (?,?,?)', (wallet['id'], ts, _json(fill)))
    return fill


def taker(db, wallet, side, requested_qty, frame, cfg, reason, capture):
    levels = frame['order_book']['asks' if side == 'buy' else 'bids']
    remaining = min(requested_qty, wallet['qty']) if side == 'sell' else requested_qty
    total_qty = total_value = 0.
    budget = wallet['cash'] / (1 + cfg['taker_fee'])
    for price, depth in levels:
        take = min(remaining, depth)
        if side == 'buy':
            take = min(take, max(0., budget - total_value) / price)
        total_qty += take
        total_value += take * price
        remaining -= take
        if remaining < 1e-9:
            break
    if total_value < cfg['min_order_usd'] or total_qty <= 0:
        wallet['reason'] = 'Sin fill: importe mínimo o profundidad insuficiente'
        return None
    return _fill(db, wallet, side, total_qty, total_value / total_qty, cfg['taker_fee'],
                 frame['observed_ms'], 'taker', reason, capture)


def maker_fills(db, wallet, frame, variant, cfg, capture, gap):
    ts = frame['observed_ms']
    cursor = wallet.get('maker_cursor')
    trades = sorted(frame['trades'], key=lambda t: t['tid'])
    # An absent cursor indicates first observation, not permission to fill past trades.
    if cursor is None or gap or (trades and len(trades) >= frame.get('trades_page_limit', 100) and cursor < trades[0]['tid']):
        wallet['quotes'] = []
    else:
        for trade in trades:
            if trade['tid'] <= cursor:
                continue
            for quote in wallet['quotes']:
                if not quote['created_ms'] + variant['latency_seconds'] * 1000 <= trade['ts'] <= quote['expires_ms']:
                    continue
                crosses = trade['price'] < quote['price'] if quote['side'] == 'buy' else trade['price'] > quote['price']
                if not crosses or trade['side'] != quote['side']:
                    continue
                qty = min(quote['qty'], trade['qty'] * variant['participation'])
                qty = min(qty, wallet['cash'] / (quote['price'] * (1 + cfg['maker_fee']))) if quote['side'] == 'buy' else min(qty, wallet['qty'])
                fill = _fill(db, wallet, quote['side'], qty, quote['price'], cfg['maker_fee'], trade['ts'],
                             'maker', 'Trade público posterior atraviesa cotización', capture, trade['tid'])
                if fill:
                    quote['qty'] = max(0., quote['qty'] - fill['qty'])
    if trades:
        wallet['maker_cursor'] = max(cursor or 0, trades[-1]['tid'])
    wallet['quotes'] = [q for q in wallet['quotes'] if q['expires_ms'] > ts and q['qty'] > 1e-8]


def quote_market(wallet, frame, variant, cfg, mid):
    ts = frame['observed_ms']
    equity = wallet['cash'] + wallet['qty'] * mid
    inventory = wallet['qty'] * mid / equity
    skew = (inventory - variant['initial_inventory_fraction']) * variant['inventory_skew']
    center = mid * (1 - skew)
    half = max((frame['order_book']['asks'][0][0] - frame['order_book']['bids'][0][0]) / (2 * mid), cfg['maker_fee'] + variant['edge_per_side'])
    quotes = []
    for side in ('buy', 'sell'):
        price = round(center * (1 - half if side == 'buy' else 1 + half), 2)
        # Never create a crossing maker order.
        price = min(price, frame['order_book']['bids'][0][0]) if side == 'buy' else max(price, frame['order_book']['asks'][0][0])
        if side == 'buy':
            room = max(0., equity * variant['max_inventory_fraction'] - wallet['qty'] * mid)
            amount = min(variant['quote_usd'], room, wallet['cash'] / (1 + cfg['maker_fee']))
        else:
            amount = min(variant['quote_usd'], wallet['qty'] * price)
        if amount < cfg['min_order_usd']:
            continue
        quotes.append({'side': side, 'price': price, 'qty': math.floor(amount / price * 1e8) / 1e8,
                       'created_ms': ts, 'expires_ms': ts + variant['quote_ttl_seconds'] * 1000})
    wallet['quotes'] = quotes
    wallet['reason'] = 'Cotizaciones con inventario y efectivo propios'


def tick(directory, frame, *, proof=None):
    cfg = plan()
    with closing(connect(directory)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        manifest = json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        if manifest['plan_sha256'] != canonical_hash(cfg):
            raise ValueError('El protocolo cambió después de crear las carteras')
        if manifest['kind'] == 'paper':
            if proof is None:
                raise ValueError('La simulación requiere preregistro aprobado y commits verificables')
            expected = execution_proof(proof['commit'])
            if expected != proof:
                raise ValueError('Prueba Git inconsistente')
            frozen = manifest.get('proof')
            if frozen and frozen != proof:
                raise ValueError('Código distinto de la versión congelada')
            manifest['proof'] = proof
        mid = validate_frame(frame, manifest['kind'])
        ts = frame['observed_ms']
        previous = db.execute('SELECT MAX(observed_ms) FROM captures').fetchone()[0]
        if previous is not None and ts <= previous:
            return {'status': 'duplicate', 'fills': 0}
        capture = canonical_hash(frame)
        compact = {k: v for k, v in frame.items() if k != 'candles'}
        compact['candles'] = {}
        for interval, rows in frame['candles'].items():
            checksum = canonical_hash(rows)
            db.execute('INSERT OR IGNORE INTO inputs VALUES (?,?)', (checksum, zlib.compress(_json(rows).encode())))
            compact['candles'][interval] = checksum
        db.execute('INSERT INTO captures VALUES (?,?,?)', (capture, ts, _json(compact)))
        fills_before = db.execute('SELECT COUNT(*) FROM fills').fetchone()[0]
        gap = previous is None or ts - previous > cfg['max_book_age_seconds'] * 1000
        manifest.setdefault('started_at', iso(ts))
        manifest.setdefault('benchmark_price', frame['order_book']['asks'][0][0])
        db.execute("UPDATE meta SET value=? WHERE key='manifest'", (_json(manifest),))
        for variant in cfg['variants']:
            wid = variant['id']
            wallet = json.loads(db.execute('SELECT payload FROM wallets WHERE id=?', (wid,)).fetchone()[0])
            if wid == 'market-making-v1':
                maker_fills(db, wallet, frame, variant, cfg, capture, gap)
            equity = wallet['cash'] + wallet['qty'] * mid
            wallet['peak'] = max(wallet['peak'], equity)
            day = iso(ts)[:10]
            if wallet['day'] != day:
                wallet.update(day=day, day_start=equity, entries_today=0, daily_paused=False)
            if equity <= wallet['peak'] * (1 - cfg['max_drawdown']):
                wallet['risk_stopped'] = True
            if equity <= wallet['day_start'] * (1 - cfg['max_daily_loss']):
                wallet['daily_paused'] = True
            inhibited = wallet['paused'] or wallet['risk_stopped'] or wallet['daily_paused']
            reason_before = wallet['reason']
            if inhibited:
                wallet['quotes'] = []
                wallet['status'] = 'risk_stopped' if wallet['risk_stopped'] else 'paused'
                wallet['reason'] = 'Pausa manual: conserva inventario' if wallet['paused'] else 'Freno de pérdida: reduce inventario'
                if not wallet['paused'] and wallet['qty']:
                    taker(db, wallet, 'sell', wallet['qty'], frame, cfg, wallet['reason'], capture)
            elif wid == 'market-making-v1':
                wallet['status'] = 'running'
                if not wallet['mm_seeded']:
                    taker(db, wallet, 'buy', equity * variant['initial_inventory_fraction'] / mid, frame, cfg, 'Compra inicial de inventario', capture)
                    wallet['mm_seeded'] = True
                if not wallet['quotes']:
                    quote_market(wallet, frame, variant, cfg, mid)
            else:
                rows = frame['candles'][variant['timeframe']]
                latest = rows[-1][0]
                wallet['status'] = 'running'
                if latest != wallet['last_bar']:
                    target, reason = directional_signal(variant, rows, wallet, ts)
                    wallet['reason'], wallet['last_bar'] = reason, latest
                    if target is not None:
                        target = min(cfg['max_exposure'], max(0., target))
                        current = wallet['qty'] * mid / equity
                        band = variant.get('band', 0.)
                        if abs(target - current) > band:
                            delta = equity * target / mid - wallet['qty']
                            taker(db, wallet, 'buy' if delta > 0 else 'sell', abs(delta), frame, cfg, reason, capture)
            equity = wallet['cash'] + wallet['qty'] * mid
            wallet['peak'] = max(wallet['peak'], equity)
            wallet.update(equity=equity, mark=mid, observed_ms=ts, drawdown=equity / wallet['peak'] - 1,
                          unrealized=wallet['qty'] * mid - wallet['cost_basis'])
            if wallet['cash'] < -1e-8 or wallet['qty'] < -1e-10:
                raise ValueError('La contabilidad produjo deuda o cortos')
            if abs((equity - 1000) - wallet['realized'] - wallet['unrealized']) > 1e-6:
                raise ValueError('Resultado realizado y abierto no concilian')
            db.execute('UPDATE wallets SET payload=? WHERE id=?', (_json(wallet), wid))
            point = {'ts': ts, 'equity': equity, 'pnl': equity - 1000, 'fees': wallet['fees'], 'drawdown': wallet['drawdown']}
            db.execute('INSERT INTO equity(strategy,ts,payload) VALUES (?,?,?)', (wid, ts, _json(point)))
            if wallet['reason'] != reason_before or previous is None:
                db.execute('INSERT INTO decisions(strategy,ts,payload) VALUES (?,?,?)',
                           (wid, ts, _json({'strategy': wid, 'ts': ts, 'reason': wallet['reason'], 'capture': capture})))
        db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   ('health', _json({'status': 'ok', 'observed_ms': ts, 'error': None})))
        return {'status': 'ok', 'capture': capture, 'fills': db.execute('SELECT COUNT(*) FROM fills').fetchone()[0] - fills_before}


def record_error(directory, message):
    with closing(connect(directory)) as db, db:
        health = {'status': 'error', 'observed_ms': now_ms(), 'error': str(message)[:400]}
        db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('health', _json(health)))
        db.execute('INSERT INTO events(ts,payload) VALUES (?,?)', (now_ms(), _json(health)))
        # No stale quotes survive an outage, and no historical fills are reconstructed.
        for wid, raw in db.execute('SELECT id,payload FROM wallets').fetchall():
            wallet = json.loads(raw)
            wallet['quotes'] = []
            db.execute('UPDATE wallets SET payload=? WHERE id=?', (_json(wallet), wid))


def control(directory, strategy, action):
    if strategy not in NAMES or action not in ('pause', 'resume'):
        raise ValueError('Acción desconocida')
    with closing(connect(directory)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        wallet = json.loads(db.execute('SELECT payload FROM wallets WHERE id=?', (strategy,)).fetchone()[0])
        if action == 'resume' and wallet['risk_stopped']:
            raise ValueError('El freno permanente no se reinicia desde el panel')
        wallet['paused'] = action == 'pause'
        wallet['quotes'] = []
        wallet['status'] = 'paused' if wallet['paused'] else 'waiting'
        wallet['reason'] = 'Pausa manual: conserva inventario' if wallet['paused'] else 'Espera el próximo ciclo'
        db.execute('UPDATE wallets SET payload=? WHERE id=?', (_json(wallet), strategy))
        db.execute('INSERT INTO events(ts,payload) VALUES (?,?)', (now_ms(), _json({'strategy': strategy, 'action': action})))


def status(directory):
    path = Path(directory) / DB_NAME
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        meta = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM meta')}
        wallets = [json.loads(r[0]) for r in db.execute('SELECT payload FROM wallets ORDER BY rowid')]
        latest = db.execute('SELECT MAX(observed_ms) FROM captures').fetchone()[0]
        fills = [json.loads(r[0]) for r in db.execute('SELECT payload FROM fills ORDER BY id DESC LIMIT 250')]
        decisions = [json.loads(r[0]) for r in db.execute('SELECT payload FROM decisions ORDER BY id DESC LIMIT 100')]
        events = [json.loads(r[0]) for r in db.execute('SELECT payload FROM events ORDER BY id DESC LIMIT 30')]
        history = {}
        for wid in NAMES:
            bounds = db.execute('SELECT MIN(ts),MAX(ts) FROM equity WHERE strategy=?', (wid,)).fetchone()
            if bounds[0] is None:
                history[wid] = []
                continue
            width = max(1, math.ceil((bounds[1] - bounds[0] + 1) / 399))
            # SQLite selects payload from the MAX(id) row within each time bin.
            sampled = db.execute('SELECT payload,MAX(id) FROM equity WHERE strategy=? GROUP BY CAST((ts-?)/? AS INT) ORDER BY MAX(id)', (wid, bounds[0], width)).fetchall()
            first = db.execute('SELECT payload FROM equity WHERE strategy=? ORDER BY ts LIMIT 1', (wid,)).fetchone()
            points = [json.loads(r[0]) for r in sampled]
            if points and json.loads(first[0])['ts'] < points[0]['ts']:
                points.insert(0, json.loads(first[0]))
            history[wid] = points
        counts = {'captures': db.execute('SELECT COUNT(*) FROM captures').fetchone()[0], 'fills': db.execute('SELECT COUNT(*) FROM fills').fetchone()[0]}
    manifest = meta['manifest']
    benchmark = None
    if manifest.get('benchmark_price') and wallets[0].get('mark'):
        benchmark = 1000 / (manifest['benchmark_price'] * (1 + manifest['plan']['taker_fee'])) * wallets[0]['mark']
    return {'mode': 'paper', 'kind': manifest['kind'], 'manifest': manifest, 'wallets': wallets,
            'health': meta.get('health', {'status': 'waiting'}), 'stale': latest is None or now_ms() - latest > 90_000,
            'last_observed_ms': latest, 'history': history, 'fills': fills, 'decisions': decisions, 'events': events,
            'counts': counts, 'benchmark_equity': benchmark, 'total_equity': sum(w['equity'] for w in wallets),
            'capital_usd': 4000, 'execution_authorized': bool(manifest.get('proof')),
            'profitability_verified': False, 'live_authorized': False}


def backup(directory, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('El respaldo debe ser nuevo')
    with closing(connect(directory)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Respaldo inválido')
    return {'file': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}


def restore(source, directory):
    target = arena_path(directory)
    if target.exists():
        raise ValueError('La restauración exige destino vacío')
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as src:
        if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Copia inválida')
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    # Restoring does not start an execution process.
    return status(directory)



def audit(directory):
    """Verify recorded inputs and reconcile independent cash/positions from fills."""
    with closing(sqlite3.connect((Path(directory) / DB_NAME).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite no conserva integridad')
        inputs = {}
        for checksum, payload in db.execute('SELECT sha,payload FROM inputs'):
            rows = json.loads(zlib.decompress(payload))
            if canonical_hash(rows) != checksum:
                raise ValueError('Las velas archivadas fueron alteradas')
            inputs[checksum] = rows
        captures = 0
        for checksum, raw in db.execute('SELECT id,payload FROM captures'):
            payload = json.loads(raw)
            payload['candles'] = {k: inputs[v] for k, v in payload['candles'].items()}
            if canonical_hash(payload) != checksum:
                raise ValueError('La captura de mercado fue alterada')
            captures += 1
        books = {wid: {'cash': 1000., 'qty': 0., 'fees': 0.} for wid in NAMES}
        fills = 0
        for raw, in db.execute('SELECT payload FROM fills ORDER BY id'):
            fill = json.loads(raw)
            book = books[fill['strategy']]
            value = fill['qty'] * fill['price']
            if abs(value - fill['value']) > 1e-7:
                raise ValueError('Fill inconsistente')
            book['cash'] += (-value - fill['fee']) if fill['side'] == 'buy' else (value - fill['fee'])
            book['qty'] += fill['qty'] if fill['side'] == 'buy' else -fill['qty']
            book['fees'] += fill['fee']
            if book['cash'] < -1e-7 or book['qty'] < -1e-8:
                raise ValueError('Fill sin financiación o sin inventario')
            fills += 1
        for wid, raw in db.execute('SELECT id,payload FROM wallets'):
            wallet = json.loads(raw)
            if any(abs(wallet[key] - books[wid][key]) > 1e-7 for key in ('cash', 'qty', 'fees')):
                raise ValueError('El historial no concilia con el saldo')
    return {'status': 'verified', 'captures': captures, 'candle_inputs': len(inputs),
            'fills': fills, 'wallets': 4, 'profitability_verified': False, 'live_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'status', 'once', 'run', 'backup', 'restore', 'audit'])
    parser.add_argument('--directory', type=Path, default=ROOT / 'runtime-data/arena-paper')
    parser.add_argument('--preregistration-commit')
    parser.add_argument('--file', type=Path)
    args = parser.parse_args()
    if args.action == 'restore':
        print(_json(restore(args.file, args.directory)))
        return
    initialize(args.directory)
    if args.action == 'init':
        print('Cuatro carteras creadas con US$1,000 ficticios cada una')
    elif args.action == 'status':
        print(_json(status(args.directory)))
    elif args.action == 'audit':
        print(_json(audit(args.directory)))
    elif args.action == 'backup':
        print(_json(backup(args.directory, args.file)))
    else:
        import fcntl
        from .arena_market import PublicFeed
        cfg = plan()
        proof = execution_proof(args.preregistration_commit or '')
        with (args.directory / 'arena-worker.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            feed = PublicFeed()
            while True:
                try:
                    print(_json(tick(args.directory, feed.capture(), proof=proof)), flush=True)
                except Exception as exc:
                    record_error(args.directory, exc)
                    if args.action == 'once':
                        raise
                    print(_json({'status': 'error', 'message': str(exc)[:300]}), flush=True)
                if args.action == 'once':
                    break
                time.sleep(cfg['poll_seconds'])


if __name__ == '__main__':
    main()
