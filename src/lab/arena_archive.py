"""Archivo de consulta de la arena v1 (F2): resultados finales, sin capturas crudas de mercado.

Se genera una sola vez desde la copia restaurada y auditada del respaldo final
(`lab.arena_maintenance`) y vive en `archive/arena-v1/`. El panel lo lee del disco cuando se pide.
La contabilidad no se recalcula aquí: sale de `lab.arena.status`, `lab.arena_fees.report` y
`lab.arena_reporting.daily_report` sobre la misma base.

    python -m lab.arena_archive build  --db RESTAURADA/arena.sqlite3 --out archive/arena-v1 --inventory inventario-contenedor.json
    python -m lab.arena_archive verify --db RESTAURADA/arena.sqlite3 --archive archive/arena-v1
"""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3

from . import arena
from .arena_fees import PREREG as FEES_PREREG, report as fee_report
from .arena_reporting import daily_report

KIND = 'arena-archive-v1'
FILL_COLUMNS = ('id', 'strategy', 'ts', 'ts_iso', 'side', 'qty', 'price', 'value', 'fee', 'realized',
                'liquidity', 'reason', 'capture', 'public_trade_id', 'mode', 'fee_context')
DECISION_COLUMNS = ('id', 'strategy', 'ts', 'ts_iso', 'reason', 'capture')
CURVE_COLUMNS = ('strategy', 'ts_iso', 'equity', 'pnl', 'fees', 'drawdown')
NUMERIC = {'id', 'ts', 'qty', 'price', 'value', 'fee', 'realized', 'equity', 'pnl', 'fees', 'drawdown'}
PREREGISTRATION_FILES = ('reports/four_strategy_arena_v1_preregistro.md', 'reports/arena_fees_v2_preregistro.md',
                         'configs/arena/four_strategies_v1.json', 'configs/arena/bitso_fees_v2.json')
ARENA_PREREG = '61c6ac319f9f5421a4c1b9ad80e5d5165b2fcc72'  # lab.arena_hosted.PREREG


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace('+00:00', 'Z')


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + '\n'


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _directory(db_path: Path) -> Path:
    db_path = Path(db_path)
    directory = db_path if db_path.is_dir() else db_path.parent
    if not (directory / arena.DB_NAME).is_file():
        raise ValueError(f'No hay {arena.DB_NAME} en {directory.name}')
    return directory


def _connect(directory: Path):
    uri = (directory / arena.DB_NAME).resolve().as_uri() + '?mode=ro&immutable=1'
    db = sqlite3.connect(uri, uri=True)
    db.execute('PRAGMA query_only=ON')
    return db


def _csv(rows: list[dict], columns: tuple[str, ...]) -> str:
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(columns)
    for row in rows:
        writer.writerow(['' if row.get(c) is None else
                         json.dumps(row[c], sort_keys=True, ensure_ascii=False) if isinstance(row.get(c), (dict, list))
                         else repr(row[c]) if isinstance(row.get(c), float) else row[c] for c in columns])
    return out.getvalue()


def _read_csv(path: Path) -> list[dict]:
    rows = []
    with path.open(newline='', encoding='utf-8') as stream:
        for raw in csv.DictReader(stream):
            row = {}
            for key, value in raw.items():
                if value == '':
                    row[key] = None
                elif key in NUMERIC:
                    row[key] = int(value) if key in ('id', 'ts') else float(value)
                elif key == 'fee_context':
                    row[key] = json.loads(value)
                else:
                    row[key] = value
            rows.append(row)
    return rows


