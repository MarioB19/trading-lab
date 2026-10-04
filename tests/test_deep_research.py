"""Offline integration of the research pipeline using only artificial prices."""
from __future__ import annotations

import copy
import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from lab import deep_research as research
from lab import portfolio
from lab import research_multi
from lab.experiments import ResearchGateError, canonical_hash, file_hash


def _sleeve(dates, values):
    return pd.DataFrame({"equity": values}, index=pd.DatetimeIndex(dates))


def test_economic_curve_counts_first_trading_loss_against_500_plus_500():
    dates = pd.date_range("2021-01-01", periods=3)
    crypto = _sleeve(dates, [497.75, 501., 502.])
    stocks = _sleeve(dates, [499.75, 499.75, 500.])
    result = research.economic_curve(crypto, stocks, 0., "2021-01-01", "2021-01-03")
    assert result["portfolio_equity"].iloc[0] == 997.5
    assert result["ret"].iloc[0] == pytest.approx(-.0025)
    assert np.prod(1 + result["ret"]) == pytest.approx(1002. / 1000.)
    assert research._metrics(result)["max_dd"] == pytest.approx(-.0025)
    assert research._metrics(result)["pnl_usd"] == 2.


def test_weekends_keep_etf_marks_and_cash_until_first_session_without_future_fill():
    dates = pd.date_range("2021-01-02", "2021-01-11")
    crypto = _sleeve(dates, 500.)
    stocks = _sleeve(["2021-01-04", "2021-01-08", "2021-01-11"], [498., 501., 503.])
    result = research.economic_curve(crypto, stocks, 0., "2021-01-02", "2021-01-11")
    assert result.loc["2021-01-02":"2021-01-03", "stocks_equity"].eq(500.).all()
    assert result.loc["2021-01-04":"2021-01-07", "stocks_equity"].eq(498.).all()
    assert result.loc["2021-01-08":"2021-01-10", "stocks_equity"].eq(501.).all()
    assert result.loc["2021-01-11", "stocks_equity"] == 503.
    assert result.loc["2021-01-03", "ret"] == 0.
    assert result.loc["2021-01-04", "ret"] == pytest.approx(-.002)


def test_monthly_expense_accrues_over_calendar_days_including_leap_february():
    dates = pd.date_range("2024-01-01", "2024-03-01")
    sleeve = _sleeve(dates, 500.)
    result = research.economic_curve(sleeve, sleeve, 31., "2024-01-01", "2024-03-01")
    assert result.loc["2024-01-01", "ret"] == pytest.approx(-.001)
    assert result.loc["2024-01-31", "hosting_accrued"] == pytest.approx(31.)
    assert result.loc["2024-02-29", "hosting_accrued"] == pytest.approx(62.)
    assert result.loc["2024-03-01", "hosting_accrued"] == pytest.approx(63.)
    assert result["portfolio_equity"].eq(1000.).all()
    assert result["crypto_equity"].eq(500.).all() and result["stocks_equity"].eq(500.).all()
    assert result["equity"].iloc[-1] == pytest.approx(937.)
    assert np.prod(1 + result["ret"]) == pytest.approx(.937)


@pytest.mark.parametrize("expense", [-1., np.nan, np.inf])
def test_economic_curve_rejects_invalid_expenses(expense):
    sleeve = _sleeve(pd.date_range("2021-01-01", periods=3), 500.)
    with pytest.raises(ValueError, match="expense"):
        research.economic_curve(sleeve, sleeve, expense, "2021-01-01", "2021-01-03")


def test_economic_curve_rejects_duplicate_dates():
    sleeve = _sleeve(pd.date_range("2021-01-01", periods=3), 500.)
    duplicate = pd.concat([sleeve, sleeve.iloc[[-1]]])
    with pytest.raises(ValueError, match="unique and sorted"):
        research.economic_curve(duplicate, sleeve, 0., "2021-01-01", "2021-01-03")


