import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load():
    sys.path.insert(0, str(ROOT / 'scripts/claude'))
    spec = importlib.util.spec_from_file_location('arena_backup_cli', ROOT / 'scripts/claude/arena_backup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_download_resumes_by_parts_and_verifies_whole_file(tmp_path, monkeypatch):
    cli = load()
    blobs = {'arena-final/20261025T000000Z/arena.sqlite3': bytes(range(256)) * 5000,
             'arena-backups/arena-1-aa/snapshot.sqlite3.gz': b'x' * 3000,
             'arena/arena.sqlite3': b'viva'}
    files = [{'path': k, 'size': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for k, v in blobs.items()]
    (tmp_path / 'inventario-contenedor.json').write_text(json.dumps({'phase': 'ready', 'inventory_after': {'files': files}}))
    calls = []

    def fake_part(env, rel, offset, length, compress):
        calls.append((rel, offset))
        if len(calls) == 3:
            raise OSError('corte de red')  # el reintento acotado lo absorbe
        return blobs[rel][offset:offset + length]

    monkeypatch.setattr(cli, '_part', fake_part)
    budget_calls = iter([0, 0, 0, 999] + [999] * 100)
    monkeypatch.setattr(cli.time, 'monotonic', lambda: next(budget_calls))
    cli.cmd_download({}, tmp_path, budget=10, part_mib=1)  # se agota el presupuesto a medio camino
    monkeypatch.setattr(cli.time, 'monotonic', lambda: 0)
    cli.cmd_download({}, tmp_path, budget=10, part_mib=1)
    assert not (tmp_path / 'arena/arena.sqlite3').exists()  # la base viva no se baja
    for rel in list(blobs)[:2]:
        assert (tmp_path / rel).read_bytes() == blobs[rel]
        ledger = json.loads((tmp_path / (rel + '.partes.json')).read_text())
        assert all(len(p['sha256']) == 64 for p in ledger['parts'].values())
    assert cli.cmd_verify(tmp_path) == 0


def test_corrupt_part_is_never_published(tmp_path, monkeypatch):
    cli = load()
    data = b'abc' * 1000
    item = {'path': 'arena-final/20261025T000000Z/arena.sqlite3', 'size': len(data),
            'sha256': hashlib.sha256(b'otra cosa').hexdigest()}
    (tmp_path / 'inventario-contenedor.json').write_text(json.dumps({'inventory_after': {'files': [item]}}))
    monkeypatch.setattr(cli, '_part', lambda env, rel, offset, length, compress: data[offset:offset + length])
    with pytest.raises(SystemExit):
        cli.cmd_download({}, tmp_path, budget=10, part_mib=1)
    assert not (tmp_path / item['path']).exists()
