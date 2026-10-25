import csv
import hashlib
import json
import os
from pathlib import Path

import pytest

from lab import arena, arena_archive
from tests.test_arena import TS, frame

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'archive/arena-v1'


def synthetic(tmp_path):
    directory = tmp_path / 'arena'
    arena.initialize(directory, 'synthetic')
    for step, mid in enumerate((100., 101., 99., 102.)):
        arena.tick(directory, frame(ts=TS + step * 300_000, mid=mid))
    assert arena.status(directory)['counts']['fills'] > 0
    return directory


def test_synthetic_archive_verifies_and_detects_tampering(tmp_path):
    directory = synthetic(tmp_path)
    out = tmp_path / 'archivo'
    manifest = arena_archive.build(directory / arena.DB_NAME, out, {'backup_sha256': 'x' * 64})
    assert manifest['kind'] == 'arena-archive-v1' and 'captures' in manifest['excluded']
    result = arena_archive.verify(directory, out)
    assert result['ok'], result['errors']
    loaded = arena_archive.load(out)
    assert set(loaded) == {'manifest', 'summary', 'curve', 'fees', 'daily'}
    assert len(arena_archive.fills(out)) == result['fills']
    again = arena_archive.build(directory, tmp_path / 'otra', {'backup_sha256': 'x' * 64})
    assert again['files'] == manifest['files']  # determinista

    text = (out / 'operaciones.csv').read_text()
    rows = list(csv.DictReader(text.splitlines()))
    rows[0]['fee'] = repr(float(rows[0]['fee']) * 2)
    with (out / 'operaciones.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    broken = arena_archive.verify(directory, out)
    assert not broken['ok'] and not broken['checks']['huellas'] and not broken['checks']['fills']

    summary = json.loads((tmp_path / 'otra' / 'resumen.json').read_text())
    summary['strategies'][0]['fees_usd'] += 0.01
    (tmp_path / 'otra' / 'resumen.json').write_text(json.dumps(summary))
    assert not arena_archive.verify(directory, tmp_path / 'otra')['checks']['comisiones_por_estrategia']


def test_build_refuses_non_empty_destination(tmp_path):
    directory = synthetic(tmp_path)
    (tmp_path / 'lleno').mkdir()
    (tmp_path / 'lleno' / 'x').write_text('x')
    with pytest.raises(ValueError):
        arena_archive.build(directory, tmp_path / 'lleno', {})


@pytest.mark.skipif(not (ARCHIVE / 'manifest.json').is_file(), reason='archive/arena-v1 no está en este checkout')
def test_versioned_archive_matches_dec031():
    manifest = json.loads((ARCHIVE / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == digest, name
    assert manifest['source']['backup_sha256'].startswith('c2518e14')
    assert manifest['generated_from_counts']['fills'] == 267
    summary = json.loads((ARCHIVE / 'resumen.json').read_text())
    operations = arena_archive.fills(ARCHIVE)
    assert len(operations) == summary['total']['fills'] == 267
    fees = {}
    for row in operations:
        fees[row['strategy']] = fees.get(row['strategy'], 0.) + row['fee']
    for item in summary['strategies']:
        assert fees[item['id']] == pytest.approx(item['fees_usd'], abs=1e-9)
    assert round(summary['total']['equity_usd'], 2) == 3714.10
    assert round(summary['total']['fees_usd'], 2) == 164.70
    assert {s['id']: round(s['pnl_usd'], 2) for s in summary['strategies']} == {
        'scalping-v1': -151.96, 'swing-v1': -92.60, 'mean-reversion-v1': -21.31, 'market-making-v1': -20.02}
    assert round(next(s for s in summary['strategies'] if s['id'] == 'scalping-v1')['fees_usd'], 2) == 127.41


@pytest.mark.skipif(not os.environ.get('ARENA_V1_DB'),
                    reason='Define ARENA_V1_DB con la base restaurada del respaldo final para compararla con el archivo')
def test_versioned_archive_matches_restored_backup():
    result = arena_archive.verify(Path(os.environ['ARENA_V1_DB']), ARCHIVE)
    assert result['ok'], result['errors']