def test_economic_expenses_beyond_capital_preserve_entire_dollar_loss():
    dates = pd.date_range("2021-01-01", "2026-09-25")
    sleeve = _sleeve(dates, 500.)
    curve = research.economic_curve(sleeve, sleeve, 20., "2021-01-01", "2026-09-25")
    expense = 20 * (68 + 25 / 30)
    assert curve["portfolio_equity"].eq(1000.).all()
    assert curve["hosting_accrued"].iloc[-1] == pytest.approx(expense)
    assert curve["equity"].iloc[-1] == pytest.approx(1000. - expense)
    assert curve["economic_deficit"].iloc[-1]
    assert curve.loc[curve["economic_deficit"], "ret"].isna().all()
    assert curve.loc[~curve["economic_deficit"], "ret"].notna().all()
    metrics = research._metrics(curve)
    assert metrics["pnl_usd"] == pytest.approx(-expense)
    assert metrics["max_dd"] == pytest.approx(-expense / 1000.)
    assert metrics["compounding_defined"] is False
    assert metrics["cagr"] is metrics["sharpe"] is metrics["worst_month"] is None
    json.dumps(metrics, allow_nan=False)


@pytest.mark.parametrize("capital", [0., -500., np.nan, np.inf])
def test_economic_curve_rejects_invalid_initial_capital(capital):
    sleeve = _sleeve(pd.date_range("2021-01-01", periods=3), 500.)
    with pytest.raises(ValueError, match="capital"):
        research.economic_curve(sleeve, sleeve, 0., "2021-01-01", "2021-01-03", capital)


def test_explicit_missing_equity_in_source_is_not_forward_filled_as_weekend():
    dates = pd.date_range("2021-01-01", periods=3)
    crypto, stocks = _sleeve(dates, [500., np.nan, 510.]), _sleeve(dates, 500.)
    with pytest.raises(ValueError, match="equity"):
        research.economic_curve(crypto, stocks, 0., "2021-01-01", "2021-01-03")


def test_holm_uses_monotone_step_down_adjustment_independent_of_input_order():
    values = {"third": .04, "first": .01, "last": .8, "second": .03}
    result = research.holm_adjust(values)
    assert result == pytest.approx({"first": .04, "second": .09, "third": .09, "last": .8})
    assert result == research.holm_adjust(dict(reversed(list(values.items()))))
    assert research.holm_adjust({"a": .6, "b": .6}) == {"a": 1., "b": 1.}
    assert research.holm_adjust({}) == {}


@pytest.mark.parametrize("value", [-.1, 1.1, np.nan, np.inf])
def test_holm_rejects_invalid_pvalues(value):
    with pytest.raises(ValueError, match="p-value"):
        research.holm_adjust({"valid": .1, "invalid": value})


@pytest.mark.parametrize("values", [[0., 0., 0.], [.001, .001, .001], [0., np.nan], [0., np.inf], [.1]])
def test_undefined_sharpe_never_passes_comparison(values):
    assert research._research_sharpe(pd.Series(values)) is None
    assert research._at_least(None, 0.) is False
    assert research._at_least(0., None) is False
    assert research._at_least(None, None) is False


def test_placebo_shifts_consumed_previous_decisions_and_keeps_unused_final_signal():
    dates = pd.date_range("2021-01-01", periods=4)
    weights = pd.DataFrame(np.eye(4), index=dates, columns=list("abcd"))
    eligible = pd.DataFrame(True, index=dates, columns=weights.columns)
    shifted = research._shift_decisions(weights, eligible, [1, 2, 3], 1)
    assert shifted.idxmax(axis=1).tolist() == list("cabd")
    pd.testing.assert_frame_equal(weights, pd.DataFrame(np.eye(4), index=dates, columns=list("abcd")))
    eligible.loc[dates[0], "c"] = False
    masked = research._shift_decisions(weights, eligible, [1, 2, 3], 1)
    assert masked.iloc[0].eq(0.).all()
    assert masked.iloc[1:].idxmax(axis=1).tolist() == list("abd")
    with pytest.raises(ResearchGateError, match="anterior"):
        research._shift_decisions(weights, eligible, [0, 1, 2], 1)


