"""Pure evidence helpers for preregistered, daily research curves.

No data access, strategy selection or trading occurs here. Bootstrap samples
resample realized return paths; they do not rerun signals or risk controls.
Annualized Sharpe uses 365 daily periods and the sample standard deviation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .validation import _block_indices, finite_randomization_pvalue

ANNUALIZATION = 365
LIMITATIONS = [
    "Inspected historical data do not become an unseen holdout through resampling.",
    "Block inference assumes temporal dependence is adequately represented by the declared block length.",
    "Return resampling does not rerun signals, execution or path-dependent risk controls.",
    "Resampling frequencies are not probabilities of future profits.",
]


def _returns(value: pd.Series, label: str) -> np.ndarray:
    if not isinstance(value, pd.Series):
        raise ValueError(f"{label} must be a pandas Series")
    if len(value) < 2 or not value.index.is_unique or not value.index.is_monotonic_increasing:
        raise ValueError(f"{label} needs at least two uniquely indexed, ordered returns")
    if value.index.hasnans or pd.api.types.is_bool_dtype(value.dtype):
        raise ValueError(f"{label} has invalid index labels or boolean returns")
    try:
        array = value.to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain numeric returns") from exc
    if not np.isfinite(array).all() or (array <= -1).any():
        raise ValueError(f"{label} requires finite returns strictly greater than -1")
    return array


def _pair(candidate: pd.Series, control: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    a, b = _returns(candidate, "candidate"), _returns(control, "control")
    if not candidate.index.equals(control.index):
        raise ValueError("candidate and control must have exactly aligned indices")
    return a, b


def _resampling(n: int, block: int, length: int) -> None:
    for label, value in (("n", n), ("block", block)):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 1:
            raise ValueError(f"{label} must be a positive integer")
    if block > length:
        raise ValueError("block cannot exceed the observed sample length")


def _constant(values: np.ndarray) -> bool:
    # Roundoff in log subtraction must not manufacture variation in a null curve.
    tolerance = 10 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(values))))
    return bool(np.ptp(values) <= tolerance)


def _sharpe(values: np.ndarray) -> float | None:
    if len(values) < 2 or _constant(values):
        return None  # A zero-volatility sample is not an infinite observed edge.
    scaled = values / np.max(np.abs(values))
    return float(scaled.mean() / scaled.std(ddof=1) * np.sqrt(ANNUALIZATION))


def _delta_sharpe(a: np.ndarray, b: np.ndarray) -> float | None:
    left, right = _sharpe(a), _sharpe(b)
    return left - right if left is not None and right is not None else None


def paired_block_evidence(candidate: pd.Series, control: pd.Series, n: int = 2000,
                          block: int = 30, seed: int = 11) -> dict:
    """Paired moving-block percentile evidence, not a null-hypothesis p-value.

    CI endpoints are the 2.5/97.5 percentiles (NumPy linear interpolation).
    delta_log_wealth is the sum of log-return differences over the full sample.
    Undefined Sharpe resamples count as no superiority; their CI is unavailable.
    """
    a, b = _pair(candidate, control)
    _resampling(n, block, len(a))
    rng = np.random.default_rng(seed)
    log_differences = np.log1p(a) - np.log1p(b)
    log_samples = np.empty(n)
    sharpe_samples = np.full(n, np.nan)
    for i in range(n):
        indices = _block_indices(len(a), len(a), block, rng)
        log_samples[i] = log_differences[indices].sum()
        difference = _delta_sharpe(a[indices], b[indices])
        if difference is not None:
            sharpe_samples[i] = difference
    valid_sharpe = np.isfinite(sharpe_samples)
    degenerate = _constant(log_differences) or _constant(log_samples)
    observed_sharpe = _delta_sharpe(a, b)
    return {
        "method": "paired_moving_block_percentile_v1", "n_observations": len(a),
        "n_resamples": int(n), "block_length": int(block), "seed": seed,
        "annualization": ANNUALIZATION,
        "observed": {"delta_log_wealth": float(log_differences.sum()),
                     "delta_sharpe": observed_sharpe},
        "delta_log_wealth_ci95": np.quantile(log_samples, [.025, .975]).tolist(),
        "delta_sharpe_ci95": (np.quantile(sharpe_samples, [.025, .975]).tolist()
                               if valid_sharpe.all() else None),
        "p_return_better": float((log_samples > 0).mean()),
        "p_sharpe_better": float((valid_sharpe & (sharpe_samples > 0)).mean()),
        "valid_sharpe_resamples": int(valid_sharpe.sum()),
        "degenerate": degenerate,
        "inferentially_valid": bool(not degenerate and valid_sharpe.all() and observed_sharpe is not None),
        "limitations": list(LIMITATIONS),
    }


def familywise_block_test(challengers: pd.DataFrame, control: pd.Series, n: int = 2000,
                         block: int = 30, seed: int = 17) -> dict:
    """Centered moving-block max-mean test in the style of White's Reality Check.

    Every challenger uses the same resampled dates. Raw and single-step adjusted
    p-values use (1 + exceedances)/(1 + n), including ties. Constant differences
    cannot establish an edge: their p-values are one and test statistic is zero.
    This controls only the supplied family; undisclosed earlier searches remain
    outside its adjustment. It is not an implementation of studentized SPA.
    """
    baseline = _returns(control, "control")
    if (not isinstance(challengers, pd.DataFrame) or challengers.shape[1] == 0
            or not challengers.columns.is_unique
            or not all(isinstance(column, str) and column for column in challengers.columns)):
        raise ValueError("challengers need unique, nonempty string column names")
    if not challengers.index.equals(control.index):
        raise ValueError("challengers and control must have exactly aligned indices")
    values = np.column_stack([_returns(challengers[name], name) for name in challengers])
    _resampling(n, block, len(baseline))
    differences = np.log1p(values) - np.log1p(baseline[:, None])
    means = differences.mean(axis=0)
    centered = differences - means
    degenerate = np.array([_constant(differences[:, j]) for j in range(values.shape[1])])
    centered[:, degenerate] = 0.0
    rng = np.random.default_rng(seed)
    null_means = np.empty((n, values.shape[1]))
    for i in range(n):
        indices = _block_indices(len(baseline), len(baseline), block, rng)
        null_means[i] = centered[indices].mean(axis=0)
    # A sole possible block (or otherwise invariant resampled statistic) gives
    # no empirical uncertainty estimate, even when the original path varies.
    degenerate |= np.array([_constant(null_means[:, j]) for j in range(values.shape[1])])
    null_means[:, degenerate] = 0.0
    # Include zero for the composite null that no challenger improves the control.
    null_maxima = np.maximum(0.0, null_means.max(axis=1))
    observed_max = max(0.0, float(np.max(np.where(degenerate, 0.0, means))))
    result = {}
    for j, name in enumerate(challengers):
        no_edge = bool(degenerate[j])
        result[name] = {
            "observed_mean_log_excess": float(means[j]), "degenerate": bool(degenerate[j]),
            "p_raw": 1.0 if no_edge else finite_randomization_pvalue(means[j], null_means[:, j]),
            "p_adjusted": 1.0 if no_edge else finite_randomization_pvalue(means[j], null_maxima),
        }
    return {
        "method": "centered_moving_block_max_mean_v1", "n_observations": len(baseline),
        "n_resamples": int(n), "block_length": int(block), "seed": seed,
        "statistic": "mean_excess_log_return", "family_size": len(result),
        "observed_max_mean_excess_log_return": observed_max,
        "global_p": (finite_randomization_pvalue(observed_max, null_maxima)
                     if observed_max > 0 else 1.0),
        "by_candidate": result, "history_status": "not_verified_as_unseen",
        "limitations": list(LIMITATIONS) + [
            "The multiplicity correction covers only the supplied challenger family.",
            "This is an unstudentized max-mean block test, not Hansen SPA or a universal validity certificate.",
            "Constant differences or invariant bootstrap statistics receive p=1; they cannot establish statistical superiority.",
        ],
    }


def chronological_folds(candidate: pd.Series, control: pd.Series, first_year: int = 2021) -> dict:
    """Describe complete calendar years of the same daily paths; never refit/reset.

    A complete year must contain every daily date from Jan 1 through Dec 31.
    Drawdown retains all previous observations, including the initial unit of
    wealth, so crossing a year boundary never resets the prior high-water mark.
    This is fold evidence for fixed paths, not a claim of training or selection.
    """
    a, b = _pair(candidate, control)
    if (not isinstance(candidate.index, pd.DatetimeIndex)
            or not candidate.index.equals(candidate.index.normalize())):
        raise ValueError("chronological folds require normalized daily DatetimeIndex labels")
    if isinstance(first_year, bool) or not isinstance(first_year, (int, np.integer)):
        raise ValueError("first_year must be an integer")
    # Log wealth avoids compounding over/underflow when computing continuous DD.
    wealth_logs = [np.log1p(values).cumsum() for values in (a, b)]
    drawdowns = [np.expm1(logs - np.maximum.accumulate(np.maximum(logs, 0.0)))
                 for logs in wealth_logs]
    years, omitted = [], []
    index = candidate.index
    for year in range(first_year, index[-1].year + 1):
        mask = index.year == year
        expected = pd.date_range(f"{year}-01-01", f"{year}-12-31", tz=index.tz)
        if not index[mask].equals(expected):
            omitted.append({"year": year, "reason": "incomplete_daily_calendar_year",
                            "observations": int(mask.sum()), "expected_observations": len(expected)})
            continue
        metrics = []
        for values, dd in zip((a, b), drawdowns):
            sampled = values[mask]
            log_return = float(np.log1p(sampled).sum())
            # Finite returns may imply wealth beyond float range; do not emit inf.
            total_return = float(np.expm1(log_return)) if log_return <= np.log(np.finfo(float).max) else None
            metrics.append({"total_return": total_return, "log_return": log_return,
                            "sharpe": _sharpe(sampled), "max_drawdown_continuous": float(dd[mask].min())})
        delta = metrics[0]["log_return"] - metrics[1]["log_return"]
        years.append({"year": year, "observations": len(expected),
                      "candidate_return": metrics[0]["total_return"],
                      "control_return": metrics[1]["total_return"], "candidate": metrics[0],
                      "control": metrics[1], "delta_log_wealth": delta, "candidate_better": delta > 0})
    wins = sum(row["candidate_better"] for row in years)
    return {
        "method": "chronological_fixed_path_years_v1", "annualization": ANNUALIZATION,
        "first_year": int(first_year), "complete_years": [row["year"] for row in years],
        "folds": years, "omitted_years": omitted, "wins": wins,
        "win_fraction": wins / len(years) if years else None,
        "selection_performed": False, "portfolio_reset": False,
        "limitations": ["Calendar partitions do not turn previously inspected data into an unseen holdout.",
                        "No strategy fitting or parameter selection is performed by this helper."],
    }
