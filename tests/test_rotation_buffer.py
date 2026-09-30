"""Synthetic causal/mechanical checks; no market experiment or profit claim."""
import copy

import numpy as np
import pandas as pd
import pytest

from lab import bot, research_multi, runtime
from lab.portfolio import PortfolioParams, listed_universe, select_ranked, target_weights


def panel():
    rng = np.random.default_rng(912)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.003, .025, (420, 7)), axis=0)),
                        index=pd.date_range("2020-01-01", periods=420),
                        columns=["BTC", "ETH", "SOL", "LINK", "UNI", "NEAR", "LTC"])


def test_small_rank_crossing_retains_incumbent_but_large_advantage_replaces():
    eligible = np.array([True, True])
    assert select_ranked(np.array([1., 1.10]), eligible, [0], 1, .15).tolist() == [0]
    assert select_ranked(np.array([1., 1.16]), eligible, [0], 1, .15).tolist() == [1]
    assert select_ranked(np.array([1., 1.10]), eligible, [0], 1, 0).tolist() == [1]


def test_ineligible_incumbent_exits_immediately_and_vacancy_can_be_filled():
    assert select_ranked(np.array([5., 1.]), np.array([False, True]), [0], 1, .15).tolist() == [1]
    assert not len(select_ranked(np.array([5., 1.]), np.array([False, False]), [0], 1, .15))


def test_zero_buffer_reproduces_original_stable_ranking():
    rng = np.random.default_rng(71)
    for _ in range(30):
        score = rng.normal(size=16)
        okay = score > 0
        expected = np.flatnonzero(okay)
        expected = expected[np.argsort(-score[expected], kind="stable")][:5]
        np.testing.assert_array_equal(select_ranked(score, okay, [1, 2], 5, 0), expected)


def test_candidate_cannot_look_ahead_and_last_only_reconstructs_prior_selections():
    prices = panel()
    p = PortfolioParams(rotation_buffer=.15)
    full = target_weights(prices, listed_universe(prices), p)
    prefix = target_weights(prices.iloc[:350], listed_universe(prices.iloc[:350]), p)
    pd.testing.assert_frame_equal(full.iloc[:350], prefix)
    changed = prices.copy()
    changed.iloc[350:] *= np.linspace(1, 10, 70)[:, None]
    future = target_weights(changed, listed_universe(changed), p)
    pd.testing.assert_frame_equal(full.iloc[:350], future.iloc[:350])
    last = target_weights(prices, listed_universe(prices), p, last_only=True)
    pd.testing.assert_series_equal(full.iloc[-1], last.iloc[-1])
    assert ((full > 0).sum(axis=1) <= 5).all()
    assert (full.sum(axis=1) <= 1 + 1e-9).all()
    assert (full.max(axis=1) <= .4 + 1e-9).all()


def test_regime_exit_is_not_delayed_by_rotation_buffer():
    prices = panel()
    prices['BTC'] = 100 * np.exp(np.linspace(0, -2, len(prices)))
    weights = target_weights(prices, listed_universe(prices), PortfolioParams(rotation_buffer=.15))
    assert (weights.iloc[250:] == 0).all().all()


def test_bot_and_research_share_the_candidate_selector():
    prices = panel()
    config = copy.deepcopy(bot.DEFAULT_CONFIG['sleeves']['crypto'])
    config['params']['rotation_buffer'] = .15
    weights = target_weights(prices, listed_universe(prices, config['min_history']), bot.sleeve_params(config))
    target, _ = bot.compute_targets(config, prices)
    pd.testing.assert_series_equal(target, weights.iloc[-1], check_names=False)


def test_declared_grid_contains_control_and_candidate_and_unique_labels():
    config, variants = research_multi.research_plan(universe='bitso', rotation_buffer=.15)
    crypto = [v for v in variants if v['sleeve'] == 'crypto']
    assert {v['params'].get('rotation_buffer', 0.) for v in crypto} == {0., .15}
    assert len({v['id'] for v in variants}) == len(variants)
    assert config['sleeves']['crypto']['candidate']['rotation_buffer'] == .15
    combos, _ = research_multi.grid_variants(config['sleeves']['crypto']['config'])
    assert len({research_multi.key_of(p) for p in combos}) == len(combos)


def test_hosted_runtime_rejects_unvalidated_candidate():
    config = copy.deepcopy(bot.DEFAULT_CONFIG)
    config['sleeves']['crypto']['params']['rotation_buffer'] = .15
    with pytest.raises(ValueError, match='validación'):
        runtime.validate_config(config)


@pytest.mark.parametrize('value', [-.1, 1, float('nan'), float('inf')])
def test_invalid_buffer_is_rejected(value):
    with pytest.raises(ValueError, match='rotation_buffer'):
        PortfolioParams(rotation_buffer=value)


def test_acceptance_rejects_weaker_evidence_and_requires_complete_years():
    evidence = dict(candidate={'cagr': .206, 'sharpe': 1., 'max_dd': -.3},
                    control={'cagr': .2, 'sharpe': 1., 'max_dd': -.3}, turns=[.84, 1.],
                    candidate_years={2021: .2, 2022: .2, 2023: .2},
                    control_years={2021: .1, 2022: .1, 2023: .3},
                    complete_years=[2021, 2022, 2023],
                    bootstrap={'p_return_better': .8, 'p_sharpe_better': .8}, placebo_p=.049,
                    stress_candidate={'cagr': .1, 'sharpe': .8}, stress_control={'cagr': .1, 'sharpe': .8})
    assert all(research_multi.rotation_checks(**evidence).values())
    changes = [({'candidate': {**evidence['candidate'], 'cagr': .204}}, 'net_cagr'),
               ({'candidate': {**evidence['candidate'], 'sharpe': .99}}, 'sharpe'),
               ({'candidate': {**evidence['candidate'], 'max_dd': -.311}}, 'drawdown'),
               ({'turns': [.86, 1.]}, 'turnover'), ({'turns': [0., 0.]}, 'turnover'),
               ({'complete_years': []}, 'annual_consistency'),
               ({'candidate_years': {2021: .2, 2022: .1, 2023: .2}}, 'annual_consistency'),
               ({'bootstrap': {'p_return_better': .79, 'p_sharpe_better': .99}}, 'bootstrap'),
               ({'placebo_p': .05}, 'placebo'),
               ({'stress_candidate': {'cagr': .09, 'sharpe': .9}}, 'cost_stress')]
    for changed, key in changes:
        assert not research_multi.rotation_checks(**{**evidence, **changed})[key]
