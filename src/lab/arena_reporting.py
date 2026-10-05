"""Read-only daily accounting from the complete ledger, in Mexico City time."""
from contextlib import closing as closing_connection
import csv
from datetime import datetime, time as daytime, timedelta
import io
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .arena import DB_NAME, NAMES, now_ms

TZ_NAME = 'America/Mexico_City'
TZ = ZoneInfo(TZ_NAME)
FRESH_MS = 90_000


def _date(ts):
    return datetime.fromtimestamp(ts / 1000, TZ).date()


def _midnight(day):
    return int(datetime.combine(day, daytime.min, TZ).timestamp() * 1000)


def _quality(samples, start, end):
    """Fraction of time with an observation no more than 90 seconds old."""
    cursor = start
    gaps = []
    for ts in samples:
        a, b = max(start, ts), min(end, ts + FRESH_MS)
        if b <= start or a >= end:
            continue
        if a > cursor:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < end:
        gaps.append((cursor, end))
    missing = sum(b - a for a, b in gaps)
    duration = max(0, end - start)
    return {'coverage': 1 - missing / duration if duration else None,
            'missing_seconds': missing / 1000, 'gaps': len(gaps),
            'longest_gap_seconds': max((b - a for a, b in gaps), default=0) / 1000}


def daily_report(directory, *, at_ms=None):
    current = now_ms() if at_ms is None else at_ms
    uri = (Path(directory) / DB_NAME).resolve().as_uri() + '?mode=ro'
    # A single read transaction keeps balances, fills and valuation timestamps coherent.
    with closing_connection(sqlite3.connect(uri, uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        meta = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM meta')}
        wallets = {k: json.loads(v) for k, v in db.execute('SELECT id,payload FROM wallets')}
        captures = [r[0] for r in db.execute('SELECT observed_ms FROM captures WHERE observed_ms<=? ORDER BY observed_ms', (current,))]
        points = [(wid, ts, json.loads(raw)) for wid, ts, raw in db.execute(
            'SELECT strategy,ts,payload FROM equity WHERE ts<=? ORDER BY ts,id', (current,))]
        fills = [json.loads(r[0]) for r in db.execute('SELECT payload FROM fills WHERE ts<=? ORDER BY ts,id', (current,))]
        events = [(ts, json.loads(raw)) for ts, raw in db.execute('SELECT ts,payload FROM events WHERE ts<=? ORDER BY ts,id', (current,))]
        decisions = [(wid, ts, json.loads(raw)) for wid, ts, raw in db.execute('SELECT strategy,ts,payload FROM decisions WHERE ts<=? ORDER BY ts,id', (current,))]
    manifest = meta['manifest']
    result = {'timezone': TZ_NAME, 'generated_at_ms': current, 'as_of_ms': captures[-1] if captures else None,
              'mode': 'paper', 'kind': manifest['kind'], 'capital_usd': 4000,
              'health': meta.get('health', {'status': 'waiting'}),
              'stale': not captures or current - captures[-1] > FRESH_MS,
              'profitability_verified': False, 'days': [],
              'method': 'Cambio de patrimonio entre últimas valoraciones diarias. Comisiones ya incluidas; sin aportaciones ni retiros.',
              'coverage_method': 'Porcentaje del periodo con una observación de hasta 90 segundos de antigüedad; no equivale a disponibilidad del servidor.'}
    # Independently reconstruct cash, holdings and paid fees from the full fill ledger.
    reconstructed = {wid: {'cash': 1000., 'qty': 0., 'fees': 0.} for wid in NAMES}
    issues = []
    for f in fills:
        w = reconstructed[f['strategy']]
        value = f['qty'] * f['price']
        if abs(value - f['value']) > 1e-7:
            issues.append('Importe inconsistente en una operación')
        w['cash'] += (-value - f['fee']) if f['side'] == 'buy' else (value - f['fee'])
        w['qty'] += f['qty'] if f['side'] == 'buy' else -f['qty']
        w['fees'] += f['fee']
        if w['cash'] < -1e-7 or w['qty'] < -1e-8:
            issues.append('Operación sin efectivo o inventario suficiente')
    for wid, expected in reconstructed.items():
        if any(abs(wallets[wid][k] - v) > 1e-7 for k, v in expected.items()):
            issues.append(f'Saldo no conciliado: {NAMES[wid]}')
        w = wallets[wid]
        if 'unrealized' in w and abs(w['equity'] - 1000 - w['realized'] - w['unrealized']) > 1e-6:
            issues.append(f'Resultado no conciliado: {NAMES[wid]}')
    result['ledger'] = {'reconciled': not issues, 'issues': sorted(set(issues)),
                        'fills_checked': len(fills), 'wallets_checked': len(wallets),
                        'scope': 'Efectivo, inventario, comisiones y resultado; los hashes se verifican por separado.'}
    if not captures:
        return result
    start = datetime.fromisoformat(manifest['started_at']).timestamp() * 1000 if manifest.get('started_at') else captures[0]
    first, today = _date(start), _date(current)
    buckets = {}
    day = first
    while day <= today:
        buckets[day] = {'points': {wid: [] for wid in NAMES}, 'fills': {wid: [] for wid in NAMES},
                        'events': [], 'decisions': {wid: [] for wid in NAMES}}
        day += timedelta(days=1)
    for wid, ts, point in points:
        if _date(ts) in buckets:
            buckets[_date(ts)]['points'][wid].append(point)
    for f in fills:
        if _date(f['ts']) in buckets:
            buckets[_date(f['ts'])]['fills'][f['strategy']].append(f)
    for ts, e in events:
        if _date(ts) in buckets:
            # Never expose proof bodies or other internal records through this view.
            buckets[_date(ts)]['events'].append({'ts': ts, 'type': e.get('action', e.get('status', 'event')),
                                                'strategy': e.get('strategy'), 'message': str(e.get('error', ''))[:400]})
    for wid, ts, d in decisions:
        if _date(ts) in buckets:
            buckets[_date(ts)]['decisions'][wid].append(d)
    previous = {wid: 1000. for wid in NAMES}
    previous_day_observed = True
    for day, b in buckets.items():
        beginning, end = _midnight(day), min(current, _midnight(day + timedelta(days=1)))
        window_start = max(start, beginning)
        quality = _quality(captures, window_start, end)
        rows = []
        for wid, name in NAMES.items():
            ps, fs = b['points'][wid], b['fills'][wid]
            opening = previous[wid] if previous_day_observed else None
            closing = ps[-1]['equity'] if ps else None
            net = closing - opening if closing is not None and opening is not None else None
            fees = sum(f['fee'] for f in fs)
            realized = sum(f['realized'] for f in fs)
            peak, worst = opening, 0.
            for point in ps:
                peak = max(peak or point['equity'], point['equity'])
                worst = min(worst, point['equity'] / peak - 1) if peak else worst
            rows.append({'id': wid, 'name': name, 'opening_equity': opening, 'closing_equity': closing,
                         'net_pnl': net, 'return': net / opening if net is not None and opening else None,
                         'before_fees_pnl': net + fees if net is not None else None, 'fees': fees,
                         'realized_pnl': realized, 'unrealized_change': net - realized if net is not None else None,
                         'operations': len(fs), 'buys': sum(f['side'] == 'buy' for f in fs),
                         'sells': sum(f['side'] == 'sell' for f in fs),
                         'max_drawdown': worst if ps else None, 'observations': len(ps),
                         'as_of_ms': ps[-1]['ts'] if ps else None,
                         'decision_count': len(b['decisions'][wid]),
                         'last_decision': b['decisions'][wid][-1]['reason'] if b['decisions'][wid] else None})
            previous[wid] = closing
        complete = all(r['closing_equity'] is not None for r in rows)
        opening = sum(r['opening_equity'] for r in rows) if all(r['opening_equity'] is not None for r in rows) else None
        closing = sum(r['closing_equity'] for r in rows) if complete else None
        net = closing - opening if closing is not None and opening is not None else None
        observations = len([ts for ts in captures if beginning <= ts < _midnight(day + timedelta(days=1))])
        if any(r['observations'] != observations for r in rows):
            result['ledger']['reconciled'] = False
            result['ledger']['issues'].append(f'Valoraciones incompletas el {day.isoformat()}')
        row = {'date': day.isoformat(), 'in_progress': day == today,
               'partial_start': day == first and start > beginning, 'no_data': not observations,
               'opening_missing': opening is None, 'from_ms': window_start, 'until_ms': end,
               'as_of_ms': max((r['as_of_ms'] or 0 for r in rows), default=0) or None,
               'opening_equity': opening, 'closing_equity': closing, 'net_pnl': net,
               'return': net / opening if net is not None and opening else None,
               'fees': sum(r['fees'] for r in rows), 'operations': sum(r['operations'] for r in rows),
               'realized_pnl': sum(r['realized_pnl'] for r in rows), 'quality': quality,
               'error_count': sum(e['type'] == 'error' for e in b['events']),
               'event_count': len(b['events']), 'events': b['events'][-100:], 'strategies': rows}
        result['days'].append(row)
        previous_day_observed = complete
    result['days'].reverse()
    result['observed_days'] = sum(not d['no_data'] for d in result['days'])
    return result


def report_csv(report):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['fecha_cdmx', 'cartera', 'inicio_usd', 'ultima_valoracion_usd', 'resultado_neto_usd',
                     'rendimiento_pct', 'comisiones_usd', 'operaciones', 'compras', 'ventas',
                     'realizado_usd', 'cambio_no_realizado_usd', 'caida_maxima_pct',
                     'cobertura_datos_pct', 'errores', 'dia_en_curso', 'inicio_parcial', 'sin_datos', 'zona_horaria'])
    def amount(value, multiplier=1):
        return '' if value is None else round(value * multiplier, 8)
    for day in report['days']:
        for r in day['strategies']:
            writer.writerow([day['date'], r['name'], amount(r['opening_equity']), amount(r['closing_equity']),
                             amount(r['net_pnl']), amount(r['return'], 100), amount(r['fees']), r['operations'],
                             r['buys'], r['sells'], amount(r['realized_pnl']), amount(r['unrealized_change']),
                             amount(r['max_drawdown'], 100), amount(day['quality']['coverage'], 100),
                             day['error_count'], day['in_progress'], day['partial_start'], day['no_data'], report['timezone']])
    return '\ufeff' + stream.getvalue()
