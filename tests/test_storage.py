import json
import sqlite3

import pytest

from lab.storage import SQLiteStore, execution_lock


def test_run_commit_rolls_back_all_documents_and_rows(tmp_path, monkeypatch):
    s = SQLiteStore(tmp_path / 'runtime.sqlite3')
    s.commit_run({'sleeves': {'old': {}}}, [], [], {'old': True})
    real = s._rows
    def fail(db, table, rows):
        if table == 'equity':
            raise RuntimeError('simulated disk failure')
        return real(db, table, rows)
    monkeypatch.setattr(s, '_rows', fail)
    with pytest.raises(RuntimeError):
        s.commit_run({'sleeves': {'new': {}}}, [{'execution_id': 'one'}], [{}], {'new': True})
    assert s.read_document('state') == {'sleeves': {'old': {}}}
    assert s.read_document('snapshot') == {'old': True}
    assert s.rows('trades') == []


def test_backup_contains_latest_wal_commits_and_idempotent_trades(tmp_path):
    s = SQLiteStore(tmp_path / 'runtime.sqlite3')
    row = {'execution_id': 'remote-1:fill-1', 'qty': .5}
    s.commit_run({'sleeves': {}}, [row], [], {'version': 1})
    s.commit_run({'sleeves': {}}, [row], [], {'version': 2})
    backup = s.backup(tmp_path / 'backup.sqlite3')
    b = SQLiteStore(backup)
    assert b.read_document('snapshot')['version'] == 2
    assert b.rows('trades') == [row]
    assert s.health()['journal_mode'] == 'wal'
    assert b.health()['integrity'] == 'ok'


def test_import_is_explicit_atomic_paper_only_and_once(tmp_path):
    source = tmp_path / 'legacy'; source.mkdir()
    (source / 'state.json').write_text(json.dumps({'sleeves': {'crypto': {'mode': 'paper', 'ledger': {'cash': 500, 'positions': {}}}}}))
    (source / 'equity.csv').write_text('date,sleeve,mode,equity,flow\n2026-09-27,crypto,paper,500,NaN\n')
    s = SQLiteStore(tmp_path / 'runtime.sqlite3')
    result = s.import_legacy(source)
    assert result['counts']['equity'] == 1
    assert s.rows('equity')[0]['equity'] == 500.0
    assert s.rows('equity')[0]['flow'] is None
    with pytest.raises(ValueError, match='vacía'):
        s.import_legacy(source)


def test_import_does_not_adopt_external_legacy_positions(tmp_path):
    source = tmp_path / 'legacy'; source.mkdir()
    (source / 'state.json').write_text(json.dumps({'sleeves': {'stocks': {'mode': 'paper', 'sleeve_cash': 100}}}))
    s = SQLiteStore(tmp_path / 'runtime.sqlite3')
    with pytest.raises(ValueError, match='propiedad'):
        s.import_legacy(source)
    assert s.read_document('state') is None


def test_cli_lock_excludes_another_process_lock(tmp_path):
    path = tmp_path / 'runtime.sqlite3'
    with execution_lock(path):
        with pytest.raises(RuntimeError, match='bloqueo'):
            with execution_lock(path):
                pass
    with execution_lock(path):
        pass


def test_newer_schema_is_refused_without_downgrade(tmp_path):
    path = tmp_path / 'future.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError, match='más nuevo'):
        SQLiteStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0
