"""Versioned, prospective paper fees; comparisons never invent maker executions."""
from contextlib import closing
from decimal import Decimal
from functools import lru_cache
import heapq
import csv
import io
import json
import math
import os
from pathlib import Path
import sqlite3

from . import arena

PLAN_PATH = arena.ROOT / 'configs/arena/bitso_fees_v2.json'
PREREG_PATH = arena.ROOT / 'reports/arena_fees_v2_preregistro.md'
PREREG = 'd26ee0b693bafb607ff030cb709dd25b41887259'
WINDOW_MS = 30 * 86400000


@lru_cache(maxsize=1)
def plan():
    return json.loads(PLAN_PATH.read_text())


def proof():
    cfg = plan()
    ids = [v['id'] for v in cfg['variants']]
    if os.environ.get('ARENA_ATTESTATION'):
        from .research_attestation import verify_attestation
        path = Path(os.environ['ARENA_ATTESTATION']).with_name('arena-fees-attestation.json')
        return verify_attestation(arena.ROOT, path, PLAN_PATH, PREREG_PATH, PREREG, cfg, ids)
    return arena.verify_preregistration(arena.ROOT, PREREG_PATH, PREREG,
                                       cfg['experiment_id'], cfg, ids)


def verify_policy(manifest):
    policy = manifest.get('fee_policy')
    if policy and (policy['proof'] != proof() or policy['schedule_sha256'] != arena.canonical_hash(plan())):
        raise ValueError('Preregistro de comisiones distinto de la versión congelada')


def tier(volume):
    value = Decimal(str(volume))
    if not value.is_finite() or value < 0:
        raise ValueError('Volumen de comisiones inválido')
    tiers = plan()['tiers']
    result = tiers[0]
    for candidate in tiers[1:]:
        if value > Decimal(str(candidate['above_usd'])):
            result = candidate
    return result


def records(db):
    """Recognition time preserves causality for delayed public maker prints."""
    return [(fid, json.loads(raw), observed) for fid, raw, observed in db.execute('''
        SELECT f.id,f.payload,c.observed_ms FROM fills f
        LEFT JOIN captures c ON c.id=json_extract(f.payload,'$.capture') ORDER BY f.id''')]


def recognized(fill, captured=None):
    return fill.get('fee_context', {}).get('as_of_ms', captured if captured is not None else fill['ts'])


def volume_before(rows, strategy, at_ms):
    return sum((Decimal(str(f['value'])) for _, f, captured in rows
                if f['strategy'] == strategy and at_ms-WINDOW_MS < recognized(f, captured) <= at_ms), Decimal(0))


def context_from_rows(rows, strategy, at_ms, liquidity):
    if liquidity not in ('maker', 'taker'):
        raise ValueError('Tipo de ejecución desconocido')
    return make_context(volume_before(rows, strategy, at_ms), at_ms, liquidity, rows[-1][0] if rows else 0)


def make_context(volume, at_ms, liquidity, prior_id):
    cfg = plan()
    selected = tier(volume)
    return {'model_id': cfg['model_id'], 'schedule_sha256': arena.canonical_hash(cfg),
            'scope': cfg['scope'], 'as_of_ms': at_ms, 'prior_fill_id': prior_id,
            'volume_30d_usd': float(volume), 'above_usd': selected['above_usd'],
            'rate': selected[liquidity], 'liquidity': liquidity}


def execution_context(db, strategy, at_ms, liquidity):
    manifest = json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
    policy = manifest.get('fee_policy')
    if not policy:
        return None
    if (policy['schedule_sha256'] != arena.canonical_hash(plan())
            or policy['model_id'] != plan()['model_id'] or at_ms < policy['activated_ms']):
        raise ValueError('Política de comisiones incompatible con la ejecución')
    return context_from_rows(records(db), strategy, at_ms, liquidity)


def verify_ledger(rows, policy):
    """Validate each new rate against only earlier recognized fills and its cutoff."""
    if policy and (policy['schedule_sha256'] != arena.canonical_hash(plan()) or policy['model_id'] != plan()['model_id']):
        raise ValueError('Política de comisiones alterada')
    queues = {wid: [] for wid in arena.NAMES}
    totals = {wid: Decimal(0) for wid in arena.NAMES}
    prior_id = 0
    last_new_ms = policy['activated_ms'] if policy else 0
    for fid, fill, captured in rows:
        wid = fill['strategy']; when = recognized(fill, captured)
        if policy and fid > policy['after_fill_id']:
            actual = fill.get('fee_context')
            if not actual or (captured is not None and actual['as_of_ms'] != captured):
                raise ValueError('Fill sin contexto verificable de comisiones')
            if actual['as_of_ms'] < last_new_ms:
                raise ValueError('Comisión anterior a su activación o reconocimiento previo')
            last_new_ms = actual['as_of_ms']
            while queues[wid] and queues[wid][0][0] <= last_new_ms-WINDOW_MS:
                _, _, expired = heapq.heappop(queues[wid]); totals[wid] -= expired
            expected = make_context(totals[wid], last_new_ms, fill['liquidity'], prior_id)
            if actual != expected or not math.isclose(fill['fee'], fill['value']*expected['rate'], abs_tol=1e-9, rel_tol=1e-12):
                raise ValueError('Comisión no coincide con volumen y escalón previos')
        elif fill.get('fee_context'):
            raise ValueError('Comisión versionada fuera del corte declarado')
        elif policy and when > policy['activated_ms']:
            raise ValueError('Fill histórico posterior al corte de comisiones')
        amount = Decimal(str(fill['value']))
        heapq.heappush(queues[wid], (when, fid, amount)); totals[wid] += amount
        prior_id = fid


