"""A cash deficit is repaired by fills, never by changing capital or erasing loss."""
import copy

import pandas as pd
import pytest

from lab.bot import DEFAULT_CONFIG, run_sleeve
from lab.brokers import Fill, SimBroker


def setup_case(cash=-.10, *, capital=500., previous_capital=500.):
    sc = copy.deepcopy(DEFAULT_CONFIG['sleeves']['stocks'])
    sc.update(capital=capital, universe=['SPY', 'IEF'], slippage=.0005, fee=.001)
    prices = pd.DataFrame({'SPY': 100., 'IEF': 100.},
                          index=pd.date_range('2025-01-01', periods=300, freq='B'))
    state = {'capital_base': previous_capital,
             'ledger': {'cash': cash, 'positions': {'SPY': 3., 'IEF': 2.}}}
    broker = SimBroker(state['ledger'], sc['fee'], sc['slippage'], 1.)
    now = prices.index[-1] + pd.Timedelta(days=1, hours=2)
    return sc, prices, state, broker, now


def run(sc, prices, state, broker, now):
    return run_sleeve('stocks', sc, prices, broker, state, now, 'paper', pd.Series(dtype=float), .4)


def test_small_inherited_deficit_bypasses_band_only_to_sell_and_preserves_pnl():
    sc, prices, state, broker, now = setup_case()
    before = broker.cash() + sum(broker.positions().values()) * 100
    result = run(sc, prices, state, broker, now)
    assert broker.cash() >= 0
    assert result['status'] == 'ok'
    assert len(result['trades']) == 1 and result['trades'][0]['side'] == 'sell'
    sale = result['trades'][0]
    assert 1 <= sale['value'] < 1.1
    assert result['equity_row']['flow'] == ''
    assert state['capital_base'] == 500
    assert result['snapshot']['equity'] <= before
    assert result['snapshot']['equity'] == pytest.approx(before, abs=.01)
    saved = copy.deepcopy(state)
    assert run(sc, prices, state, broker, now)['status'] == 'skip'
    assert state == saved  # no second fill or manual cash adjustment on retry


def test_withdrawal_covers_costs_without_spending_the_new_cash():
    sc, prices, state, broker, now = setup_case(cash=200., previous_capital=700.)
    state['ledger']['cash'] = 0.
    state['ledger']['positions'] = {'SPY': 4.2, 'IEF': 2.8}
    result = run(sc, prices, state, broker, now)
    assert broker.cash() >= 0
    assert result['equity_row']['flow'] == -200
    assert state['capital_base'] == 500
    assert all(t['side'] == 'sell' for t in result['trades'])
    assert 498 < result['snapshot']['equity'] < 500
    assert not state.get('kill_switch')


@pytest.mark.parametrize('price', [1.27, 500.02])
def test_minimum_sale_survives_weight_and_quantity_rounding(price):
    sc, prices, state, broker, now = setup_case()
    prices['SPY'] = price
    state['ledger']['positions']['SPY'] = 300 / price
    result = run(sc, prices, state, broker, now)
    assert result['status'] == 'ok'
    assert len(result['trades']) == 1
    assert result['trades'][0]['value'] >= broker.min_order_value
    assert broker.cash() >= 0
    assert not state['execution_pending']


def test_no_fresh_sellable_price_leaves_an_explicit_error_without_fabricating_cash():
    sc, prices, state, broker, now = setup_case()
    prices.iloc[-1] = float('nan')
    result = run(sc, prices, state, broker, now)
    assert result['status'] == 'error'
    assert result['trades'] == []
    assert broker.cash() == -.10
    assert state['execution_pending']
    assert 'last_candle' not in state


def test_failed_sell_is_retried_once_successful_without_duplicate_fills():
    sc, prices, state, broker, now = setup_case()
    execute = broker.execute
    broker.execute = lambda asset, side, qty, ref: Fill(asset, side, 0, ref, 0, status='failed')
    first = run(sc, prices, state, broker, now)
    assert first['status'] == 'error' and broker.cash() == -.10
    broker.execute = execute
    second = run(sc, prices, state, broker, now)
    assert second['status'] == 'ok' and broker.cash() >= 0
    assert len(second['trades']) == 1
    assert run(sc, prices, state, broker, now)['status'] == 'skip'


def test_external_negative_cash_blocks_instead_of_automatically_selling():
    sc, prices, state, broker, now = setup_case()
    class External:
        name = 'external-test'
        min_order_value = 1.
        cash = broker.cash
        positions = broker.positions
        pending = broker.pending
        def execute(self, *args):
            raise AssertionError('External orders must not be sent')
    state['sleeve_cash'] = -.10
    result = run(sc, prices, state, External(), now)
    assert result['status'] == 'blocked'
    assert result['trades'] == []
    assert broker.cash() == -.10


def test_healthy_portfolio_does_not_sell_to_create_a_new_cash_reserve():
    sc, prices, state, broker, now = setup_case(cash=0.)
    result = run(sc, prices, state, broker, now)
    assert result['status'] == 'ok'
    assert result['trades'] == []
    assert broker.cash() == 0.
