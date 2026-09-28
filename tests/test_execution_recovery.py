import copy

import pandas as pd
import pytest

from lab import bot
from lab.brokers import AlpacaBroker, BitsoBroker, Fill, SimBroker
from lab.journal import JournalBroker
from lab.realtime import REALTIME_DEFAULTS, check_sleeve
from lab.storage import SQLiteStore


class Remote:
    name = 'fake alpaca paper'
    account_key = 'offline-account'
    min_order_value = 1
    def __init__(self, positions=None):
        self.p = dict(positions or {})
        self.balance = 100000
        self.calls = []
        self.next_fill = None
        self.raise_after_accept = False
    def positions(self): return dict(self.p)
    def cash(self): return self.balance
    def pending(self): return 0
    def execute(self, asset, side, qty, ref_price, client_order_id=''):
        self.calls.append(client_order_id)
        if self.raise_after_accept:
            raise TimeoutError('POST accepted, response lost')
        return Fill(asset, side, 0, ref_price, 0, 'submitted', order_id='remote-id', terminal=False)
    def lookup_order(self, order):
        return self.next_fill or Fill(order['asset'], order['side'], 0, order['ref'], 0, 'submitted',
                                      order_id='remote-id', terminal=False)


def cfg():
    c = copy.deepcopy(bot.DEFAULT_CONFIG['sleeves']['stocks'])
    c.update(capital=500, max_order_value=500)
    return c


def journal(tmp_path, remote, st=None, store=None):
    st = st if st is not None else {}
    store = store or SQLiteStore(tmp_path / 'runtime.sqlite3')
    b = JournalBroker(remote, store, 'stocks', 'paper', cfg(), st)
    b.candle = '2026-09-25'
    return b, st, store


def prices():
    return pd.DataFrame({'SPY': 100., 'IEF': 100.}, index=pd.date_range('2026-09-20', periods=6))


def run(b, st):
    p = prices()
    return bot.run_sleeve('stocks', cfg(), p, b, st, pd.Timestamp('2026-09-26 02:00'),
                          'paper', pd.Series(dtype=float), .4)


def test_existing_account_holdings_are_not_owned_or_sold(tmp_path):
    remote = Remote({'SPY': 100})
    b, st, store = journal(tmp_path, remote)
    assert b.positions() == {}
    result = run(b, st)
    assert result['snapshot']['equity'] == 500
    assert all(o['side'] == 'buy' for o in store.orders())
    assert remote.p == {'SPY': 100}
    assert result['status'] == 'pending'


def test_pending_cash_is_not_debited_or_falsely_killed(tmp_path):
    remote = Remote()
    b, st, store = journal(tmp_path, remote)
    result = run(b, st)
    remote.balance = 500 - sum(o['qty'] * o['ref'] for o in store.orders())  # only remaining free cash
    view = check_sleeve('stocks', cfg(), st, REALTIME_DEFAULTS, 'paper', pd.Timestamp('2026-09-26 02:00'),
                        pd.Series(dtype=float), broker=b, daily=prices(), live=prices().iloc[-1])
    assert result['snapshot']['equity'] == view['equity'] == 500
    assert view['drawdown'] == 0
    assert st['sleeve_cash'] == 500
    assert not st.get('kill_switch')


def test_partial_fills_reconcile_once_across_restart(tmp_path):
    remote = Remote()
    b, st, store = journal(tmp_path, remote)
    b.execute('SPY', 'buy', 1, 100)
    remote.p = {'SPY': .5}
    remote.next_fill = Fill('SPY', 'buy', .5, 110, .1, 'partial', order_id='remote-id', terminal=False)
    b.reconcile(); b.reconcile()
    assert st['sleeve_cash'] == pytest.approx(444.9)
    assert len(store.rows('trades')) == 1
    b2, st2, _ = journal(tmp_path, remote, store=SQLiteStore(store.path))
    remote.p = {'SPY': 1}
    remote.next_fill = Fill('SPY', 'buy', 1, 110, .2, 'filled', order_id='remote-id')
    b2.reconcile(); b2.reconcile()
    assert st2['sleeve_cash'] == pytest.approx(389.8)
    assert b2.positions() == {'SPY': 1}
    assert sum(t['qty'] for t in store.rows('trades')) == 1
    assert len(store.rows('trades')) == 2
    assert len(remote.calls) == 1