def report(directory, *, at_ms=None):
    at_ms = arena.now_ms() if at_ms is None else at_ms
    path = Path(directory) / arena.DB_NAME
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        manifest = json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        rows = records(db)
        last = db.execute('SELECT MAX(observed_ms) FROM captures').fetchone()[0]
    cfg = plan(); policy = manifest.get('fee_policy')
    verify_ledger(rows, policy)
    result = []
    for wid, name in arena.NAMES.items():
        current_volume = volume_before(rows, wid, at_ms)
        current_tier = tier(current_volume)
        tiers = cfg['tiers']; index = tiers.index(current_tier)
        next_tier = tiers[index+1] if index+1 < len(tiers) else None
        item = {'id': wid, 'name': name, 'volume_30d_usd': float(current_volume),
                'tier': current_tier, 'next_above_usd': next_tier['above_usd'] if next_tier else None,
                'volume_to_threshold_usd': float(max(Decimal(0), Decimal(str(next_tier['above_usd']))-current_volume)) if next_tier else None,
                'recorded_fees_usd': 0., 'historical_fees_usd': 0., 'new_fees_usd': 0.,
                'fixed_fees_usd': 0., 'all_maker_fees_usd': 0., 'all_taker_fees_usd': 0.,
                'new_fills': 0, 'maker_fills': 0, 'taker_fills': 0}
        for fid, f, captured in rows:
            if f['strategy'] != wid or recognized(f, captured) > at_ms:
                continue
            item['recorded_fees_usd'] += f['fee']
            item[f['liquidity']+'_fills'] += 1
            if policy and fid > policy['after_fill_id']:
                rate_tier = tier(f['fee_context']['volume_30d_usd'])
                item['new_fills'] += 1
                item['new_fees_usd'] += f['fee']
                item['fixed_fees_usd'] += f['value']*manifest['plan'][f['liquidity']+'_fee']
                item['all_maker_fees_usd'] += f['value']*rate_tier['maker']
                item['all_taker_fees_usd'] += f['value']*rate_tier['taker']
            else:
                item['historical_fees_usd'] += f['fee']
        item['fee_difference_usd'] = item['fixed_fees_usd']-item['new_fees_usd']
        result.append(item)
    keys = ('recorded_fees_usd','historical_fees_usd','new_fees_usd','fixed_fees_usd',
            'all_maker_fees_usd','all_taker_fees_usd','fee_difference_usd','new_fills','maker_fills','taker_fills')
    return {'mode': 'paper', 'model_id': cfg['model_id'], 'scope': cfg['scope'],
            'source_url': cfg['source_url'], 'verified_on': cfg['verified_on'],
            'generated_at_ms': at_ms, 'last_observed_ms': last, 'stale': last is None or at_ms-last > 90000,
            'active': bool(policy), 'cutover': policy, 'strategies': result,
            'totals': {k: sum(r[k] for r in result) for k in keys}, 'tiers': cfg['tiers'],
            'account_fees_verified': False, 'fee_ledger_verified': True,
            'comparison': 'same_recorded_fills_cost_only',
            'note': 'Comparación de comisiones sobre las mismas cantidades y precios desde el corte. No simula fills maker alternativos ni mide rentabilidad.'}


def report_csv(value):
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow(['estrategia','modelo','corte_ms','volumen_30d_usd','maker_pct','taker_pct',
                     'comisiones_historicas_usd','comisiones_desde_corte_usd','costo_fijo_mismos_fills_usd',
                     'diferencia_costos_usd','costo_todo_maker_hipotetico_usd','costo_todo_taker_hipotetico_usd','nota'])
    for r in value['strategies']:
        writer.writerow([r['name'],value['model_id'],(value['cutover'] or {}).get('activated_ms',''),
                         r['volume_30d_usd'],r['tier']['maker']*100,r['tier']['taker']*100,
                         r['historical_fees_usd'],r['new_fees_usd'],r['fixed_fees_usd'],r['fee_difference_usd'],
                         r['all_maker_fees_usd'],r['all_taker_fees_usd'],value['note']])
    return '\ufeff'+out.getvalue()
