"""Preregistered, funded historical audit. Never changes the operational bot.

The inspected dataset can refute a candidate or justify further investigation;
it cannot establish an unseen winner or authorize live execution.
"""
from __future__ import annotations

import copy
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import sharpe
from .experiments import ExperimentRun, ResearchGateError, canonical_hash, file_hash, variant_id
from .portfolio import PortfolioParams, listed_universe, target_weights

INPUT_HASHES = {
    "crypto_prices.csv": "28d9b9e89e368162c36419acfd4c395cf34b447482b28476ac99ef6bcbdce016",
    "crypto_eligible.csv": "cb079497938df91998f6f95b6b60073de7067aaa4d306b512165911a656bca6b",
    "stocks_prices.csv": "7343358427f3cb3dca8df225058b260f8a032df5068b8de2b2b59a2401fcaa37",
    "stocks_eligible.csv": "82c125d1ff26525fcb9ab860c9bf4234f8d8cca0ba5f0408ff33d05f05aed2d0",
}


def deep_plan():
    """Describe identities without opening market files or computing returns."""
    from .research_multi import BITSO_TRADABLE, SLEEVES

    grid = SLEEVES["deep_crypto"]
    specs = []
    for buffer, band in itertools.product(grid["grid"]["rotation_buffer"], grid["grid"]["band"]):
        name = "control" if buffer == 0 and band == .02 else f"r{int(buffer * 100)}_b{int(band * 100)}"
        specs.append({"name": name, "kind": "tactical", "band": band,
                      "params": PortfolioParams(**grid["fixed"], rotation_buffer=buffer).to_dict()})
    specs += [{"name": "passive_btc_etf", "kind": "passive_reference",
               "crypto": {"BTC": 1.}, "stocks": {"SPY": .6, "IEF": .4}, "kill_dd": None},
              {"name": "cash", "kind": "cash_reference", "annual_interest": 0.}]
    plan = {
        "protocol_version": 1, "profile": "cost-aware-v1", "engine_version": "funded-audit-v1",
        "capital": {"crypto": 500., "stocks": 500.}, "assets": list(BITSO_TRADABLE),
        "evaluation": {"start": "2021-01-01", "end": "2026-09-25",
                       "classification": "retrospective_inspected", "folds": "complete_calendar_years",
                       "selection": "fixed_rules_no_optimizer", "signal_warmup": "all_frozen_prior_rows"},
        "input_sha256": dict(INPUT_HASHES), "specs": specs,
        "execution": {"crypto_cost": .0045, "stocks_cost": .0005,
                      "crypto_min_order_usd": 5., "stocks_min_order_usd": 1.,
                      "stocks_mix": {"SPY": .6, "IEF": .4}, "stocks_band": .05,
                      "crypto_kill_dd": .45, "stocks_kill_dd": .25,
                      "price_model": "previous_close_proxy_after_previous_signal",
                      "cash_model": "sell_first_scale_buys_to_cash_including_cost",
                      "missing_mark": "forward_fill_at_most_5_rows_then_fail_if_held",
                      "missing_execution_price": "no_order", "lot_precision": "fractional_float_proxy",
                      "cross_sleeve_transfers": False},
        "economics": {"monthly_costs_usd": [0., 5., 10., 20.], "primary_monthly_cost": 5.,
                      "expense_model": "daily_calendar_accrual_paid_externally_no_portfolio_withdrawal",
                      "nonpositive_economic_equity": "retain_pnl_compounded_metrics_unavailable",
                      "passive_primary_monthly_cost": 0., "taxes_included": False},
        "inference": {"bootstrap_n": 2000, "block_days": 30, "sensitivity_blocks": [14, 90],
                      "paired_seed": 11, "family_seed": 17, "placebo_n": 199,
                      "placebo_seed": 23, "placebo_min_shift": 60, "placebo_family_adjustment": "holm",
                      "placebo_max_shift_inclusive": "evaluation_rows_minus_min_shift",
                      "placebo_shifted_rows": "decisions_immediately_before_evaluated_returns",
                      "bootstrap_method": "noncircular_moving_blocks_joint_indices_inclusive_last_start",
                      "familywise_method": "centered_max_mean_excess_log_return_including_zero",
                      "undefined_sharpe_policy": "null_metric_failed_comparison_placebo_p_one",
                      "legacy_trials_lower_bound": 97},
        "criteria": {"cagr_improvement_pp": .5, "sharpe_no_worse": True,
                     "drawdown_worse_max_pp": 1., "turnover_reduction_pct": 15.,
                     "complete_years_win_fraction": .6, "bootstrap_superiority_fraction": .8,
                     "familywise_p_lt": .05, "placebo_holm_p_lt": .05,
                     "economic_profit_after_5_positive": True,
                     "stress_costs_per_side": [.006, .01], "stress_primary": .006,
                     "stress_cagr_and_sharpe_no_worse": True,
                     "vs_passive_sharpe_no_worse_after_respective_costs": True},
        "execution_equivalence_diagnostic": {"window_rows": 720, "sample_dates": 24,
                                             "max_abs_weight_difference": .0001,
                                             "reconstruct_window_eligibility_min_history": 250,
                                             "same_positive_members_required": True},
        "data_quality": {"bitso_point_in_time_listing_history": False,
                         "execution_price_and_queue_equivalence": False,
                         "etf_corporate_action_ledger": False,
                         "unseen_holdout": False},
        "promotion": {"automatic": False, "live_authorized": False,
                      "minimum_new_forward_days": 28, "minimum_days_proves_edge": False},
    }
    variants = [{"id": variant_id("deep_total", spec, "frozen_inspected_bitso"),
                 "name": spec["name"], "params": copy.deepcopy(spec), "status": "declared"}
                for spec in specs]
    return plan, variants