def test_accepted_timeout_recovers_by_durable_identity_without_resend(tmp_path):
    remote = Remote(); remote.raise_after_accept = True
    b, st, store = journal(tmp_path, remote)
    result = b.execute('SPY', 'buy', 1, 100)
    assert result.status == 'unknown'
    order = store.orders()[0]
    assert order['id'] == remote.calls[0] and not order['terminal']
    b2, st2, _ = journal(tmp_path, remote, store=SQLiteStore(store.path))
    remote.p = {'SPY': 1}
    remote.next_fill = Fill('SPY', 'buy', 1, 101, 0, 'filled', order_id='recovered-by-client-id')
    assert b2.reconcile() == 0
    assert st2['sleeve_cash'] == 399
    assert len(remote.calls) == 1
    assert store.health()['unknown_orders'] == 0


def test_cancellation_releases_reservation_without_fake_loss(tmp_path):
    remote = Remote()
    b, st, store = journal(tmp_path, remote)
    b.execute('SPY', 'buy', 1, 100)
    remote.next_fill = Fill('SPY', 'buy', 0, 100, 0, 'failed', 'canceled', order_id='remote-id')
    assert b.reconcile() == 0
    assert st['sleeve_cash'] == 500
    assert b.positions() == {}
    assert store.rows('trades') == []


def test_bitso_unknown_without_remote_id_remains_blocked(tmp_path):
    class Exchange:
        apiKey = 'offline'
        def fetch_open_orders(self): return []
        def fetch_balance(self): return {'free': {'USD': 500}, 'total': {'USD': 500}}
        def fetch_ticker(self, s): return {'ask': 100, 'bid': 99}
        def amount_to_precision(self, s, q): return q
        def price_to_precision(self, s, q): return q
        def create_order(self, *a): raise TimeoutError('server accepted, no reply')
    raw = BitsoBroker.__new__(BitsoBroker)
    raw.ex, raw.quote, raw.offset, raw.timeout = Exchange(), 'USD', .004, 0
    raw.name, raw.account_key, raw.min_order_value = 'offline bitso', 'offline-bitso', 1
    b, st, store = journal(tmp_path, raw)
    fill = b.execute('BTC', 'buy', 1, 100)
    assert fill.status == 'unknown'
    assert b.reconcile() == 1
    with pytest.raises(RuntimeError, match='sin resolver'):
        b.execute('BTC', 'buy', 1, 100)
    assert len(store.orders()) == 1 and store.health()['unknown_orders'] == 1


def test_alpaca_uses_actual_filled_qty_and_rejection_state():
    raw = AlpacaBroker.__new__(AlpacaBroker)
    raw._req = lambda *a, **kw: {'id': 'r', 'status': 'partially_filled', 'filled_qty': '.5', 'filled_avg_price': '101'}
    fill = raw.execute('SPY', 'buy', 2, 100)
    assert fill.qty == .5 and fill.status == 'partial' and not fill.terminal
    raw._req = lambda *a, **kw: {'id': 'r', 'status': 'rejected', 'filled_qty': '0'}
    fill = raw.execute('SPY', 'buy', 2, 100)
    assert fill.qty == 0 and fill.status == 'failed' and fill.terminal


def test_failed_kill_liquidation_retries_same_candle():
    class FailingOnce(SimBroker):
        attempts = 0
        def execute(self, asset, side, qty, ref):
            self.attempts += 1
            if self.attempts == 1:
                return Fill(asset, side, 0, ref, 0, 'failed', 'temporary rejection')
            return super().execute(asset, side, qty, ref)
    ledger = {'cash': 0, 'positions': {'SPY': 5}}
    b = FailingOnce(ledger, 0, 0)
    st = {'ledger': ledger, 'peak': 1000}
    first = run(b, st)
    assert first['status'] == 'error' and st['execution_pending']
    assert st.get('last_candle') is None and ledger['positions']['SPY'] == 5
    assert bot.is_due(cfg(), st, pd.Timestamp('2026-09-26'))
    second = run(b, st)
    assert second['status'] == 'ok'
    assert ledger['positions'] == {} and not st['execution_pending']
    assert st['last_candle'] == '2026-09-25'


