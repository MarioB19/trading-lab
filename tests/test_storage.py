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


@pytest.mark.parametrize('no_flow', [None, '', 0, 0.0, '0', '0.0'])
def test_retry_updates_equity_but_retains_committed_flow_once(tmp_path, no_flow):
    store = SQLiteStore(tmp_path / 'runtime.sqlite3')
    first = {'date': '2026-10-01', 'sleeve': 'stocks', 'mode': 'paper', 'equity': 500., 'flow': -200.}
    store.commit_run({}, [], [first], {})
    retry = {**first, 'equity': 499.75, 'flow': no_flow}
    original = dict(retry)
    store.commit_run({}, [], [retry], {})
    store.commit_run({}, [], [retry], {})
    assert store.rows('equity') == [{**first, 'equity': 499.75}]
    assert retry == original
    # A replay with the original nonzero flow is not summed twice either.
    store.commit_run({}, [], [{**first, 'equity': 499.75}], {})
    assert store.rows('equity')[0]['flow'] == -200.
    # A distinct day has its own flow: no leakage from the retry's prior day.
    store.commit_run({}, [], [{**first, 'date': '2026-10-02', 'equity': 599.75, 'flow': 100}], {})
    assert [row['flow'] for row in store.rows('equity')] == [-200., 100]


def test_retry_without_flow_key_preserves_flow_and_equity_key_is_namespaced(tmp_path):
    store = SQLiteStore(tmp_path / 'runtime.sqlite3')
    row = {'date': '2026-10-01', 'sleeve': 'stocks', 'mode': 'paper', 'equity': 500., 'flow': -200.}
    store.commit_run({}, [], [row], {})
    retry = {key: value for key, value in row.items() if key != 'flow'}
    store.commit_run({}, [], [retry, {**retry, 'sleeve': 'crypto'}, {**retry, 'mode': 'live'}], {})
    saved = {(item['sleeve'], item['mode']): item for item in store.rows('equity')}
    assert saved['stocks', 'paper']['flow'] == -200.
    assert 'flow' not in saved['crypto', 'paper']
    assert 'flow' not in saved['stocks', 'live']


def test_withdrawal_failed_sale_retry_preserves_flow_and_trading_pnl(tmp_path):
    from copy import deepcopy
    import pandas as pd

    from lab.bot import DEFAULT_CONFIG, run_sleeve
    from lab.brokers import Fill, SimBroker
    from lab.performance import build_performance

    store = SQLiteStore(tmp_path / 'runtime.sqlite3')
    sc = deepcopy(DEFAULT_CONFIG['sleeves']['stocks'])
    sc.update(capital=500., universe=['SPY', 'IEF'], slippage=.0005, fee=.001)
    prices = pd.DataFrame({'SPY': 100., 'IEF': 100.},
                          index=pd.date_range('2025-01-01', periods=300, freq='B'))
    state = {'sleeves': {'stocks': {'mode': 'paper', 'capital_base': 700.,
                                  'ledger': {'cash': 0., 'positions': {'SPY': 4.2, 'IEF': 2.8}}}}}
    previous = {'date': str(prices.index[-2].date()), 'sleeve': 'stocks', 'mode': 'paper',
                'equity': 700., 'flow': ''}
    store.commit_run(state, [], [previous], {})
    st = state['sleeves']['stocks']
    broker = SimBroker(st['ledger'], sc['fee'], sc['slippage'], 1.)
    execute = broker.execute
    broker.execute = lambda asset, side, qty, ref: Fill(asset, side, 0, ref, 0, status='failed')
    now = prices.index[-1] + pd.Timedelta(days=1, hours=2)

    def attempt():
        result = run_sleeve('stocks', sc, prices, broker, st, now, 'paper', pd.Series(dtype=float), .4)
        snapshot = {'mode': 'paper', 'sleeves': {'stocks': result['snapshot']}}
        store.commit_run(state, result['trades'], [result['equity_row']], snapshot)
        return result, snapshot

    failed, _ = attempt()
    assert failed['status'] == 'error' and failed['equity_row']['flow'] == -200.
    assert store.read_document('state')['sleeves']['stocks']['capital_base'] == 500.
    assert store.rows('equity')[-1]['flow'] == -200.
    broker.execute = execute
    succeeded, snapshot = attempt()
    assert succeeded['status'] == 'ok' and succeeded['equity_row']['flow'] == ''
    # Re-delivery of the final transaction cannot erase or double-count the flow.
    store.commit_run(state, succeeded['trades'], [succeeded['equity_row']], snapshot)
    rows = store.rows('equity')
    assert len(rows) == 2 and rows[-1]['flow'] == -200.
    assert len(store.rows('trades')) == len(failed['trades']) + len(succeeded['trades'])
    result = build_performance(state, snapshot, {}, rows, {'sleeves': {'stocks': sc}})
    daily = result['daily'][-1]
    assert result['capital']['by_sleeve']['stocks']['initial_usd'] == 700.
    assert daily['flow_usd'] == -200.
    assert daily['capital_usd'] == 500.
    assert daily['pnl_usd'] == pytest.approx(rows[-1]['equity'] - 500.)
    assert -1. < daily['pnl_usd'] < 0.  # Only actual execution costs, not a $200 loss.
