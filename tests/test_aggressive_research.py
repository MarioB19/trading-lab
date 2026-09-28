"""Integridad offline: precios sintéticos, sin seleccionar variantes de mercado."""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

from lab import aggressive_research as research
from lab.aggressive_plan import comparison_plan
from lab.experiments import ResearchGateError
from lab.portfolio import PortfolioParams, listed_universe, target_weights


def _synthetic_plan():
    plan, _ = comparison_plan()
    plan["evaluation"].update(start="2020-01-01", end="2023-03-01", history_start="2019-01-01")
    plan["criteria"].update(bootstrap_n=20, placebo_n=3)
    return plan


def _panels(plan):
    ev = plan["evaluation"]
    idx = pd.date_range(ev["history_start"], ev["end"])
    assets = plan["portfolios"]["control"]["crypto"]["universe"]
    rng = np.random.default_rng(71)
    crypto = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.0002, .015, (len(idx), len(assets))), axis=0)),
                          columns=assets, index=idx)
    sessions = pd.bdate_range(ev["history_start"], ev["end"])
    stocks = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.0001, .003, (len(sessions), 2)), axis=0)),
                          columns=["SPY", "IEF"], index=sessions)
    return crypto, listed_universe(crypto), stocks


def _constant_targets(prices, eligible, params):
    weights = pd.DataFrame(0., index=prices.index, columns=prices.columns)
    weights.iloc[:, :params.top_k] = 1 / params.top_k
    return weights.where(eligible, 0)


def test_describe_is_offline_and_declares_exactly_two_variants(monkeypatch, capsys):
    monkeypatch.setattr(research, "load_sleeve", lambda *a, **kw: pytest.fail("no cargar datos"))
    monkeypatch.setattr(research, "ExperimentRun", lambda *a, **kw: pytest.fail("no iniciar investigación"))
    research.main(["--describe"])
    data = json.loads(capsys.readouterr().out)
    assert data["executed"] is False and data["live_authorized"] is False
    assert {v["role"] for v in data["variants"]} == {"control", "aggressive"}
    assert all(v["status"] == "declared" for v in data["variants"])
    assert data["plan"]["portfolios"]["control"]["stocks"] == data["plan"]["portfolios"]["aggressive"]["stocks"]


def test_preregistration_gate_precedes_data_or_calculation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(research, "assert_current_control", lambda plan: calls.append("control"))
    def gate(*args, **kwargs):
        calls.append("gate")
        raise ResearchGateError("synthetic gate rejected")
    monkeypatch.setattr(research, "ExperimentRun", gate)
    monkeypatch.setattr(research, "load_sleeve", lambda *a, **kw: pytest.fail("datos antes del gate"))
    monkeypatch.setattr(research, "target_weights", lambda *a, **kw: pytest.fail("cálculo antes del gate"))
    with pytest.raises(ResearchGateError, match="preregistration-commit"):
        research.run()
    assert calls == []
    with pytest.raises(ResearchGateError, match="synthetic gate rejected"):
        research.run("a" * 40, tmp_path / "results", tmp_path / "ledger/events.jsonl")
    assert calls == ["control", "gate"]


def test_grid_membership_gate_runs_before_describe_or_execution(monkeypatch, tmp_path):
    def reject(plan):
        raise ResearchGateError("variante no registrada")
    monkeypatch.setattr(research, "validate_registered_variants", reject)
    monkeypatch.setattr(research, "load_sleeve", lambda *a, **kw: pytest.fail("no cargar datos"))
    monkeypatch.setattr(research, "ExperimentRun", lambda *a, **kw: pytest.fail("no iniciar corrida"))
    with pytest.raises(ResearchGateError, match="no registrada"):
        research.main(["--describe"])
    with pytest.raises(ResearchGateError, match="no registrada"):
        research.run("a" * 40, tmp_path / "results")


