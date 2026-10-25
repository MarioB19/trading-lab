#!/usr/bin/env python3
"""Verificación del respaldo final de la arena en la USB (F1, comprobaciones b–f).

Necesita `lab` (Python 3.13 con numpy/pandas/yaml) y PYTHONPATH=src. Cada paso cabe en una
llamada corta y deja su resultado en `<dest>/verificacion/<paso>.json`. Nunca abre para escribir la
copia descargada: trabaja sobre una copia de trabajo y una restauración en carpeta vacía y desactivada.

    arena_verify.py integridad   --dest DIR   (b) integrity_check de la copia + cadena de huellas de los respaldos viejos
    arena_verify.py restaurar    --dest DIR   (c1) copia de trabajo y lab.arena restore a carpeta vacía, sin arena.enabled
    arena_verify.py auditar      --dest DIR   (c2) lab.arena audit sobre la restaurada (efectivo, inventario, comisiones)
    arena_verify.py totales      --dest DIR --corte SNAPSHOT.json   (d) conteos y (e) totales de DEC-031
    arena_verify.py releer       --dest DIR   (f) vuelve a leer de la USB y compara huellas
    arena_verify.py informe      --dest DIR   resumen de las seis comprobaciones
"""
from __future__ import annotations

import argparse
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time

from lab import arena
from lab.arena_fees import report as fee_report
from lab.arena_maintenance import digest, table_counts

STEPS = ('huellas', 'integridad', 'auditar', 'totales', 'releer')


def inventory(dest: Path) -> dict:
    return json.loads((dest / 'inventario-contenedor.json').read_text(encoding='utf-8'))


def final_db(dest: Path, inv: dict) -> Path:
    return dest / inv['backup']['directory'] / arena.DB_NAME


def save(dest: Path, name: str, value: dict) -> dict:
    folder = dest / 'verificacion'
    folder.mkdir(exist_ok=True)
    (folder / f'{name}.json').write_text(json.dumps(value, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in value.items() if k not in ('detalle',)}, ensure_ascii=False, indent=1))
    return value


def step_integrity(dest: Path) -> dict:
    inv, started = inventory(dest), time.monotonic()
    db = final_db(dest, inv)
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as conn:
        check = conn.execute('PRAGMA integrity_check').fetchall()
    old = []
    for folder in sorted(p for p in (dest / 'arena-backups').iterdir() if p.is_dir()):
        meta = json.loads((folder / 'manifest.json').read_text())
        packed = folder / 'snapshot.sqlite3.gz'
        h, size = hashlib.sha256(), 0
        with gzip.open(packed, 'rb') as reader:
            while chunk := reader.read(4 * 1024 * 1024):
                h.update(chunk)
                size += len(chunk)
        row = {'respaldo': folder.name, 'creado_ms': meta['created_ms'],
               'comprimido_igual': digest(packed) == meta['compressed_sha256'],
               'sqlite_igual': h.hexdigest() == meta['sqlite_sha256'] and size == meta['sqlite_bytes']}
        row['ok'] = row['comprimido_igual'] and row['sqlite_igual']
        old.append(row)
    ok = check == [('ok',)] and all(r['ok'] for r in old)
    return save(dest, 'integridad', {'ok': ok, 'integrity_check': check[0][0] if len(check) == 1 else check[:5],
                                     'respaldos_anteriores': old, 'segundos': round(time.monotonic() - started, 1)})


def step_restore(dest: Path) -> dict:
    inv, started = inventory(dest), time.monotonic()
    source = final_db(dest, inv)
    work = dest / 'verificacion' / 'copia-de-trabajo'
    target = dest / 'verificacion' / 'restaurada'
    if target.exists():
        sys.exit('La carpeta de restauración ya existe; la restauración exige destino vacío.')
    work.mkdir(parents=True, exist_ok=True)
    copy = work / arena.DB_NAME
    if not copy.exists():
        shutil.copyfile(source, copy)
    if digest(copy) != inv['backup']['sqlite_sha256']:
        sys.exit('La copia de trabajo no coincide con la huella del contenedor.')
    arena.restore(copy, target)  # lab.arena restore: destino vacío; no arranca ningún proceso
    disabled = not (target / 'arena.enabled').exists()
    return save(dest, 'restaurar', {'ok': disabled, 'destino': str(target.relative_to(dest)),
                                    'desactivada': disabled, 'segundos': round(time.monotonic() - started, 1)})


def step_audit(dest: Path) -> dict:
    started = time.monotonic()
    target = dest / 'verificacion' / 'restaurada'
    if (target / 'arena.enabled').exists():
        sys.exit('La copia restaurada no está desactivada.')
    try:
        result = arena.audit(target)
        ok = result['status'] == 'verified'
    except ValueError as exc:
        result, ok = {'status': 'failed', 'error': str(exc)}, False
    return save(dest, 'auditar', {'ok': ok, **result, 'segundos': round(time.monotonic() - started, 1)})


def _cents(value: float) -> float:
    return round(value + 0.0, 2)


