"""Offline accounting, read-only API and broker telemetry checks."""
from datetime import datetime, timezone
from http.client import HTTPConnection
import json
import threading

import pytest

from lab.execution_quality import book_quality, build_execution_quality
from lab.service import Reader, make_server
from lab.storage import SQLiteStore
from test_analyze import FakeBitso, FakeBitsoLive, _maker_broker

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def trade(**override):
    return {'mode': 'paper', 'sleeve': 'crypto', 'asset': 'SOL', 'side': 'buy',
            'run_at_utc': '2026-09-29 00:00', 'status': 'filled', 'value': 100., 'fee': .36,
            'broker': 'simulado · libro real de Bitso', 'cost_bps': 40., **override}


def test_book_preview_counts_only_visible_depth_and_never_fakes_missing_cost():
    quality = book_quality({'bids': [[99., 10]], 'asks': [[100., .5], [101., 1.]]}, 'buy', 2., .0036)
    assert quality['depth_fill_ratio'] == .75
    assert quality['visible_depth_usd'] == 0
    assert quality['estimated_taker_cost_bps'] > 36
    assert book_quality({'bids': [], 'asks': []}, 'buy', 1, .0036) == {}
    assert book_quality({'bids': [[101, 1]], 'asks': [[100, 1]]}, 'buy', 1, .0036) == {}


def test_weighted_cost_separates_assumptions_and_unknown_maker():
    rows = [trade(), trade(value=300, cost_bps=20),
            trade(value=1000, cost_bps=80, execution_source='assumed_simulation'),
            trade(value=10, cost_bps=None, broker='simulado')]
    result = build_execution_quality(rows, now=NOW)['by_sleeve']['crypto']
    assert result['book_cost_bps'] == 25
    assert result['book_cost_trades'] == 2
    assert result['assumed_cost_trades'] == 1
    assert result['unmeasured_trades'] == 1
    assert result['maker_share'] is None
    assert result['maker_known_trades'] == 0


def test_maker_ratio_is_notional_weighted_and_fees_are_not_costs_twice():
    rows = [trade(maker_value_usd=25, taker_value_usd=75, execution_wait_s=120),
            trade(value=300, maker_value_usd=300, taker_value_usd=0, fee=.9, execution_wait_s=30)]
    result = build_execution_quality(rows, now=NOW)['total']
    assert result['maker_share'] == .8125
    assert result['fees_usd'] == 1.26
    assert result['book_cost_bps'] == 40
    assert result['mean_execution_wait_s'] == 75


def test_reentry_pairs_are_scoped_and_failed_or_future_trades_do_not_count():
    rows = [trade(side='sell'), trade(run_at_utc='2026-09-29 12:00'),
            trade(sleeve='stocks', side='buy'), trade(status='failed'),
            trade(run_at_utc='2026-10-01'), trade(run_at_utc='2026-01-01')]
    result = build_execution_quality(rows, now=NOW)
    assert result['total']['filled_trades'] == 3
    assert len(result['total']['reentries_48h']) == 1
    assert result['total']['reentries_48h'][0]['hours_since_sale'] == 12


def test_invalid_values_and_missing_measurements_are_not_zero_observations():
    rows = [trade(value=float('nan')), trade(cost_bps='', fee=None), trade(mode='live')]
    result = build_execution_quality(rows, now=NOW)['total']
    assert result['filled_trades'] == 1
    assert result['book_cost_bps'] is None
    assert result['fees_usd'] is None
    assert result['maker_share'] is None


def test_mixed_fill_telemetry_matches_ledger_and_does_not_change_execution():
    exchange = FakeBitsoLive(asks=[[101., 5]], bids=[[99., 5]], trades=[(98., .5)])
    ledger = {'cash': 1000., 'positions': {}}
    fill = _maker_broker(exchange, ledger).execute('ETH', 'buy', 2., 100.)
    assert fill.price == pytest.approx(100.5)
    assert fill.execution['maker_value_usd'] == 49.5
    assert fill.execution['taker_value_usd'] == 151.5
    assert fill.execution['execution_wait_s'] == 60
    assert fill.execution['execution_source'] == 'public_book_simulation'
    assert ledger['cash'] == pytest.approx(1000 - 49.5 * 1.003 - 151.5 * 1.0036)


def test_fallback_fill_is_explicitly_assumed():
    class Unavailable(FakeBitso):
        def fetch_order_book(self, *_args, **_kwargs):
            raise TimeoutError('synthetic unavailable')
    ledger = {'cash': 1000., 'positions': {}}
    fill = _maker_broker(Unavailable(asks=[[101, 5]], bids=[[99, 5]]), ledger).execute('ETH', 'buy', 1, 100)
    assert fill.execution['execution_source'] == 'assumed_simulation'
    assert fill.execution['maker_value_usd'] == 0


def test_quality_api_reads_all_rows_without_writing_database(tmp_path):
    store = SQLiteStore(tmp_path / 'trading.sqlite3')
    with store.transaction() as db:
        store._rows(db, 'trades', [trade(run_at_utc=datetime.now(timezone.utc).isoformat(), execution_id=f'fixture-{i}')
                                  for i in range(510)])
    reader = Reader(tmp_path)
    assert reader.execution_quality()['total']['filled_trades'] == 510
    server = make_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        connection.request('GET', '/api/execution-quality')
        response = connection.getresponse()
        assert response.status == 200
        result = json.loads(response.read())
        assert result['read_only'] is True
        assert result['total']['filled_trades'] == 510
        assert len(store.rows('trades')) == 510
        connection.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_absent_database_is_not_created_by_diagnostics(tmp_path):
    directory = tmp_path / 'absent'
    assert Reader(directory).execution_quality()['total']['filled_trades'] == 0
    assert not directory.exists()