@pytest.mark.parametrize("protected", ["state", "data", "src", "configs", ".git", "infra"])
def test_output_and_ledger_cannot_touch_operational_paths(tmp_path, protected):
    with pytest.raises(ResearchGateError):
        research._destinations(research.ROOT / protected / "experiment", tmp_path / "ledger/events.jsonl")
    with pytest.raises(ResearchGateError):
        research._destinations(tmp_path / "results", research.ROOT / protected / "events.jsonl")


def test_output_ledger_symlink_to_state_is_rejected(tmp_path):
    link = tmp_path / "shortcut"
    link.symlink_to(research.ROOT / "state", target_is_directory=True)
    with pytest.raises(ResearchGateError):
        research._destinations(tmp_path / "results", link / "events.jsonl")


def test_entry_cost_and_initial_drawdown_are_counted_without_warmup_trades():
    idx = pd.date_range("2019-12-01", "2020-01-03")
    prices = pd.DataFrame(100., index=idx, columns=["A"])
    weights = pd.DataFrame(1., index=idx, columns=["A"])
    bt = research.evaluation_simulation(prices, weights, PortfolioParams(dd_brake=False),
                                        {"band": 0., "kill_drawdown": .45, "capital": 500.},
                                        "2020-01-01", "2020-01-03", .0045)
    assert list(bt.index) == list(pd.date_range("2020-01-01", "2020-01-03"))
    assert bt["cost_usd"].sum() == pytest.approx(2.25)
    assert bt["turnover_usd"].sum() == 500
    assert bt["equity_usd"].iloc[-1] == pytest.approx(497.75)
    assert bt["drawdown"].min() == pytest.approx(-.0045)
    assert research.curve_metrics(bt, 500, 365)["max_dd"] == pytest.approx(-.0045)


def test_kill_persists_across_year_without_capital_reset():
    idx = pd.date_range("2020-12-29", "2021-01-04")
    prices = pd.DataFrame({"A": [100, 100, 50, 50, 90, 200, 300]}, index=idx)
    weights = pd.DataFrame(1., index=idx, columns=["A"])
    bt = research.evaluation_simulation(prices, weights, PortfolioParams(dd_brake=False),
                                        {"band": 0., "kill_drawdown": .45, "capital": 500.},
                                        "2020-12-30", "2021-01-04", 0.)
    assert bt.loc["2020-12-31", "equity_usd"] == 250
    assert (bt.loc["2021-01-01":, "equity_usd"] == 250).all()
    assert (bt.loc["2021-01-01":, "position"] == 0).all()
    assert (bt.loc["2021-01-01":, "brake"] == 0).all()


def test_annual_windows_exclude_partial_year_and_need_complete_coverage():
    idx = pd.date_range("2020-01-01", "2023-06-01")
    control, aggressive = pd.Series(0., index=idx), pd.Series(.0001, index=idx)
    result = research.annual_windows(control, aggressive, "2020-01-01", "2023-06-01", 3, .5)
    assert result["complete_years"] == 3 and result["passed"]
    assert not result["windows"][-1]["complete"]
    assert result["capital_reset_each_year"] is False and result["unseen_holdout"] is False
    incomplete = control.drop(pd.Timestamp("2021-04-01"))
    result = research.annual_windows(incomplete, aggressive.reindex(incomplete.index),
                                     "2020-01-01", "2023-06-01", 3, .5)
    assert result["complete_years"] == 2 and not result["passed"]


def test_combine_adds_independent_equity_with_weekends_not_daily_rebalancing():
    idx = pd.date_range("2021-01-01", "2021-01-04")
    crypto = pd.DataFrame({"equity_usd": [600, 720, 864, 1036.8], "cost_usd": 0.,
                           "turnover_usd": 0.}, index=idx)
    stocks = pd.DataFrame({"equity_usd": [450, 405], "cost_usd": [1, 2],
                           "turnover_usd": [10, 20]}, index=idx[[0, 3]])
    total = research.combine_sleeves(crypto, stocks, 500, 500)
    np.testing.assert_allclose(total["equity_usd"], [1050, 1170, 1314, 1441.8])
    assert total["ret"].iloc[0] == pytest.approx(.05)
    assert total["cost_usd"].tolist() == [1, 0, 0, 2]
    assert (1 + total["ret"]).prod() == pytest.approx(1.4418)