def economic_curve(crypto: pd.DataFrame, stocks: pd.DataFrame, monthly_cost: float,
                   start: str, end: str, capital_per_sleeve: float = 500.) -> pd.DataFrame:
    """Add two separately funded sleeves; never erase the first trading cost."""
    if not np.isfinite(monthly_cost) or monthly_cost < 0:
        raise ValueError("invalid monthly expense")
    if not np.isfinite(capital_per_sleeve) or capital_per_sleeve <= 0:
        raise ValueError("invalid initial capital")
    dates = pd.date_range(start, end, freq="D")
    if not len(dates):
        raise ValueError("empty economic window")
    parts = []
    for sleeve in (crypto, stocks):
        if (sleeve.empty or not isinstance(sleeve.index, pd.DatetimeIndex)
                or sleeve.index.hasnans or not sleeve.index.is_unique or not sleeve.index.is_monotonic_increasing):
            raise ValueError("sleeve dates must be unique and sorted")
        if not np.isfinite(sleeve["equity"]).all() or (sleeve["equity"] <= 0).any():
            raise ValueError("invalid source sleeve equity")
        eq = sleeve["equity"].reindex(dates.union(sleeve.index)).sort_index().ffill().reindex(dates)
        # Before the first eligible market close, the sleeve still has initial cash.
        eq.loc[dates < sleeve.index.min()] = capital_per_sleeve
        if eq.isna().any() or not np.isfinite(eq).all() or (eq <= 0).any():
            raise ValueError("incomplete sleeve equity")
        parts.append(eq)
    gross = parts[0] + parts[1]
    accrued = pd.Series(monthly_cost / dates.days_in_month.to_numpy(), index=dates).cumsum()
    net = gross - accrued
    previous = net.shift(1)
    previous.iloc[0] = 2 * capital_per_sleeve
    # External bills may exceed invested capital: preserve the dollar deficit,
    # but do not manufacture compounded returns through nonpositive net wealth.
    returns = (net / previous - 1).where((net > 0) & (previous > 0))
    return pd.DataFrame({"ret": returns, "equity": net, "portfolio_equity": gross,
                         "economic_deficit": net <= 0,
                         "hosting_accrued": accrued, "crypto_equity": parts[0], "stocks_equity": parts[1]})


def holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues, key=pvalues.get)
    maximum = 0.
    out = {}
    for rank, key in enumerate(ordered):
        value = pvalues[key]
        if not np.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("invalid p-value")
        maximum = max(maximum, (len(ordered) - rank) * value)
        out[key] = min(1., maximum)
    return out


def _research_sharpe(returns):
    values = np.asarray(returns, dtype=float)
    if (len(values) < 2 or not np.isfinite(values).all()
            or np.ptp(values) <= 10 * np.finfo(float).eps * max(1., float(np.abs(values).max()))):
        return None
    return sharpe(returns, 365)


def _at_least(left, right):
    return left is not None and right is not None and left >= right


def _metrics(curve, initial=1000.):
    r = curve["ret"]
    wealth = curve["equity"]
    peaks = wealth.cummax().clip(lower=initial)  # Include initial cash in drawdown.
    years = len(r) / 365.
    valid = bool(np.isfinite(r).all() and (wealth > 0).all())
    return {"final_equity": float(curve["equity"].iloc[-1]),
            "pnl_usd": float(curve["equity"].iloc[-1] - initial),
            "compounding_defined": valid,
            "cagr": float((curve["equity"].iloc[-1] / initial) ** (1 / years) - 1) if valid else None,
            "sharpe": _research_sharpe(r) if valid else None,
            "max_dd": float((wealth / peaks - 1).min()),
            "worst_month": float(((1 + r).resample("ME").prod() - 1).min()) if valid else None}


def _load_frozen(execution, directory, plan):
    frames = {}
    for name, expected in plan["input_sha256"].items():
        source = Path(directory) / name
        if not source.is_file() or source.is_symlink() or file_hash(source) != expected:
            raise ResearchGateError(f"entrada congelada ausente o modificada: {name}")
        frame = pd.read_csv(source, index_col=0, parse_dates=True)
        if (not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans
                or not frame.index.is_unique or not frame.index.is_monotonic_increasing
                or not frame.columns.is_unique):
            raise ResearchGateError(f"índice inválido: {name}")
        frames[name] = frame
    for name in ("crypto", "stocks"):
        prices, eligible = frames[f"{name}_prices.csv"], frames[f"{name}_eligible.csv"]
        if not prices.index.equals(eligible.index) or not prices.columns.equals(eligible.columns):
            raise ResearchGateError("precios y elegibilidad no coinciden")
        if not eligible.isin([True, False, 0, 1]).all().all():
            raise ResearchGateError("elegibilidad no booleana")
        frames[f"{name}_eligible.csv"] = eligible.astype(bool)
        execution.freeze_dataset(name, prices, eligible, {
            "source_run": "rotation-v2/20260930T020623Z-3142e39c", "inspected_history": True,
            "input_identity": plan["input_sha256"], **plan["data_quality"]})
    if list(frames["crypto_prices.csv"].columns) != plan["assets"]:
        raise ResearchGateError("universo cripto distinto del preregistrado")
    return frames


def _equivalence(prices, eligible, weights, params, plan):
    """Fixed-date diagnostic; a mismatch remains a blocker, never a tuned window."""
    spec = plan["execution_equivalence_diagnostic"]
    points = np.flatnonzero(prices.index >= plan["evaluation"]["start"])
    selected = np.unique(np.linspace(points[0], points[-1], spec["sample_dates"], dtype=int))
    samples = []
    for end in selected:
        window = slice(max(0, end - spec["window_rows"] + 1), end + 1)
        window_prices = prices.iloc[window]
        window_eligible = listed_universe(window_prices, spec["reconstruct_window_eligibility_min_history"])
        reconstructed = target_weights(window_prices, window_eligible, params,
                                       last_only=True).iloc[-1]
        expected = weights.iloc[end]
        delta = float((reconstructed - expected).abs().max())
        members_equal = bool(((reconstructed > 1e-8) == (expected > 1e-8)).all())
        samples.append({"date": str(prices.index[end].date()), "max_abs_weight_difference": delta,
                        "same_members": members_equal})
    return {"samples": samples, "sampled_dates_pass": all(
        row["same_members"] and row["max_abs_weight_difference"] <= spec["max_abs_weight_difference"]
        for row in samples), "complete_execution_equivalence": False}