def test_equivalence_reconstructs_eligibility_from_each_rolling_window(monkeypatch):
    plan, _ = research.deep_plan()
    dates = pd.date_range("2020-01-01", periods=300)
    prices = pd.DataFrame(100., index=dates, columns=["BTC", "ETH"])
    eligible = pd.DataFrame(True, index=dates, columns=prices.columns)
    weights = pd.DataFrame(.5, index=dates, columns=prices.columns)
    plan["evaluation"]["start"] = str(dates[260].date())
    plan["execution_equivalence_diagnostic"].update(window_rows=200, sample_dates=2,
                                                    reconstruct_window_eligibility_min_history=250)
    seen = []
    def reconstruct(window_prices, window_eligible, params, last_only=False):
        assert last_only is True
        seen.append((window_prices.copy(), window_eligible.copy()))
        return window_eligible.astype(float) * .5
    monkeypatch.setattr(research, "target_weights", reconstruct)
    result = research._equivalence(prices, eligible, weights, None, plan)
    assert len(seen) == 2
    assert all(len(panel) == 200 and not mask.any().any() for panel, mask in seen)
    assert result["sampled_dates_pass"] is False
    assert result["complete_execution_equivalence"] is False
    assert all(row["max_abs_weight_difference"] == .5 for row in result["samples"])


def _forbidden(*args, **kwargs):
    pytest.fail("Unexpected market access or calculation before authorization")


@pytest.mark.parametrize("mismatch", ["absent", "config_hash", "manifest", "variants"])
def test_execution_identity_gate_precedes_frozen_file_reads(monkeypatch, tmp_path, mismatch):
    plan, variants = research.deep_plan()
    execution = SimpleNamespace(config_hash=canonical_hash(plan), manifest={"config": copy.deepcopy(plan)},
                                variants={row["id"]: row for row in variants})
    if mismatch == "absent":
        execution = None
    elif mismatch == "config_hash":
        execution.config_hash = "0" * 64
    elif mismatch == "manifest":
        execution.manifest["config"]["capital"]["crypto"] = 501.
    else:
        execution.variants.pop(variants[-1]["id"])
    monkeypatch.setattr(research, "_load_frozen", _forbidden)
    monkeypatch.setattr(research, "target_weights", _forbidden)
    with pytest.raises(ResearchGateError, match="preregistrada exacta"):
        research.run_deep(execution, tmp_path / "unread")
    assert list(tmp_path.iterdir()) == []


def test_describe_is_stable_offline_and_does_not_start_an_experiment(monkeypatch, capsys):
    monkeypatch.setattr(research_multi, "ExperimentRun", _forbidden)
    monkeypatch.setattr(research_multi, "load_crypto_panel", _forbidden)
    monkeypatch.setattr(research_multi, "load_etf_panel", _forbidden)
    monkeypatch.setattr(research, "_load_frozen", _forbidden)
    monkeypatch.setattr(research, "target_weights", _forbidden)
    monkeypatch.setattr(sys, "argv", ["research_multi", "--deep-profile", "cost-aware-v1", "--describe"])
    research_multi.main()
    first = json.loads(capsys.readouterr().out)
    research_multi.main()
    second = json.loads(capsys.readouterr().out)
    assert first == second
    assert first["config_sha256"] == canonical_hash(first["config"])
    assert first["config"]["capital"] == {"crypto": 500., "stocks": 500.}
    assert first["config"]["promotion"]["automatic"] is False
    assert first["config"]["promotion"]["live_authorized"] is False
    assert len(first["variants"]) == 6
    assert len({row["id"] for row in first["variants"]}) == 6
    assert all(row["status"] == "declared" for row in first["variants"])
    json.dumps(first, allow_nan=False)


class FakeExecution:
    """In-memory registration double; it never validates a real preregistration."""
    def __init__(self, directory, plan, variants):
        self.directory = directory
        directory.mkdir()
        self.config_hash = canonical_hash(plan)
        self.manifest = {"config": copy.deepcopy(plan)}
        self.variants = {row["id"]: copy.deepcopy(row) for row in variants}
        self.states = dict.fromkeys(self.variants, "declared")
        self.events = []
        self.frozen = {}

    def freeze_dataset(self, name, prices, eligible, provenance):
        assert name not in self.frozen
        self.frozen[name] = (prices.copy(), eligible.copy(), copy.deepcopy(provenance))

    def variant(self, identity, state):
        assert len(self.frozen) == 2
        assert identity in self.variants
        self.states[identity] = state
        self.events.append((identity, state))


