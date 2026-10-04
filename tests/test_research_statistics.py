"""Synthetic research-statistics mechanics; no downloaded or market data."""
import json

import numpy as np
import pandas as pd
import pytest

from lab.research_statistics import (chronological_folds, familywise_block_test,
                                     paired_block_evidence)


def pair(periods=90):
    index = pd.date_range("2021-01-01", periods=periods)
    rng = np.random.default_rng(512)
    control = pd.Series(rng.normal(.0002, .01, periods), index=index)
    candidate = control + rng.normal(.0001, .003, periods)
    return candidate, control


def test_pair_identical_paths_have_no_superiority_or_fake_sharpe():
    _, control = pair()
    result = paired_block_evidence(control, control, n=31, block=10)
    assert result["observed"] == {"delta_log_wealth": 0., "delta_sharpe": 0.}
    assert result["delta_log_wealth_ci95"] == [0., 0.]
    assert result["delta_sharpe_ci95"] == [0., 0.]
    assert result["p_return_better"] == result["p_sharpe_better"] == 0.
    assert result["degenerate"] and not result["inferentially_valid"]


def test_pair_whole_sample_block_preserves_exact_statistics_and_inputs():
    a, b = pair(30)
    originals = (a.copy(), b.copy())
    result = paired_block_evidence(a, b, n=17, block=30)
    expected = float((np.log1p(a) - np.log1p(b)).sum())
    sharpe_delta = (a.mean() / a.std(ddof=1) - b.mean() / b.std(ddof=1)) * np.sqrt(365)
    assert result["observed"]["delta_log_wealth"] == pytest.approx(expected)
    assert result["delta_log_wealth_ci95"] == pytest.approx([expected, expected])
    assert result["delta_sharpe_ci95"] == pytest.approx([sharpe_delta, sharpe_delta])
    assert result["degenerate"] and not result["inferentially_valid"]
    pd.testing.assert_series_equal(a, originals[0])
    pd.testing.assert_series_equal(b, originals[1])
    json.dumps(result, allow_nan=False)


def test_pair_is_reproducible_and_order_swaps_difference_sign():
    a, b = pair()
    left = paired_block_evidence(a, b, n=60, block=13)
    assert left == paired_block_evidence(a, b, n=60, block=13)
    right = paired_block_evidence(b, a, n=60, block=13)
    assert left["delta_log_wealth_ci95"] == pytest.approx([-x for x in right["delta_log_wealth_ci95"][::-1]])
    assert left["delta_sharpe_ci95"] == pytest.approx([-x for x in right["delta_sharpe_ci95"][::-1]])


def test_constant_returns_do_not_invent_infinite_sharpe_or_significance():
    index = pd.date_range("2021-01-01", periods=40)
    a, b = pd.Series(.01, index=index), pd.Series(0., index=index)
    paired = paired_block_evidence(a, b, n=19, block=10)
    assert paired["observed"]["delta_sharpe"] is None
    assert paired["delta_sharpe_ci95"] is None
    assert paired["p_sharpe_better"] == 0.
    assert not paired["inferentially_valid"]
    family = familywise_block_test(pd.DataFrame({"constant": a, "identical": b}), b, n=19, block=10)
    assert family["global_p"] == 1.
    assert all(row["p_raw"] == row["p_adjusted"] == 1. for row in family["by_candidate"].values())
    json.dumps({"pair": paired, "family": family}, allow_nan=False)


def test_family_uses_one_resampling_plan_for_duplicate_and_reordered_columns():
    a, b = pair()
    frame = pd.DataFrame({"one": a, "copy": a, "control_copy": b})
    result = familywise_block_test(frame, b, n=99, block=13)
    assert result["by_candidate"]["one"] == result["by_candidate"]["copy"]
    assert result["by_candidate"]["control_copy"]["p_adjusted"] == 1.
    reordered = familywise_block_test(frame[["copy", "control_copy", "one"]], b, n=99, block=13)
    assert result["by_candidate"] == reordered["by_candidate"]
    assert result["global_p"] == reordered["global_p"]
    for value in result["by_candidate"].values():
        assert 1 / 100 <= value["p_raw"] <= value["p_adjusted"] <= 1.
    json.dumps(result, allow_nan=False)


def test_family_centering_finite_correction_and_inferior_challenger():
    _, b = pair(60)
    shift = pd.Series(np.linspace(.01, .02, len(b)), index=b.index)
    better = np.expm1(np.log1p(b) + shift)
    worse = np.expm1(np.log1p(b) - shift)
    result = familywise_block_test(pd.DataFrame({"better": better, "worse": worse}), b,
                                   n=49, block=10)
    assert result["by_candidate"]["better"]["p_raw"] == 1 / 50
    assert result["by_candidate"]["better"]["p_adjusted"] == 1 / 50
    assert result["by_candidate"]["worse"]["p_adjusted"] == 1.
    assert result["global_p"] == 1 / 50
    assert result["history_status"] == "not_verified_as_unseen"