def test_paired_bootstrap_uses_same_days_is_reproducible_and_rejects_misalignment():
    idx = pd.date_range("2020-01-01", periods=400)
    control = pd.Series(np.random.default_rng(21).normal(.0001, .01, len(idx)), index=idx)
    result, draws = research.paired_bootstrap(control, control, 40, 30, 11)
    assert result["valid"] and result["p_return_better"] == result["p_sharpe_better"] == 0
    assert (draws == 0).all().all()
    first, samples = research.paired_bootstrap(control + .001, control, 40, 30, 11)
    second, repeat = research.paired_bootstrap(control + .001, control, 40, 30, 11)
    assert first == second and first["p_return_better"] == first["p_sharpe_better"] == 1
    pd.testing.assert_frame_equal(samples, repeat)
    with pytest.raises(ResearchGateError, match="alineadas"):
        research.paired_bootstrap(control.iloc[1:], control.iloc[:-1], 40, 30, 11)
    flat, _ = research.paired_bootstrap(control * 0, control * 0, 10, 30, 11)
    assert not flat["valid"] and flat["p_sharpe_better"] is None


def test_placebo_finite_p_and_same_kill_band_cost(monkeypatch):
    plan = _synthetic_plan()
    crypto, _, _ = _panels(plan)
    weights = pd.DataFrame(0., index=crypto.index, columns=crypto.columns)
    seen = []
    def simulation(prices, shifted, params, sleeve, start, end, cost):
        seen.append((sleeve["kill_drawdown"], sleeve["band"], cost, prices.index[0], start))
        return pd.DataFrame({"ret": [0., 0.]})
    monkeypatch.setattr(research, "evaluation_simulation", simulation)
    cfg = plan["portfolios"]["aggressive"]["crypto"]
    result, draws = research.timing_placebo(crypto, weights, PortfolioParams.from_dict(cfg["params"]), cfg, plan, 5.)
    assert result["p_value"] == pytest.approx(1 / (plan["criteria"]["placebo_n"] + 1))
    assert len(draws) == len(seen) == plan["criteria"]["placebo_n"]
    assert all(row[:3] == (.45, .02, .0045) for row in seen)
    assert all(row[3] == pd.Timestamp("2019-12-31") for row in seen)
    assert result["scope"] == "aggressive_timing_only_not_incremental_superiority"


def test_stress_gate_uses_both_metrics_and_one_percent_is_only_informative():
    plan = _synthetic_plan()
    control = {"cagr": .10, "sharpe": 1., "max_dd": -.2}
    aggressive = {"cagr": .15, "sharpe": 1.1, "max_dd": -.24}
    metrics = {cost: {"control": {"crypto": control.copy()}, "aggressive": {"crypto": aggressive.copy()}}
               for cost in ("0.0045", "0.0060", "0.0100")}
    metrics["0.0100"]["aggressive"]["crypto"].update(cagr=-.9, sharpe=-10.)
    boot = {"valid": True, "p_return_better": .8, "p_sharpe_better": .8}
    def checks():
        return research.comparison_checks(plan, metrics, {"passed": True}, boot, {"passed": True})
    assert all(checks().values())
    metrics["0.0045"]["aggressive"]["crypto"]["cagr"] = .12
    assert not checks()["cagr"] and not checks()["walk_forward"]
    assert all(value for key, value in checks().items() if key not in {"cagr", "walk_forward"})
    metrics["0.0045"]["aggressive"]["crypto"].update(cagr=.15, sharpe=.9)
    assert not checks()["sharpe"] and not checks()["walk_forward"]
    metrics["0.0045"]["aggressive"]["crypto"]["sharpe"] = 1.1
    metrics["0.0060"]["aggressive"]["crypto"]["sharpe"] = .9
    assert not checks()["cost_stress"]
    metrics["0.0060"]["aggressive"]["crypto"].update(sharpe=1.1, cagr=.09)
    assert not checks()["cost_stress"]
    metrics["0.0045"]["aggressive"]["crypto"]["max_dd"] = -.26
    assert not checks()["drawdown"]