def _read_db(directory: Path) -> dict:
    with closing(_connect(directory)) as db:
        db.execute('BEGIN')
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        bounds = db.execute('SELECT MIN(observed_ms), MAX(observed_ms) FROM captures').fetchone()
        wallets = [json.loads(r[0]) for r in db.execute('SELECT payload FROM wallets ORDER BY rowid')]
        fills = [{'id': fid, **json.loads(raw)} for fid, raw in db.execute('SELECT id,payload FROM fills ORDER BY id')]
        decisions = [{'id': did, **json.loads(raw)} for did, raw in db.execute('SELECT id,payload FROM decisions ORDER BY id')]
        events = [{'id': eid, 'ts': ts, 'ts_iso': _iso(ts), 'payload': json.loads(raw)}
                  for eid, ts, raw in db.execute('SELECT id,ts,payload FROM events ORDER BY id')]
        hours = {}
        first, last = {}, {}
        for wid, ts, raw in db.execute('SELECT strategy,ts,payload FROM equity ORDER BY ts,id'):
            point = json.loads(raw)
            first.setdefault(wid, point)
            last[wid] = point
            hours[(wid, ts // 3_600_000)] = point
    curve = {(wid, p['ts']): p for wid, p in first.items()}
    curve.update({(wid, p['ts']): p for (wid, _), p in hours.items()})
    curve.update({(wid, p['ts']): p for wid, p in last.items()})
    order = {wid: i for i, wid in enumerate(arena.NAMES)}
    points = [{'strategy': wid, 'ts_iso': _iso(p['ts']), 'equity': p['equity'], 'pnl': p['pnl'],
               'fees': p['fees'], 'drawdown': p['drawdown']}
              for (wid, _), p in sorted(curve.items(), key=lambda kv: (order[kv[0][0]], kv[0][1]))]
    for row in fills + decisions:
        row['ts_iso'] = _iso(row['ts'])
    return {'counts': counts, 'first_ms': bounds[0], 'last_ms': bounds[1], 'wallets': wallets,
            'fills': fills, 'decisions': decisions, 'events': events, 'curve': points}


def _summary(data: dict, status: dict, fees: dict) -> dict:
    by_fee = {s['id']: s for s in fees['strategies']}
    strategies = []
    for wallet in data['wallets']:
        wid = wallet['id']
        strategies.append({'id': wid, 'name': arena.NAMES[wid], 'initial_usd': 1000.0, 'equity_usd': wallet['equity'],
                           'pnl_usd': wallet['equity'] - 1000.0, 'fees_usd': wallet['fees'], 'fills': wallet['fills'],
                           'maker_fills': by_fee[wid]['maker_fills'], 'taker_fills': by_fee[wid]['taker_fills'],
                           'realized_usd': wallet['realized'], 'qty_btc': wallet['qty'], 'status': wallet['status']})
    equity = sum(s['equity_usd'] for s in strategies)
    return {'total': {'initial_usd': 4000.0, 'equity_usd': equity, 'pnl_usd': equity - 4000.0,
                      'fees_usd': sum(s['fees_usd'] for s in strategies), 'fills': len(data['fills'])},
            'strategies': strategies,
            'benchmark_equity_usd_per_1000': status.get('benchmark_equity'),
            'final_mark_usd': data['wallets'][0].get('mark'),
            'as_of': _iso(data['last_ms']) if data['last_ms'] else None,
            'mode': 'paper', 'live_authorized': False, 'profitability_verified': False}


def build(db_path: Path, out_dir: Path, source: dict) -> dict:
    """Genera el archivo en una carpeta nueva. `source` describe el respaldo de origen."""
    directory, out_dir = _directory(db_path), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError('El archivo debe generarse en una carpeta vacía')
    data = _read_db(directory)
    at_ms = data['last_ms'] or 0
    status = arena.status(directory)
    fees = fee_report(directory, at_ms=at_ms)
    daily = daily_report(directory, at_ms=at_ms)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'preregistros').mkdir()
    files = {
        'resumen.json': _dumps(_summary(data, status, fees)),
        'carteras_finales.json': _dumps(data['wallets']),
        'operaciones.csv': _csv(data['fills'], FILL_COLUMNS),
        'decisiones.csv': _csv(data['decisions'], DECISION_COLUMNS),
        'eventos.json': _dumps(data['events']),
        'curva.csv': _csv(data['curve'], CURVE_COLUMNS),
        'auditoria_diaria.json': _dumps(daily),
        'comisiones.json': _dumps(fees),
    }
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding='utf-8')
    for rel in PREREGISTRATION_FILES:
        shutil.copyfile(arena.ROOT / rel, out_dir / 'preregistros' / Path(rel).name)
    hashes = {str(p.relative_to(out_dir)): _sha(p) for p in sorted(out_dir.rglob('*'))
              if p.is_file() and p.name != 'manifest.json'}
    manifest = {
        'kind': KIND, 'mode': 'paper', 'live_authorized': False,
        'source': {'backup_sha256': source.get('backup_sha256'), 'backup_bytes': source.get('backup_bytes'),
                   'backup_directory': source.get('backup_directory'), 'method': 'lab.arena.backup',
                   'restored_and_audited': bool(source.get('restored_and_audited', True))},
        'generated_from_counts': data['counts'],
        'period': {'first_capture_iso': _iso(data['first_ms']) if data['first_ms'] else None,
                   'last_capture_iso': _iso(data['last_ms']) if data['last_ms'] else None},
        'as_of': _iso(at_ms) if at_ms else None,
        'curve_sampling': 'último punto de cada hora UTC por estrategia, más el primero y el último',
        'files': hashes,
        'excluded': {'captures': data['counts'].get('captures'), 'inputs': data['counts'].get('inputs'),
                     'equity_rows': data['counts'].get('equity'),
                     'note': 'capturas crudas de mercado; viven en el respaldo de la USB'},
        'preregistrations': [{'file': f'preregistros/{Path(rel).name}', 'origin': rel} for rel in PREREGISTRATION_FILES]
                            + [{'commit': ARENA_PREREG, 'protocol': 'four-strategy-arena-v1'},
                               {'commit': FEES_PREREG, 'protocol': 'arena-fees-v2'}],
    }
    (out_dir / 'manifest.json').write_text(_dumps(manifest), encoding='utf-8')
    return manifest