def test_family_whole_sample_blocks_cannot_establish_significance():
    _, b = pair(60)
    shift = pd.Series(np.linspace(.01, .02, len(b)), index=b.index)
    better = np.expm1(np.log1p(b) + shift)
    result = familywise_block_test(pd.DataFrame({"better": better}), b, n=49, block=60)
    assert result["by_candidate"]["better"]["observed_mean_log_excess"] == pytest.approx(.015)
    assert result["by_candidate"]["better"]["degenerate"]
    assert result["by_candidate"]["better"]["p_raw"] == 1.
    assert result["by_candidate"]["better"]["p_adjusted"] == result["global_p"] == 1.


def test_negative_observed_mean_keeps_raw_tail_probability_and_adjusted_one():
    _, b = pair(90)
    shift = pd.Series(np.linspace(-.006, .004, len(b)), index=b.index)
    candidate = np.expm1(np.log1p(b) + shift)
    result = familywise_block_test(pd.DataFrame({"lower": candidate}), b, n=199, block=10)
    row = result["by_candidate"]["lower"]
    assert row["observed_mean_log_excess"] == pytest.approx(-.001)
    assert not row["degenerate"]
    assert 0. < row["p_raw"] < 1.
    assert row["p_adjusted"] == result["global_p"] == 1.


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, -1., -1.01])
def test_invalid_returns_are_rejected(bad):
    a, b = pair()
    a.iloc[4] = bad
    with pytest.raises(ValueError, match="finite returns"):
        paired_block_evidence(a, b)
    with pytest.raises(ValueError, match="finite returns"):
        familywise_block_test(pd.DataFrame({"bad": a}), b)


def test_misaligned_duplicate_and_unsorted_indices_are_not_silently_repaired():
    a, b = pair()
    for invalid in (a.iloc[::-1], a.set_axis([a.index[0]] * len(a)),
                    a.set_axis(a.index + pd.Timedelta(days=1))):
        with pytest.raises(ValueError):
            paired_block_evidence(invalid, b)
        with pytest.raises(ValueError):
            familywise_block_test(pd.DataFrame({"invalid": invalid}), b)


@pytest.mark.parametrize("kwargs", [{"n": 0}, {"n": True}, {"n": 2.5}, {"block": 0},
                                   {"block": True}, {"block": 91}])
def test_invalid_bootstrap_configuration_is_rejected(kwargs):
    a, b = pair()
    with pytest.raises(ValueError):
        paired_block_evidence(a, b, **kwargs)
    with pytest.raises(ValueError):
        familywise_block_test(pd.DataFrame({"a": a}), b, **kwargs)


def test_family_requires_a_unique_declared_column_identity():
    a, b = pair()
    for frame in (pd.DataFrame(index=b.index), pd.concat([a, a], axis=1).set_axis(["same", "same"], axis=1),
                  pd.DataFrame({0: a})):
        with pytest.raises(ValueError, match="column names"):
            familywise_block_test(frame, b)


def test_folds_keep_initial_loss_and_previous_year_peak_without_refitting():
    index = pd.date_range("2021-01-01", "2023-03-04")
    a, b = pd.Series(0., index=index), pd.Series(0., index=index)
    a.loc["2021-01-01"] = -.10
    a.loc["2021-06-01"] = 1.
    a.loc["2021-12-31"] = -.50
    a.loc["2022-01-01"] = -.10
    result = chronological_folds(a, b)
    assert result["complete_years"] == [2021, 2022]
    assert result["folds"][0]["candidate"]["total_return"] == pytest.approx(-.10)
    assert result["folds"][0]["candidate_return"] == pytest.approx(-.10)
    assert result["folds"][0]["control_return"] == 0.
    assert result["folds"][1]["candidate"]["total_return"] == pytest.approx(-.10)
    assert result["folds"][1]["candidate"]["max_drawdown_continuous"] == pytest.approx(-.55)
    assert result["win_fraction"] == 0.
    assert result["wins"] == 0
    assert result["omitted_years"][-1]["year"] == 2023
    assert not result["selection_performed"] and not result["portfolio_reset"]
    json.dumps(result, allow_nan=False)


def test_folds_reject_incomplete_years_and_handle_leap_year():
    index = pd.date_range("2023-07-01", "2025-12-31")
    a = pd.Series(0., index=index).drop(pd.Timestamp("2025-01-01"))
    result = chronological_folds(a, a, first_year=2023)
    assert result["complete_years"] == [2024]
    assert result["folds"][0]["observations"] == 366
    assert [row["year"] for row in result["omitted_years"]] == [2023, 2025]


def test_future_extension_cannot_change_prior_completed_fold_metrics():
    index = pd.date_range("2021-01-01", "2022-12-31", tz="UTC")
    a, b = pd.Series(.001, index=index), pd.Series(.0005, index=index)
    before = chronological_folds(a, b)
    suffix = pd.date_range("2023-01-01", "2023-12-31", tz="UTC")
    after = chronological_folds(pd.concat([a, pd.Series(-.01, index=suffix)]),
                                pd.concat([b, pd.Series(.01, index=suffix)]))
    assert before["folds"] == after["folds"][:2]


def test_folds_do_not_claim_training_and_require_daily_dates():
    a, b = pair(40)
    result = chronological_folds(a, b)
    assert result["complete_years"] == [] and result["win_fraction"] is None
    with pytest.raises(ValueError, match="daily DatetimeIndex"):
        chronological_folds(a.reset_index(drop=True), b.reset_index(drop=True))
