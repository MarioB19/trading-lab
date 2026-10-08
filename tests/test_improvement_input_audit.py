"""Parity and corruption checks for the read-only collector; no new strategy."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import zlib

import pytest

from lab import arena, improvement_sources as sources
from test_arena import frame, TS


def test_compact_hash_matches_full_frame_canonical_hash():
    original = frame()
    original['unicode'] = {'ñ': ['BTC', 1e-12, -0.0, None, True]}
    compact = deepcopy(original)
    serialized = {}
    for interval, rows in original['candles'].items():
        checksum = arena.canonical_hash(rows)
        serialized[checksum] = json.dumps(rows, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=False, allow_nan=False)
        compact['candles'][interval] = checksum
    assert sources.compact_capture_hash(compact, serialized) == arena.canonical_hash(original)
    compact['order_book']['bids'][0][0] += 1
    assert sources.compact_capture_hash(compact, serialized) != arena.canonical_hash(original)


def test_unknown_input_or_nonfinite_capture_cannot_pass():
    with pytest.raises(KeyError):
        sources.compact_capture_hash({'candles': {'1h': 'missing'}}, {})
    with pytest.raises(ValueError):
        sources.compact_capture_hash({'candles': {}, 'price': float('nan')}, {})


@pytest.fixture
def recorded(tmp_path):
    arena.initialize(tmp_path, 'synthetic')
    for step in range(4):
        arena.tick(tmp_path, frame(TS + step * 15000))
    return tmp_path


def dump(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        return list(db.iterdump())


def test_readonly_audit_matches_existing_audit_counts_and_preserves_every_table(recorded):
    path = recorded / arena.DB_NAME
    before = dump(path)
    original = arena.audit(recorded)
    result = sources.arena_input_audit(path)
    assert result['status'] == original['status'] == 'verified'
    assert result['captures'] == original['captures'] == 4
    assert result['candle_inputs'] == original['candle_inputs']
    assert result['scope'] == 'sqlite_integrity_inputs_and_captures'
    assert result['wallets_verified'] is False  # existing daily_report handles the ledger
    assert dump(path) == before


@pytest.mark.parametrize('target', ['capture', 'input', 'missing_input'])
def test_corrupted_or_missing_archived_data_blocks(recorded, target):
    path = recorded / arena.DB_NAME
    # Only an artificial test database is mutated to exercise the guard.
    with closing(sqlite3.connect(path)) as db, db:
        if target == 'capture':
            key, raw = db.execute('SELECT id,payload FROM captures LIMIT 1').fetchone()
            value = json.loads(raw)
            value['order_book']['asks'][0][0] += 1
            db.execute('UPDATE captures SET payload=? WHERE id=?', (json.dumps(value), key))
        elif target == 'input':
            key, raw = db.execute('SELECT sha,payload FROM inputs LIMIT 1').fetchone()
            value = json.loads(zlib.decompress(raw))
            value[0][1] += 1
            db.execute('UPDATE inputs SET payload=? WHERE sha=?', (zlib.compress(json.dumps(value).encode()), key))
        else:
            db.execute('DELETE FROM inputs WHERE sha=(SELECT sha FROM inputs LIMIT 1)')
    with pytest.raises((ValueError, KeyError)):
        sources.arena_input_audit(path)


def test_embedded_remote_reader_keeps_wallet_guard_and_sqlite_unchanged(recorded, monkeypatch, capsys):
    from lab import arena_reporting
    monkeypatch.setattr(arena, 'now_ms', lambda: TS + 46000)
    monkeypatch.setattr(arena_reporting, 'now_ms', lambda: TS + 46000)
    path = recorded / arena.DB_NAME
    # A good market archive must never conceal an inconsistent wallet.
    with closing(sqlite3.connect(path)) as db, db:
        key, raw = db.execute('SELECT id,payload FROM wallets LIMIT 1').fetchone()
        wallet = json.loads(raw)
        wallet['cash'] += 1
        db.execute('UPDATE wallets SET payload=? WHERE id=?', (json.dumps(wallet), key))
    before = dump(path)
    namespace = {'json': json, 'datetime': datetime, 'timezone': timezone,
                 'Path': lambda value: recorded if value == '/data/arena' else Path(value),
                 'release': {'build_id': 'synthetic'}, 'files_match': True}
    exec(sources.ARENA[len(sources.COMMON):], namespace)
    result = json.loads(capsys.readouterr().out.split('IMPROVEMENT_SOURCE=')[1])
    assert result['audit']['status'] == 'verified'
    assert result['healthy'] is True
    assert result['reconciled'] is False
    assert result['daily_report']['ledger']['issues']
    assert result['reader_timing']['input_audit_seconds'] >= 0
    assert dump(path) == before