def test_remote_balance_shortage_does_not_sell_unowned_assets(tmp_path):
    remote = Remote()
    b, st, store = journal(tmp_path, remote)
    b.execute('SPY', 'buy', 1, 100)
    remote.p = {'SPY': 1}; remote.next_fill = Fill('SPY', 'buy', 1, 100, 0, 'filled', order_id='r')
    b.reconcile()
    remote.p = {}
    with pytest.raises(RuntimeError, match='propiedad registrada'):
        b.positions()


def test_crossed_maker_price_is_limited_by_depth_not_infinite_liquidity():
    from lab.brokers import BookSimBroker
    now = [0]
    class Book:
        def milliseconds(self): return 0
        def fetch_trades(self, *a, **k): return []
        def fetch_order_book(self, *a, **k): return {'asks': [[99, .2]], 'bids': [[98, 1]]}
    b = BookSimBroker.__new__(BookSimBroker)
    b.maker, b._maker_left, b.ex = {'wait_s': 3, 'poll_s': 1}, 3, Book()
    b._clock = lambda: now[0]
    b._sleep = lambda seconds: now.__setitem__(0, now[0] + seconds)
    assert b._maker_fill('BTC/USD', 'buy', 10, 100) == .2


def test_simulated_gap_cannot_create_negative_cash():
    b = SimBroker({'cash': 100, 'positions': {}}, .01, 0)
    fill = b.execute('SPY', 'buy', 2, 100)
    assert fill.status == 'partial' and fill.qty == pytest.approx(100 / 101)
    assert b.cash() >= -1e-10


def test_sqlite_remains_authoritative_when_json_exports_are_stale(tmp_path, monkeypatch):
    import json
    import yaml
    runtime = tmp_path / 'runtime'; runtime.mkdir()
    config = copy.deepcopy(bot.DEFAULT_CONFIG)
    config['sleeves']['crypto']['enabled'] = False
    config['sleeves']['stocks'].update(capital=500, paper_broker='sim')
    config['paths'] = {n: str(runtime / f'{n}.{ext}') for n, ext in [('state','json'),('trades','csv'),('equity','csv'),('snapshot','json')]}
    config['paths']['database'] = str(runtime / 'trading.sqlite3')
    path = tmp_path / 'config.yaml'; path.write_text(yaml.safe_dump(config))
    store = SQLiteStore(config['paths']['database'])
    state = {'sleeves': {'stocks': {'mode': 'paper', 'ledger': {'cash': 500, 'positions': {}}}}}
    store.commit_run(state, [], [], {'sleeves': {}})
    state['sleeves']['stocks']['ledger']['cash'] = 9000
    (runtime / 'state.json').write_text(json.dumps(state))
    monkeypatch.setattr(bot, 'offline_prices', lambda *a: prices())
    assert bot.main(['--config', str(path), '--offline']) == 0
    assert store.rows('equity')[0]['equity'] < 501
    assert json.loads((runtime / 'state.json').read_text()) == store.read_document('state')