def verify(db_path: Path, archive_dir: Path) -> dict:
    """Compara el archivo con la base: fills, comisiones, resultados, carteras y huellas."""
    directory, archive_dir = _directory(db_path), Path(archive_dir)
    data = _read_db(directory)
    status = arena.status(directory)
    checks, errors = {}, []

    def check(name, ok, detail=''):
        checks[name] = bool(ok)
        if not ok:
            errors.append(f'{name}: {detail}'.rstrip(': '))

    manifest = json.loads((archive_dir / 'manifest.json').read_text(encoding='utf-8'))
    bad = [n for n, h in manifest['files'].items() if not (archive_dir / n).is_file() or _sha(archive_dir / n) != h]
    extra = [str(p.relative_to(archive_dir)) for p in archive_dir.rglob('*')
             if p.is_file() and p.name != 'manifest.json' and str(p.relative_to(archive_dir)) not in manifest['files']]
    check('huellas', not bad and not extra, f'distintas {bad}, sin registrar {extra}')
    check('conteos', manifest['generated_from_counts'] == data['counts'], 'conteos de la base distintos')
    archived = _read_csv(archive_dir / 'operaciones.csv')
    check('numero_de_fills', len(archived) == len(data['fills']), f'{len(archived)} contra {len(data["fills"])}')
    keys = ('id', 'strategy', 'ts', 'side', 'qty', 'price', 'fee', 'value', 'liquidity')
    mismatched = [a.get('id') for a, d in zip(archived, data['fills']) if any(a.get(k) != d.get(k) for k in keys)]
    check('fills', not mismatched and len(archived) == len(data['fills']), f'ids distintos {mismatched[:5]}')
    summary = json.loads((archive_dir / 'resumen.json').read_text(encoding='utf-8'))
    db_wallets = {w['id']: w for w in data['wallets']}
    rows = {s['id']: s for s in summary['strategies']}
    fees_by_csv = {}
    for row in archived:
        fees_by_csv[row['strategy']] = fees_by_csv.get(row['strategy'], 0.0) + row['fee']
    check('comisiones_por_estrategia', set(rows) == set(db_wallets) and all(
        rows[w]['fees_usd'] == db_wallets[w]['fees'] and abs(fees_by_csv.get(w, 0.0) - db_wallets[w]['fees']) < 1e-6
        for w in db_wallets), 'comisiones distintas')
    check('comisiones_totales', abs(summary['total']['fees_usd'] - sum(w['fees'] for w in data['wallets'])) < 1e-9,
          'total de comisiones distinto')
    check('resultado_por_estrategia', all(
        rows[w]['equity_usd'] == db_wallets[w]['equity'] and rows[w]['pnl_usd'] == db_wallets[w]['equity'] - 1000.0
        for w in db_wallets if w in rows), 'patrimonio distinto')
    check('resultado_total', abs(summary['total']['equity_usd'] - status['total_equity']) < 1e-9
          and summary['total']['fills'] == len(data['fills']), 'patrimonio total distinto')
    wallets = json.loads((archive_dir / 'carteras_finales.json').read_text(encoding='utf-8'))
    check('carteras_finales', wallets == data['wallets'], 'carteras distintas')
    check('decisiones', len(_read_csv(archive_dir / 'decisiones.csv')) == len(data['decisions']), 'decisiones distintas')
    events = json.loads((archive_dir / 'eventos.json').read_text(encoding='utf-8'))
    check('eventos', events == data['events'], 'eventos distintos')
    return {'ok': all(checks.values()), 'checks': checks, 'errors': errors,
            'fills': len(data['fills']), 'equity_usd': summary['total']['equity_usd'],
            'fees_usd': summary['total']['fees_usd']}