def _artificial_inputs(tmp_path, placebo_n):
    plan, variants = research.deep_plan()
    plan["evaluation"].update(start="2021-01-01", end="2021-05-25")
    plan["inference"].update(bootstrap_n=29, placebo_n=placebo_n)
    plan["execution_equivalence_diagnostic"]["sample_dates"] = 3
    dates = pd.date_range("2020-04-01", plan["evaluation"]["end"])
    rng = np.random.default_rng(821)
    crypto = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.0004, .015, (len(dates), 16)), axis=0)),
                          index=dates, columns=plan["assets"])
    sessions = pd.bdate_range(dates[0], dates[-1])
    stocks = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.0001, .005, (len(sessions), 2)), axis=0)),
                          index=sessions, columns=["SPY", "IEF"])
    source = tmp_path / "artificial_inputs"
    source.mkdir()
    frames = {"crypto_prices.csv": crypto, "crypto_eligible.csv": crypto.notna(),
              "stocks_prices.csv": stocks, "stocks_eligible.csv": stocks.notna()}
    for name, frame in frames.items():
        frame.index.name = "date"
        frame.to_csv(source / name, index_label="date")
    plan["input_sha256"] = {name: file_hash(source / name) for name in frames}
    return plan, variants, source, frames


@pytest.mark.parametrize("placebo_n", [2, 3])
def test_run_deep_artificial_end_to_end_emits_finite_evidence_without_promotion(monkeypatch, tmp_path, placebo_n):
    plan, variants, source, frames = _artificial_inputs(tmp_path, placebo_n)
    monkeypatch.setattr(research, "deep_plan", lambda: (copy.deepcopy(plan), copy.deepcopy(variants)))
    monkeypatch.setattr(research_multi, "load_crypto_panel", _forbidden)
    monkeypatch.setattr(research_multi, "load_etf_panel", _forbidden)
    execution = FakeExecution(tmp_path / "synthetic_result", plan, variants)
    output = research.run_deep(execution, source)
    assert set(execution.states.values()) == {"completed"}
    assert execution.events == [(row["id"], state) for row in variants for state in ("started", "completed")]
    assert set(execution.frozen) == {"crypto", "stocks"}
    for sleeve in ("crypto", "stocks"):
        prices, eligible, provenance = execution.frozen[sleeve]
        pd.testing.assert_frame_equal(prices, frames[f"{sleeve}_prices.csv"], check_freq=False)
        pd.testing.assert_frame_equal(eligible, frames[f"{sleeve}_eligible.csv"], check_freq=False)
        assert provenance["inspected_history"] is True
    assert output["classification"] == "retrospective_inspected"
    assert output["live_authorized"] is output["promoted"] is False
    assert output["plan_sha256"] == canonical_hash(plan)
    assert set(output["block_sensitivities"]) == {"14", "90"}
    assert output["familywise"]["family_size"] == 3
    assert set(output["results"]) == {row["name"] for row in variants}
    for name, result in output["results"].items():
        assert result["minimum_cash_usd"] >= -1e-8
        assert result["max_crypto_exposure"] <= 1 + 1e-8
        crypto_path = execution.directory / f"{name}_crypto.csv"
        assert crypto_path.is_file()
        for cost in plan["economics"]["monthly_costs_usd"]:
            curve = pd.read_csv(execution.directory / f"{name}_expense_{cost}.csv", index_col=0, parse_dates=True)
            assert curve.index.equals(pd.date_range(plan["evaluation"]["start"], plan["evaluation"]["end"]))
            assert np.isfinite(curve.to_numpy(dtype=float)).all()
            assert np.prod(1 + curve["ret"]) == pytest.approx(curve["equity"].iloc[-1] / 1000.)
            assert (curve["portfolio_equity"] - curve["equity"]).iloc[-1] == pytest.approx(curve["hosting_accrued"].iloc[-1])
        if name in output["familywise"]["by_candidate"]:
            assert result["placebo"]["n"] == placebo_n
            assert result["promoted"] is result["eligible_for_new_forward_validation"] is False
            assert result["folds"]["complete_years"] == []
            assert result["retrospective_checks"]["chronological_folds"] is False
            assert result["shortlisted_for_research_review"] is False
    cash = output["results"]["cash"]["metrics_by_monthly_cost"]
    assert cash["0.0"]["final_equity"] == 1000. and cash["0.0"]["pnl_usd"] == 0.
    assert cash["5.0"]["pnl_usd"] < 0
    samples = pd.read_csv(execution.directory / "placebo_samples.csv")
    assert len(samples) == placebo_n
    assert set(samples) == {"shift_days", "r0_b4", "r15_b2", "r15_b4"}
    assert samples["shift_days"].between(60, 85).all()
    assert (execution.directory / "deep_report.md").is_file()
    serialized = json.loads((execution.directory / "deep_results.json").read_text())
    assert serialized == json.loads(json.dumps(output, default=float, allow_nan=False))
    assert all(file_hash(source / name) == digest for name, digest in plan["input_sha256"].items())


