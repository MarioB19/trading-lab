"""Mechanical ledger checks on invented prices; no market experiment."""
import numpy as np
import pandas as pd
import pytest

from lab.portfolio import PortfolioParams, simulate_funded_portfolio


def frames(prices, weights):
    index = pd.date_range("2024-01-01", periods=len(prices))
    return (pd.DataFrame(prices, index=index, dtype=float),
            pd.DataFrame(weights, index=index, dtype=float))


def run(prices, weights, **kwargs):
    return simulate_funded_portfolio(prices, weights, PortfolioParams(dd_brake=False), **kwargs)


def test_band_can_skip_sales_but_cannot_fund_purchases_with_debt():
    prices, weights = frames([[100] * 3] * 3, [[.34, .33, .33], [.39, .305, .305], [.39, .305, .305]])
    result = run(prices, weights, cost=0, band=.03)
    assert result["equity"].eq(500).all()
    assert (result["cash"] >= 0).all()
    assert result["position"].max() <= 1 + 1e-12
    assert result["turnover"].iloc[-1] == 0  # .05 buy needs cash; both .025 sells are inside band.
    np.testing.assert_allclose(result.attrs["held"].iloc[-1], [.34, .33, .33])


def test_sales_fund_buys_and_every_dollar_of_cost_reduces_equity_once():
    prices, weights = frames([[100, 100]] * 3, [[1, 0], [0, 1], [0, 1]])
    result = run(prices, weights, cost=.01, band=0)
    assert result["equity"].iloc[1] == pytest.approx(500 / 1.01)
    assert result["equity"].iloc[2] == pytest.approx((500 / 1.01) * .99 / 1.01)
    assert result["equity"].iloc[-1] == pytest.approx(500 - result["cost_usd"].sum())
    assert result["cost_usd"].iloc[-1] > result["cost_usd"].iloc[1]  # sale plus funded purchase
    assert (result["cash"] >= 0).all()
    assert result.attrs["held"].iloc[-1, 0] == 0
    assert result.attrs["held"].iloc[-1, 1] == pytest.approx(1)


def test_buys_share_cash_proportionally_after_cost():
    prices, weights = frames([[100, 100]] * 2, [[.6, .4]] * 2)
    result = run(prices, weights, cost=.02, band=0)
    np.testing.assert_allclose(result.attrs["held"].iloc[-1], [.6, .4])
    assert result["cash"].iloc[-1] == pytest.approx(0, abs=1e-10)
    assert result["equity"].iloc[-1] == pytest.approx(500 / 1.02)


def test_minimum_is_dollars_per_order_and_full_exit_bypasses_only_band():
    prices, weights = frames([[100, 100]] * 3, [[.008, .01], [0, 0], [0, 0]])
    result = run(prices, weights, cost=0, band=0, min_order_value=5)
    assert result.attrs["held"].iloc[1, 0] == 0  # $4 order rejected.
    assert result.attrs["held"].iloc[1, 1] == pytest.approx(.01)  # $5 accepted.
    assert result["turnover"].iloc[1] == pytest.approx(.01)
    # Hold a small position, then request its entire exit inside a wider band.
    prices, weights = frames([[100]] * 3, [[.2], [0], [0]])
    result = run(prices, weights, cost=0, band=.1, min_order_value=5)
    assert result["cash"].iloc[-1] == 500 and result["position"].iloc[-1] == 0


def test_untradeable_small_purchase_does_not_reserve_cash_from_valid_orders():
    prices, weights = frames([[100, 100]] * 2, [[.992, .008]] * 2)
    result = run(prices, weights, cost=.01, band=0, min_order_value=5)
    assert result["cash"].iloc[-1] == pytest.approx(0, abs=1e-10)
    assert result.attrs["held"].iloc[-1, 1] == 0
    assert result["equity"].iloc[-1] == pytest.approx(500 / 1.01)


def test_small_exit_still_obeys_minimum_and_keeps_actual_inventory_value():
    prices, weights = frames([[100], [4], [4]], [[.2], [0], [0]])
    result = run(prices, weights, cost=0, band=.1, min_order_value=5, kill_dd=None)
    assert result["cash"].iloc[-1] == 400
    assert result["equity"].iloc[-1] == 404
    assert result["position"].iloc[-1] > 0
    assert result["turnover"].iloc[-1] == 0  # Cannot invent liquidation of $4 dust.