@pytest.mark.parametrize("role", ["control", "aggressive"])
def test_actual_signal_and_simulation_prefix_invariance(role):
    plan, _ = comparison_plan()
    cfg = plan["portfolios"][role]["crypto"]
    params = PortfolioParams.from_dict(cfg["params"])
    idx = pd.date_range("2019-01-01", periods=460)
    rng = np.random.default_rng(42)
    prices = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(.002, .018, (len(idx), 3)), axis=0)),
                          index=idx, columns=["BTC", "ETH", "SOL"])
    cutoff = idx[410]
    full = target_weights(prices, listed_universe(prices), params)
    truncated = prices.loc[:cutoff]
    prefix = target_weights(truncated, listed_universe(truncated), params)
    pd.testing.assert_frame_equal(full.loc[:cutoff], prefix)
    bt = research.evaluation_simulation(prices, full, params, cfg, "2020-01-01", str(idx[-1].date()), .0045)
    old = research.evaluation_simulation(truncated, prefix, params, cfg, "2020-01-01", str(cutoff.date()), .0045)
    pd.testing.assert_frame_equal(bt.loc[:cutoff], old)
    assert old["turnover"].sum() > 0


def test_missing_declared_asset_or_missing_day_prevents_result():
    plan = _synthetic_plan()
    crypto, eligible, stocks = _panels(plan)
    missing = crypto.copy()
    missing["SOL"] = np.nan
    assert research.availability(missing, "crypto")["missing_assets"] == ["SOL"]
    with pytest.raises(ResearchGateError, match="faltan activos"):
        research.validate_panels(plan, missing, eligible, stocks)
    crypto = crypto.drop(pd.Timestamp("2021-01-01"))
    with pytest.raises(ResearchGateError, match="faltan fechas"):
        research.validate_panels(plan, crypto, eligible.reindex_like(crypto), stocks)


@pytest.mark.parametrize("gap_date", ["2019-12-15", "2019-12-31", "2020-01-02"])
def test_single_missing_close_cannot_hide_a_loss_by_selling_at_imputed_price(monkeypatch, gap_date):
    plan = _synthetic_plan()
    crypto, _, stocks = _panels(plan)
    gap = pd.Timestamp(gap_date)
    dates = pd.date_range(gap - pd.Timedelta(days=1), periods=3)
    crypto.loc[dates, "BTC"] = [100., np.nan, 50.]
    # Con pesos [1, 0, 0], el ffill del motor podría liquidar a 100 antes de
    # aplicar el retorno de 50. El comparador debe rechazar datos antes del motor.
    weights = pd.DataFrame(0., index=crypto.index, columns=crypto.columns)
    weights.loc[dates[0], "BTC"] = 1.
    monkeypatch.setattr(research, "target_weights", lambda *a, **kw: weights)
    monkeypatch.setattr(research, "evaluation_simulation", lambda *a, **kw: pytest.fail("no simular huecos"))
    with pytest.raises(ResearchGateError, match=f"crypto/BTC: cierre ausente en {gap_date}.*no ejecutada"):
        research.compare_panels(plan, crypto, listed_universe(crypto), stocks)


def test_missing_prices_before_first_observation_remain_allowed():
    plan = _synthetic_plan()
    crypto, _, stocks = _panels(plan)
    crypto.loc[:"2020-03-31", "SOL"] = np.nan
    eligible = listed_universe(crypto)
    research.validate_panels(plan, crypto, eligible, stocks)
    assert not eligible.loc[:"2020-03-31", "SOL"].any()
    assert research.availability(crypto, "crypto")["pre_first_observation_missing_allowed"] is True