def _shift_decisions(weights, eligible, evaluation_positions, shift):
    """Permute exactly the decisions the funded ledger consumes, not the final unused signal."""
    positions = np.asarray(evaluation_positions, dtype=int)
    if not len(positions) or positions[0] < 1:
        raise ResearchGateError("el placebo requiere una decisión anterior a la evaluación")
    decisions = positions - 1
    shifted = weights.copy()
    values = np.roll(weights.iloc[decisions].to_numpy(), int(shift), axis=0)
    shifted.iloc[decisions] = np.where(eligible.iloc[decisions].to_numpy(dtype=bool), values, 0.)
    return shifted


def run_deep(execution: ExperimentRun | None, input_dir: Path):
    """Only market entry point: requires the existing committed preregistration gate."""
    from .portfolio import simulate_funded_portfolio
    from .research_statistics import paired_block_evidence, familywise_block_test, chronological_folds
    from .validation import deflated_sharpe, finite_randomization_pvalue

    plan, variants = deep_plan()
    if (execution is None or execution.config_hash != canonical_hash(plan)
            or canonical_hash(execution.manifest["config"]) != canonical_hash(plan)
            or set(execution.variants) != {v["id"] for v in variants}):
        raise ResearchGateError("la investigación profunda necesita su ejecución preregistrada exacta")
    frames = _load_frozen(execution, input_dir, plan)
    start, end = plan["evaluation"]["start"], plan["evaluation"]["end"]
    P = frames["crypto_prices.csv"].loc[:end]
    E = frames["crypto_eligible.csv"].loc[:end]
    S = frames["stocks_prices.csv"].loc[:end, ["SPY", "IEF"]]
    cfg, inference = plan["execution"], plan["inference"]
    stock_params = PortfolioParams(dd_brake=False, regime_asset=None, ann=252)
    stock_weights = pd.DataFrame(cfg["stocks_mix"], index=S.index)
    stocks = simulate_funded_portfolio(S, stock_weights, stock_params,
        cost=cfg["stocks_cost"], band=cfg["stocks_band"], kill_dd=cfg["stocks_kill_dd"],
        initial_capital=500., min_order_value=1., start=start)
    cached_weights, runs, results = {}, {}, {}

    def crypto_run(weights, params, band, cost, kill=cfg["crypto_kill_dd"]):
        return simulate_funded_portfolio(P, weights, params, cost=cost, band=band, kill_dd=kill,
                                        initial_capital=500., min_order_value=5., start=start)

    for variant in variants:
        execution.variant(variant["id"], "started")
        spec = variant["params"]
        name = spec["name"]
        try:
            if spec["kind"] == "tactical":
                params = PortfolioParams.from_dict(spec["params"])
                key = canonical_hash(spec["params"])
                if key not in cached_weights:
                    cached_weights[key] = target_weights(P, E, params)
                W = cached_weights[key]
                bt = crypto_run(W, params, spec["band"], cfg["crypto_cost"])
                stock_bt = stocks
            elif spec["kind"] == "passive_reference":
                params = PortfolioParams(dd_brake=False, regime_asset=None)
                W = pd.DataFrame(0., index=P.index, columns=P.columns)
                W["BTC"] = 1.
                bt = crypto_run(W, params, 0., cfg["crypto_cost"], kill=None)
                stock_bt = simulate_funded_portfolio(S, stock_weights, stock_params,
                    cost=cfg["stocks_cost"], band=cfg["stocks_band"], kill_dd=None,
                    initial_capital=500., min_order_value=1., start=start)
            else:
                dates = pd.date_range(start, end)
                bt = pd.DataFrame({"equity": 500., "ret": 0., "turnover": 0., "cost_usd": 0.,
                                   "position": 0., "cash": 500., "killed": False}, index=dates)
                stock_bt, W, params = bt, None, None
            economics = {str(cost): economic_curve(bt, stock_bt, cost, start, end)
                         for cost in plan["economics"]["monthly_costs_usd"]}
            runs[name] = {"crypto": bt, "stocks": stock_bt, "weights": W, "params": params,
                          "economics": economics, "spec": spec}
            results[name] = {"variant_id": variant["id"], "spec": spec,
                "metrics_by_monthly_cost": {cost: _metrics(curve) for cost, curve in economics.items()},
                "crypto_turnover": float(bt["turnover"].sum()),
                "trading_cost_usd": float(bt["cost_usd"].sum() + stock_bt["cost_usd"].sum()),
                "crypto_killed": bool(bt["killed"].iloc[-1]),
                "minimum_cash_usd": float(min(bt["cash"].min(), stock_bt["cash"].min())),
                "max_crypto_exposure": float(bt["position"].max())}
            bt.to_csv(execution.directory / f"{name}_crypto.csv", index_label="date")
            for cost, curve in economics.items():
                curve.to_csv(execution.directory / f"{name}_expense_{cost}.csv", index_label="date")
            if spec["kind"] == "tactical":
                results[name]["window_equivalence"] = _equivalence(P, E, W, params, plan)
        except BaseException:
            execution.variant(variant["id"], "failed")
            raise
        execution.variant(variant["id"], "completed")
        print(f"Variante registrada: {name}", flush=True)

    names = [s["name"] for s in plan["specs"] if s["kind"] == "tactical"]
    challengers = [name for name in names if name != "control"]
    returns = pd.DataFrame({name: runs[name]["economics"]["5.0"]["ret"] for name in names})
    valid_paths = {name: bool(np.isfinite(returns[name]).all()) for name in names}

    def family_test(block):
        if all(valid_paths.values()):
            return familywise_block_test(returns[challengers], returns["control"],
                n=inference["bootstrap_n"], block=block, seed=inference["family_seed"])
        # Never drop a bankrupt challenger and silently shrink the declared family.
        return {"method": "unavailable_nonpositive_economic_equity", "block_length": block,
                "family_size": len(challengers), "global_p": 1.,
                "unavailable_curves": [name for name in names if not valid_paths[name]],
                "by_candidate": {name: {"observed_mean_log_excess": None, "p_raw": 1.,
                    "p_adjusted": 1., "degenerate": True} for name in challengers},
                "limitations": ["Family retained in full; undefined compounded returns cannot establish superiority."]}

    family = family_test(inference["block_days"])
    sensitivities = {str(block): family_test(block) for block in inference["sensitivity_blocks"]}
    daily_srs = [float(returns[name].mean() / returns[name].std(ddof=1))
                 if valid_paths[name] and returns[name].std(ddof=1) > 0 else 0. for name in names]
    for name in challengers:
        result = results[name]
        if valid_paths[name] and valid_paths["control"]:
            result["bootstrap"] = paired_block_evidence(returns[name], returns["control"],
                n=inference["bootstrap_n"], block=inference["block_days"], seed=inference["paired_seed"])
            result["folds"] = chronological_folds(returns[name], returns["control"], first_year=2021)
        else:
            result["bootstrap"] = {"method": "unavailable_nonpositive_economic_equity",
                "inferentially_valid": False, "degenerate": True, "p_return_better": 0.,
                "p_sharpe_better": 0., "delta_log_wealth_ci95": None, "delta_sharpe_ci95": None}
            result["folds"] = {"method": "unavailable_nonpositive_economic_equity",
                "complete_years": [], "folds": [], "wins": 0, "win_fraction": None,
                "portfolio_reset": False, "selection_performed": False}
        result["familywise"] = family["by_candidate"][name]
        result["deflated_sharpe_partial"] = (deflated_sharpe(returns[name], daily_srs,
            ann=365, extra_trials=inference["legacy_trials_lower_bound"]) if all(valid_paths.values())
            and _research_sharpe(returns[name]) is not None else {
                "n_trials": len(names) + inference["legacy_trials_lower_bound"], "sr0_annual": None, "dsr": None})
        for key, value in result["deflated_sharpe_partial"].items():
            if isinstance(value, (float, np.floating)) and not np.isfinite(value):
                result["deflated_sharpe_partial"][key] = None
        result["deflated_sharpe_partial"]["defined"] = result["deflated_sharpe_partial"]["dsr"] is not None
        result["deflated_sharpe_partial"]["historical_search_fully_reconstructed"] = False
        result["stress"] = {}
    for cost in plan["criteria"]["stress_costs_per_side"]:
        for name in names:
            row = runs[name]
            stressed = crypto_run(row["weights"], row["params"], row["spec"]["band"], cost)
            curve = economic_curve(stressed, stocks, 5., start, end)
            results[name].setdefault("stress", {})[str(cost)] = _metrics(curve)
    print("Inferencia por bloques y escenarios de costos completados.", flush=True)

    # Re-run funded ledgers with both candidate and control signals shifted alike.
    # Current eligibility masks apply after shifting. This does not preserve turnover.
    positions = np.flatnonzero(P.index >= start)
    rng = np.random.default_rng(inference["placebo_seed"])
    shifts = rng.integers(inference["placebo_min_shift"],
                         len(positions) - inference["placebo_min_shift"] + 1, inference["placebo_n"])
    samples = {name: [] for name in challengers}
    for iteration, shift in enumerate(shifts):
        scores = {}
        for name in names:
            row = runs[name]
            shifted = _shift_decisions(row["weights"], E, positions, shift)
            bt = crypto_run(shifted, row["params"], row["spec"]["band"], cfg["crypto_cost"])
            scores[name] = _research_sharpe(economic_curve(bt, stocks, 5., start, end)["ret"])
        for name in challengers:
            samples[name].append(scores[name] - scores["control"]
                                 if scores[name] is not None and scores["control"] is not None else None)
        if (iteration + 1) % 20 == 0:
            print(f"Placebo incremental {iteration + 1}/{len(shifts)}", flush=True)
    observed_srs = {name: _research_sharpe(returns[name]) for name in names}
    observed_deltas = {name: observed_srs[name] - observed_srs["control"]
                       if observed_srs[name] is not None and observed_srs["control"] is not None else None
                       for name in challengers}
    raw_p = {name: finite_randomization_pvalue(observed_deltas[name], samples[name])
             if observed_deltas[name] is not None and all(value is not None for value in samples[name])
             else 1. for name in challengers}
    adjusted = holm_adjust(raw_p)
    pd.DataFrame({"shift_days": shifts, **samples}).to_csv(execution.directory / "placebo_samples.csv", index=False)
    criteria = plan["criteria"]
    control_metrics = results["control"]["metrics_by_monthly_cost"]["5.0"]
    passive_metrics = results["passive_btc_etf"]["metrics_by_monthly_cost"]["0.0"]
    for name in challengers:
        result = results[name]
        result["placebo"] = {"p_raw": raw_p[name], "p_holm": adjusted[name], "n": len(shifts),
                             "observed_delta_sharpe": observed_deltas[name],
                             "all_statistics_defined": observed_deltas[name] is not None and all(
                                 value is not None for value in samples[name]),
                             "null": "common_circular_shift_signals_reexecute_funded_ledger"}
        metric = result["metrics_by_monthly_cost"]["5.0"]
        boot, folds = result["bootstrap"], result["folds"]
        stress = result["stress"][str(criteria["stress_primary"])]
        stress_control = results["control"]["stress"][str(criteria["stress_primary"]) ]
        checks = {
            "economic_profit": metric["pnl_usd"] > 0,
            "cagr": _at_least(metric["cagr"], control_metrics["cagr"] + criteria["cagr_improvement_pp"] / 100
                              if control_metrics["cagr"] is not None else None),
            "sharpe": _at_least(metric["sharpe"], control_metrics["sharpe"]),
            "drawdown": metric["max_dd"] >= control_metrics["max_dd"] - criteria["drawdown_worse_max_pp"] / 100,
            "turnover": results["control"]["crypto_turnover"] > 0 and result["crypto_turnover"] <=
                results["control"]["crypto_turnover"] * (1 - criteria["turnover_reduction_pct"] / 100),
            "chronological_folds": bool(folds["complete_years"]) and folds["wins"] >=
                math.ceil(criteria["complete_years_win_fraction"] * len(folds["complete_years"])),
            "bootstrap": boot["inferentially_valid"] and boot["p_return_better"] >= criteria["bootstrap_superiority_fraction"] and
                boot["p_sharpe_better"] >= criteria["bootstrap_superiority_fraction"],
            "multiple_testing": result["familywise"]["p_adjusted"] < criteria["familywise_p_lt"],
            "incremental_placebo": adjusted[name] < criteria["placebo_holm_p_lt"],
            "stress": _at_least(stress["cagr"], stress_control["cagr"]) and _at_least(stress["sharpe"], stress_control["sharpe"]),
            "simple_reference_sharpe": _at_least(metric["sharpe"], passive_metrics["sharpe"]),
        }
        result["retrospective_checks"] = checks
        result["shortlisted_for_research_review"] = all(checks.values())
        result["eligible_for_new_forward_validation"] = False
        result["promoted"] = False
    output = {"plan_sha256": canonical_hash(plan), "classification": "retrospective_inspected",
              "results": results, "familywise": family, "block_sensitivities": sensitivities,
              "data_quality": plan["data_quality"], "live_authorized": False, "promoted": False,
              "verdict": "No hay ganadora validada: histórico inspeccionado y equivalencia pendiente.",
              "limitations": ["Folds cronológicos de reglas fijas; no se optimizan parámetros ni se afirma holdout virgen.",
                 "Precios de cierre proxy, mínimos genéricos y fricción constante; no equivalen a fills Bitso/Alpaca.",
                 "ETF usa precios ajustados; no un ledger corporativo con dividendos y splits.",
                 "Gastos externos pueden superar el capital; se conserva la pérdida USD y se omiten métricas compuestas indefinidas.",
                 "Bootstrap/DSR no reconstruyen todas las decisiones históricas de investigación.",
                 "La ventana móvil se audita en fechas prefijadas; no se modifica el selector congelado.",
                 "La observación mínima de 28 días prueba continuidad, no garantiza rentabilidad."]}
    (execution.directory / "deep_results.json").write_text(json.dumps(output, indent=2, default=float,
                                                                       ensure_ascii=False, allow_nan=False) + "\n")
    lines = ["# Investigación de costos con US$1,000", "", output["verdict"], "",
             "| Regla | Saldo cartera USD | Resultado después de US$5/mes | CAGR económico | Caída económica |",
             "|---|---:|---:|---:|---:|"]
    for name, result in results.items():
        zero, cost = result["metrics_by_monthly_cost"]["0.0"], result["metrics_by_monthly_cost"]["5.0"]
        cagr = f"{cost['cagr']:.2%}" if cost["cagr"] is not None else "n/d"
        lines.append(f"| {name} | {zero['final_equity']:.2f} | {cost['pnl_usd']:.2f} | {cagr} | {cost['max_dd']:.2%} |")
    lines += ["", "Referencias pasivas también se evalúan sin hosting; los controles automatizados usan US$5/mes.",
              "La tabla no ordena ni selecciona una ganadora. Todos los checks están en deep_results.json.", ""]
    lines += [f"- {text}" for text in output["limitations"]]
    (execution.directory / "deep_report.md").write_text("\n".join(lines) + "\n")
    return output