def test_kill_switch_persists_after_price_recovery():
    prices, weights = frames([[100], [70], [70], [100]], [[.8]] * 4)
    result = run(prices, weights, cost=0, band=.02, kill_dd=.2)
    assert result["equity"].tolist() == pytest.approx([500, 380, 380, 380])
    assert result["killed"].tolist() == [False, False, True, True]
    assert result["brake"].tolist() == [1, 1, 0, 0]
    assert result["cash"].iloc[-1] == 380
    assert result["position"].iloc[-1] == 0


def test_signal_lag_and_future_mutations_cannot_change_earlier_returns():
    prices, weights = frames([[100], [200], [300], [400]], [[0], [1], [0], [1]])
    first = run(prices, weights, cost=0, band=0, kill_dd=None)
    assert first["ret"].tolist() == pytest.approx([0, 0, .5, 0])
    changed_prices, changed_weights = prices.copy(), weights.copy()
    changed_prices.iloc[-1] = 1
    changed_weights.iloc[-1] = 0
    changed = run(changed_prices, changed_weights, cost=0, band=0, kill_dd=None)
    pd.testing.assert_frame_equal(first.iloc[:-1], changed.iloc[:-1])


def test_evaluation_starts_flat_at_500_with_the_preceding_warmed_signal():
    prices, weights = frames([[100], [200], [300], [400]], [[1]] * 4)
    result = run(prices, weights, start=prices.index[2], cost=0, band=0, kill_dd=None)
    assert result.index.equals(prices.index[2:])
    assert result["equity"].tolist() == pytest.approx([750, 1000])
    assert result["ret"].iloc[0] == pytest.approx(.5)
    assert result["turnover"].iloc[0] == 1
    assert result.attrs["initial_capital_usd"] == 500
    prices.iloc[0] = 1e9
    changed = run(prices, weights, start=prices.index[2], cost=0, band=0, kill_dd=None)
    pd.testing.assert_frame_equal(result, changed)


def test_missing_prelisting_prices_are_allowed_until_any_inventory_exists():
    prices, weights = frames([[np.nan], [np.nan], [100], [110]], [[0], [0], [.5], [.5]])
    result = run(prices, weights, cost=0, band=0)
    assert result["equity"].tolist() == pytest.approx([500, 500, 500, 525])
    assert result.attrs["held"].iloc[-1, 0] == .5


def test_five_row_marking_policy_does_not_allow_trading_at_missing_raw_quote():
    prices, weights = frames([[100], [np.nan], [100]], [[.5], [0], [0]])
    result = run(prices, weights, cost=0, band=0)
    assert result["equity"].eq(500).all()
    assert result["cash"].iloc[-1] == 250  # Missing decision quote prevents the sale.
    assert result["turnover"].iloc[-1] == 0
    assert result.attrs["valuation_ffill_rows"] == 5


def test_held_price_gap_longer_than_five_rows_fails_instead_of_valuing_zero():
    prices, weights = frames([[100]] + [[np.nan]] * 6, [[.5]] * 7)
    with pytest.raises(ValueError, match="sin precio para posición abierta"):
        run(prices, weights, cost=0, band=0)


def test_drawdown_brake_uses_shared_rule_before_next_return():
    prices, weights = frames([[100], [80], [80]], [[.5]] * 3)
    p = PortfolioParams(dd_brake=True, dd_start=.05, dd_full=.15, dd_floor=0)
    result = simulate_funded_portfolio(prices, weights, p, cost=0, band=0, kill_dd=None)
    assert result["equity"].iloc[-1] == 450
    assert result["brake"].iloc[-1] == pytest.approx(.5)
    assert result["position"].iloc[-1] == pytest.approx(.25)


@pytest.mark.parametrize("weights", [[[1.01]], [[-.1]], [[np.nan]]])
def test_invalid_target_cannot_introduce_leverage_or_an_unknown_allocation(weights):
    prices, target = frames([[100]], weights)
    with pytest.raises(ValueError, match="pesos deben"):
        run(prices, target)


@pytest.mark.parametrize("options", [{"cost": -1}, {"cost": 1}, {"initial_capital": 0},
                                    {"min_order_value": -1}, {"kill_dd": 0}, {"band": np.nan}])
def test_invalid_execution_contract_fails_before_simulation(options):
    prices, weights = frames([[100]], [[0]])
    with pytest.raises(ValueError):
        run(prices, weights, **options)