def test_full_comparator_keeps_identical_passive_stocks_and_emits_all_curves(monkeypatch):
    plan = _synthetic_plan()
    crypto, eligible, stocks = _panels(plan)
    monkeypatch.setattr(research, "target_weights", _constant_targets)
    calls = []
    original = research.evaluation_simulation
    def simulation(prices, weights, params, cfg, start, end, cost):
        if "SPY" in prices:
            calls.append((params.dd_brake, cfg["kill_drawdown"], weights.iloc[-1].to_dict()))
        return original(prices, weights, params, cfg, start, end, cost)
    monkeypatch.setattr(research, "evaluation_simulation", simulation)
    events = []
    result, curves = research.compare_panels(plan, crypto, eligible, stocks,
                                             lambda role, status: events.append((role, status)))
    assert calls == [(False, .25, {"SPY": .6, "IEF": .4})]
    assert events == [("control", "started"), ("control", "completed"),
                      ("aggressive", "started"), ("aggressive", "completed")]
    pd.testing.assert_frame_equal(curves["control_stocks"], curves["aggressive_stocks"])
    assert len(curves) == 16
    assert result["annual_fixed_windows"]["complete_years"] == 3
    assert result["live_authorized"] is False and result["ready_for_promotion"] is False
    assert result["dsr"]["global_historical_trial_count"] is None
    assert result["causality"]["verified_automatically_by_this_run"] is False
    json.dumps(result, allow_nan=False)
    assert "1% es informativo" in research.report_markdown(result)


@pytest.mark.parametrize("should_fail", [False, True])
def test_run_records_frozen_inputs_variant_events_and_artifacts(monkeypatch, tmp_path, should_fail):
    plan = _synthetic_plan()
    _, variants = comparison_plan()
    crypto, eligible, stocks = _panels(plan)
    monkeypatch.setattr(research, "comparison_plan", lambda: (copy.deepcopy(plan), copy.deepcopy(variants)))
    monkeypatch.setattr(research, "assert_current_control", lambda _: None)
    observed = []
    class Context:
        def __init__(self, root, identity, prereg, commit, config, variants, output, ledger):
            observed.append("gate")
            self.directory = output / "synthetic-run"
            self.directory.mkdir(parents=True)
            self.variant_states = {v["id"]: "declared" for v in variants}
            self.run_id, self.proof = "synthetic", {"code_commit": "b" * 40}
        def freeze_dataset(self, name, prices, elig, provenance):
            observed.append(f"frozen:{name}")
        def variant(self, identity, state):
            self.variant_states[identity] = state
            observed.append(state)
        def event(self, *a, **kw):
            observed.append("evaluated")
        def finish(self, state):
            if state == "completed":
                assert set(self.variant_states.values()) == {"completed"}
            observed.append(f"finish:{state}")
    monkeypatch.setattr(research, "ExperimentRun", Context)
    def load(name, **kwargs):
        assert observed[0] == "gate"
        return (crypto, eligible) if name == "crypto" else (stocks, listed_universe(stocks))
    monkeypatch.setattr(research, "load_sleeve", load)
    real_compare = research.compare_panels
    monkeypatch.setattr(research, "target_weights", _constant_targets)
    def compare(plan, crypto, eligible, stocks, variant_event):
        assert observed[:3] == ["gate", "frozen:crypto", "frozen:stocks"]
        if not should_fail:
            return real_compare(plan, crypto, eligible, stocks, variant_event)
        variant_event("control", "started")
        raise ResearchGateError("falta un dato sintético")
    monkeypatch.setattr(research, "compare_panels", compare)
    if not should_fail:
        directory = research.run("a" * 40, tmp_path / "output")
        assert observed[-2:] == ["evaluated", "finish:completed"]
        result = json.loads((directory / "comparison.json").read_text())
        assert result["run_id"] == "synthetic" and result["code_commit"] == "b" * 40
        assert (directory / "comparison.md").is_file()
        assert len(list((directory / "curves").glob("*.csv"))) == 16
        assert not (directory / "failure.json").exists()
        return
    with pytest.raises(ResearchGateError, match="sintético"):
        research.run("a" * 40, tmp_path / "output")
    assert observed[-3:] == ["started", "failed", "finish:failed"]
    failure = json.loads((tmp_path / "output/synthetic-run/failure.json").read_text())
    assert failure["live_authorized"] is False and "sintético" in failure["message"]
    assert not (tmp_path / "output/synthetic-run/comparison.json").exists()