def step_totals(dest: Path, cut_path: Path) -> dict:
    inv = inventory(dest)
    target = dest / 'verificacion' / 'restaurada'
    counts = table_counts(target / arena.DB_NAME)
    counts_ok = counts == inv['counts']['live'] == inv['counts']['backup']
    cut = json.loads(cut_path.read_text(encoding='utf-8'))['arena']
    cut_arena, cut_fees = cut['arena']['data'], cut['fees']['data']
    cut_ms = cut_arena['last_observed_ms']
    with closing(sqlite3.connect((target / arena.DB_NAME).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        upto = db.execute('SELECT COUNT(*) FROM captures WHERE observed_ms<=?', (cut_ms,)).fetchone()[0]
        after = [arena.iso(r[0]) for r in db.execute('SELECT observed_ms FROM captures WHERE observed_ms>? ORDER BY observed_ms', (cut_ms,))]
        fills_after = db.execute('SELECT COUNT(*) FROM fills WHERE ts>?', (cut_ms,)).fetchone()[0]
        at_cut = {s: json.loads(p) for s, p in db.execute('SELECT strategy,payload FROM equity WHERE ts=?', (cut_ms,))}
    status = arena.status(target)
    fees_now = fee_report(target)
    rows = []
    for wallet in status['wallets']:
        wid = wallet['id']
        cut_wallet = next(w for w in cut_arena['wallets'] if w['id'] == wid)
        rows.append({'estrategia': wid,
                     'resultado_corte': _cents(cut_wallet['equity'] - 1000),
                     'resultado_base_en_el_corte': _cents(at_cut[wid]['equity'] - 1000) if wid in at_cut else None,
                     'resultado_base_final': _cents(wallet['equity'] - 1000),
                     'comisiones_corte': _cents(cut_wallet['fees']), 'comisiones_base': _cents(wallet['fees'])})
    total_cut = _cents(cut_arena['total_equity'])
    total_at_cut = _cents(sum(p['equity'] for p in at_cut.values())) if len(at_cut) == 4 else None
    fees_cut, fees_db = _cents(sum(w['fees'] for w in cut_arena['wallets'])), _cents(sum(w['fees'] for w in status['wallets']))
    totals_ok = (total_at_cut == total_cut == 3714.10 and fees_cut == fees_db == 164.70 and fills_after == 0
                 and all(r['resultado_base_en_el_corte'] == r['resultado_corte'] and r['comisiones_base'] == r['comisiones_corte']
                         for r in rows))
    return save(dest, 'totales', {
        'ok': counts_ok and totals_ok, 'conteos_ok': counts_ok, 'totales_ok': totals_ok,
        'conteos_restaurada': counts, 'conteos_contenedor': inv['counts'],
        'corte': {'archivo': cut_path.name, 'ultima_captura': arena.iso(cut_ms), 'capturas': cut_arena['counts']['captures'],
                  'fills': cut_arena['counts']['fills']},
        'capturas_hasta_el_corte': upto, 'capturas_despues_del_corte': after, 'fills_despues_del_corte': fills_after,
        'patrimonio': {'corte': total_cut, 'base_en_el_corte': total_at_cut, 'base_final': _cents(status['total_equity'])},
        'comisiones': {'corte': fees_cut, 'base': fees_db, 'reporte_de_comisiones_base': fees_now.get('totals'),
                       'reporte_de_comisiones_corte': cut_fees.get('totals')},
        'por_estrategia': rows})


def step_reread(dest: Path) -> dict:
    inv, started = inventory(dest), time.monotonic()
    rows = []
    for item in inv['inventory_after']['files']:
        if not item['path'].startswith(('arena-final/', 'arena-backups/', 'arena-imports/')):
            continue
        sha = digest(dest / item['path'])
        rows.append({'path': item['path'], 'igual': sha == item['sha256']})
    return save(dest, 'releer', {'ok': all(r['igual'] for r in rows), 'archivos': rows,
                                 'segundos': round(time.monotonic() - started, 1)})


def step_report(dest: Path) -> dict:
    folder = dest / 'verificacion'
    names = {'huellas': dest / 'verif-a-huellas.json'}
    results = {}
    for step in STEPS:
        path = names.get(step, folder / f'{step}.json')
        results[step] = json.loads(path.read_text()) if path.exists() else {'ok': None}
    return save(dest, 'informe', {'ok': all(r.get('ok') is True for r in results.values()),
                                  'pasos': {k: v.get('ok') for k, v in results.items()}})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('step', choices=['integridad', 'restaurar', 'auditar', 'totales', 'releer', 'informe'])
    p.add_argument('--dest', type=Path, required=True)
    p.add_argument('--corte', type=Path)
    a = p.parse_args()
    result = {'integridad': step_integrity, 'restaurar': step_restore, 'auditar': step_audit,
              'releer': step_reread, 'informe': step_report}.get(a.step)
    out = step_totals(a.dest, a.corte) if a.step == 'totales' else result(a.dest)
    sys.exit(0 if out.get('ok') else 1)


if __name__ == '__main__':
    main()