def load(archive_dir: Path) -> dict:
    """Lectura para el panel: resumen, curva, comisiones, auditoría resumida y manifiesto."""
    archive_dir = Path(archive_dir)
    manifest = json.loads((archive_dir / 'manifest.json').read_text(encoding='utf-8'))
    summary = json.loads((archive_dir / 'resumen.json').read_text(encoding='utf-8'))
    fees = json.loads((archive_dir / 'comisiones.json').read_text(encoding='utf-8'))
    daily = json.loads((archive_dir / 'auditoria_diaria.json').read_text(encoding='utf-8'))
    curve = _read_csv(archive_dir / 'curva.csv')
    days = [{'date': d['date'], 'opening_equity': d['opening_equity'], 'closing_equity': d['closing_equity'],
             'net_pnl': d['net_pnl'], 'fees': d['fees'], 'operations': d['operations'], 'no_data': d['no_data'],
             'partial_start': d['partial_start'], 'error_count': d['error_count'],
             'strategies': [{'id': s.get('id'), 'closing_equity': s.get('closing_equity'), 'net_pnl': s.get('net_pnl'),
                             'fees': s.get('fees'), 'operations': s.get('operations')} for s in d['strategies']]}
            for d in daily['days']]
    return {'manifest': {k: manifest[k] for k in ('kind', 'source', 'period', 'as_of', 'excluded', 'generated_from_counts',
                                                    'curve_sampling', 'preregistrations')},
            'summary': summary,
            'curve': curve,
            'fees': {'totals': fees['totals'], 'strategies': fees['strategies'], 'model_id': fees['model_id'],
                     'note': fees['note']},
            'daily': {'observed_days': daily.get('observed_days'), 'ledger': daily.get('ledger'), 'days': days}}


def fills(archive_dir: Path) -> list[dict]:
    """Las operaciones del archivo, en orden, con las columnas de FILL_COLUMNS."""
    return _read_csv(Path(archive_dir) / 'operaciones.csv')


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['build', 'verify'])
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--inventory', type=Path, help='inventario-contenedor.json del respaldo final')
    args = parser.parse_args(argv)
    if args.action == 'build':
        inventory = json.loads(args.inventory.read_text(encoding='utf-8')) if args.inventory else {}
        backup = inventory.get('backup', {})
        source = {'backup_sha256': backup.get('sqlite_sha256'), 'backup_bytes': backup.get('sqlite_bytes'),
                  'backup_directory': backup.get('directory'), 'restored_and_audited': True}
        manifest = build(args.db, args.out, source)
        print(json.dumps({'files': len(manifest['files']), 'counts': manifest['generated_from_counts']}, ensure_ascii=False))
    else:
        result = verify(args.db, args.archive or args.out)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        raise SystemExit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