def test_frozen_hash_mismatch_is_rejected_before_simulation(monkeypatch, tmp_path):
    plan, variants, source, _ = _artificial_inputs(tmp_path, 2)
    monkeypatch.setattr(research, "deep_plan", lambda: (copy.deepcopy(plan), copy.deepcopy(variants)))
    monkeypatch.setattr(research, "target_weights", _forbidden)
    execution = FakeExecution(tmp_path / "synthetic_result", plan, variants)
    with (source / "crypto_prices.csv").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ResearchGateError, match="ausente o modificada"):
        research.run_deep(execution, source)
    assert execution.events == [] and execution.frozen == {}
    assert list(execution.directory.iterdir()) == []


def test_primary_economic_deficit_finishes_report_and_cannot_pass_inference(monkeypatch, tmp_path):
    """Inject an extreme synthetic ledger loss, not a hypothetical market forecast."""
    plan, variants, source, _ = _artificial_inputs(tmp_path, 2)
    monkeypatch.setattr(research, "deep_plan", lambda: (copy.deepcopy(plan), copy.deepcopy(variants)))
    monkeypatch.setattr(research_multi, "load_crypto_panel", _forbidden)
    monkeypatch.setattr(research_multi, "load_etf_panel", _forbidden)

    def extreme_loss(prices, weights, params, **kwargs):
        assert kwargs["initial_capital"] == 500.
        dates = prices.loc[kwargs["start"]:].index
        equity = pd.Series(2.5, index=dates)
        equity.iloc[0] = 500.
        return pd.DataFrame({"equity": equity, "ret": equity.pct_change().fillna(0.),
                             "turnover": 0., "cost_usd": 0.,
                             "position": (np.arange(len(dates)) == 0).astype(float),
                             "cash": np.where(np.arange(len(dates)) == 0, 0., 2.5),
                             "killed": np.arange(len(dates)) > 0}, index=dates)

    monkeypatch.setattr(portfolio, "simulate_funded_portfolio", extreme_loss)
    execution = FakeExecution(tmp_path / "synthetic_result", plan, variants)
    output = research.run_deep(execution, source)
    assert set(execution.states.values()) == {"completed"}
    assert output["live_authorized"] is output["promoted"] is False
    family = output["familywise"]
    assert family["family_size"] == 3 and family["global_p"] == 1.
    assert set(family["by_candidate"]) == {"r0_b4", "r15_b2", "r15_b4"}
    for name, comparison in family["by_candidate"].items():
        assert comparison["p_raw"] == comparison["p_adjusted"] == 1.
        result = output["results"][name]
        primary = result["metrics_by_monthly_cost"]["5.0"]
        assert primary["final_equity"] < 0 and primary["pnl_usd"] < -1000.
        assert primary["compounding_defined"] is False
        assert primary["cagr"] is primary["sharpe"] is primary["worst_month"] is None
        assert result["bootstrap"]["inferentially_valid"] is False
        assert result["bootstrap"]["p_return_better"] == result["bootstrap"]["p_sharpe_better"] == 0.
        assert result["folds"]["complete_years"] == []
        assert result["deflated_sharpe_partial"]["dsr"] is None
        assert result["retrospective_checks"]["chronological_folds"] is False
        assert result["retrospective_checks"]["bootstrap"] is False
        assert result["retrospective_checks"]["multiple_testing"] is False
        assert result["shortlisted_for_research_review"] is False
        assert result["promoted"] is result["eligible_for_new_forward_validation"] is False
        curve = pd.read_csv(execution.directory / f"{name}_expense_5.0.csv")
        assert curve["economic_deficit"].iloc[-1]
        assert pd.isna(curve["ret"].iloc[-1])
        assert curve["equity"].iloc[-1] == pytest.approx(primary["final_equity"])
    assert "n/d" in (execution.directory / "deep_report.md").read_text().lower()
    result_json = json.loads((execution.directory / "deep_results.json").read_text())
    assert result_json == json.loads(json.dumps(output, default=float, allow_nan=False))