def test_one_failed_sleeve_returns_failure_but_commits_successful_sleeve(tmp_path, monkeypatch):
    import yaml
    config = copy.deepcopy(bot.DEFAULT_CONFIG)
    config['sleeves']['stocks'].update(capital=500, paper_broker='sim')
    config['paths'] = {n: str(tmp_path / f'{n}.{ext}') for n, ext in [('state','json'),('trades','csv'),('equity','csv'),('snapshot','json')]}
    config['paths']['database'] = str(tmp_path / 'trading.sqlite3')
    path = tmp_path / 'config.yaml'; path.write_text(yaml.safe_dump(config))
    real = bot.make_broker
    def factory(name, *args, **kwargs):
        if name == 'crypto':
            raise RuntimeError('offline failure')
        return real(name, *args, **kwargs)
    monkeypatch.setattr(bot, 'make_broker', factory)
    monkeypatch.setattr(bot, 'offline_prices', lambda *a: prices())
    assert bot.main(['--config', str(path), '--offline']) == 1
    snapshot = SQLiteStore(config['paths']['database']).read_document('snapshot')
    assert snapshot['sleeves']['crypto']['status'] == 'error'
    assert snapshot['sleeves']['stocks']['status'] == 'ok'


def test_alpaca_journal_buy_uses_notional_budget_and_client_id():
    raw = AlpacaBroker.__new__(AlpacaBroker)
    sent = {}
    def request(*args, **kwargs):
        sent.update(kwargs['json'])
        return {'id': 'r', 'status': 'accepted', 'filled_qty': '0'}
    raw._req = request
    raw.execute('SPY', 'buy', 3, 100, client_order_id='stable-attempt', max_notional=300)
    assert sent['notional'] == '300.00' and 'qty' not in sent
    assert sent['client_order_id'] == 'stable-attempt'


def test_kill_latch_survives_process_death_during_submission(tmp_path):
    remote = Remote()
    b, st, store = journal(tmp_path, remote)
    b.execute('SPY', 'buy', 5, 100)
    remote.p = {'SPY': 5}; remote.next_fill = Fill('SPY', 'buy', 5, 100, 0, 'filled', order_id='buy-id')
    b.reconcile()
    st['peak'] = 1000
    def die(*args, **kwargs):
        raise KeyboardInterrupt('process terminated after durable sell intent')
    remote.execute = die
    with pytest.raises(KeyboardInterrupt):
        run(b, st)
    saved = SQLiteStore(store.path).read_document('state')['sleeves']['stocks']
    assert saved['kill_switch'] is True and saved['execution_pending'] is True
    pending = store.orders(pending_only=True)
    assert len(pending) == 1 and pending[0]['side'] == 'sell' and pending[0]['status'] == 'intent'


def test_journal_trade_precision_is_not_overwritten_by_csv_rounding(tmp_path):
    remote = Remote()
    b, st, store = journal(tmp_path, remote)
    b.execute('SPY', 'buy', 1, 100)
    remote.p = {'SPY': .123456789}
    remote.next_fill = Fill('SPY', 'buy', .123456789, 100.123456789, .123456789, 'filled', order_id='r')
    b.reconcile()
    exact = store.rows('trades')[0]
    rounded = {**exact, 'qty': round(exact['qty'], 8), 'fee': round(exact['fee'], 4)}
    store.commit_run({'sleeves': {}}, [rounded], [], {'sleeves': {}})
    assert store.rows('trades')[0] == exact


def test_alpaca_sell_precision_never_rounds_above_owned_quantity():
    raw = AlpacaBroker.__new__(AlpacaBroker)
    sent = {}
    def request(*args, **kwargs):
        sent.update(kwargs['json'])
        return {'id': 'r', 'status': 'accepted', 'filled_qty': '0'}
    raw._req = request
    raw.execute('SPY', 'sell', .123456789, 100, client_order_id='sell-own')
    assert float(sent['qty']) <= .123456789


def test_external_capital_change_fails_before_mutating_durable_accounting(tmp_path):
    remote = Remote()
    b, st, store = journal(tmp_path, remote)
    before = store.read_document(b.namespace)
    st['peak'] = 500
    changed = cfg(); changed['capital'] = 700
    with pytest.raises(RuntimeError, match='migración explícita'):
        bot.run_sleeve('stocks', changed, prices(), b, st, pd.Timestamp('2026-09-26 02:00'),
                       'paper', pd.Series(dtype=float), .4)
    assert store.read_document(b.namespace) == before
    assert st['sleeve_cash'] == st['capital_base'] == st['peak'] == 500
    assert store.orders() == [] and remote.calls == []
