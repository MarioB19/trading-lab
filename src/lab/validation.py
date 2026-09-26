"""Validación: las pruebas que separan una ventaja real de un espejismo estadístico."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

from .backtest import max_drawdown, sharpe, simulate
from .strategies import ANN, PARAM_GRID, compute, label

EULER = 0.5772156649


# ------------------------------------------------ Sharpe probabilístico y deflactado
def probabilistic_sharpe(ret: pd.Series, sr0_daily: float = 0.0) -> float:  # noqa: D401
    """P(el Sharpe verdadero > sr0), corrigiendo por colas gordas y asimetría (Bailey & López de Prado)."""
    r = ret.dropna().values
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = skew(r), kurtosis(r, fisher=False)
    denom = np.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return float(norm.cdf((sr - sr0_daily) * np.sqrt(len(r) - 1) / denom))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Sharpe máximo que esperarías por pura suerte al probar n_trials estrategias sin ventaja."""
    if n_trials < 2:
        return 0.0
    return float(np.sqrt(var_sr) * ((1 - EULER) * norm.ppf(1 - 1 / n_trials)
                                    + EULER * norm.ppf(1 - 1 / (n_trials * np.e))))


def deflated_sharpe(best_ret: pd.Series, trial_daily_srs: list[float], ann: int = ANN,
                    extra_trials: int = 0) -> dict:
    """extra_trials: intentos que no se simulan aquí (p. ej. las variantes en tiempo real,
    que necesitan datos por hora) pero que cuentan igual como pruebas hechas."""
    n = len(trial_daily_srs) + extra_trials
    sr0 = expected_max_sharpe(n, float(np.var(trial_daily_srs, ddof=1)))
    return {"n_trials": n, "sr0_annual": sr0 * np.sqrt(ann),
            "dsr": probabilistic_sharpe(best_ret, sr0)}


# ------------------------------------------------ todas las variantes
def run_grid(close: pd.Series, cost: float, band: float = 0.0,
             grid: dict | None = None) -> dict[str, dict]:
    """Calcula señal y backtest de cada variante sobre TODO el histórico (las señales son causales)."""
    grid = grid or PARAM_GRID
    out = {}
    for fam, plist in grid.items():
        for params in plist:
            tgt = compute(fam, close, params)
            out[label(fam, params)] = {"family": fam, "params": params, "target": tgt,
                                       "bt": simulate(close, tgt, cost, band)}
    return out


# ------------------------------------------------ walk-forward
def walk_forward(close: pd.Series, runs: dict[str, dict], first_test_year: int,
                 train_start: str, cost: float, band: float = 0.0,
                 families: list[str] | None = None) -> dict:
    """Cada año elige la variante con mejor Sharpe en el pasado y la usa el año siguiente.

    Así se opera en la vida real: solo conoces el pasado. El resultado del año
    elegido es genuinamente "fuera de muestra".
    """
    cands = {k: v for k, v in runs.items() if families is None or v["family"] in families}
    last_year = close.index[-1].year
    stitched = pd.Series(0.0, index=close.index)
    picks = []
    for year in range(first_test_year, last_year + 1):
        train_end = pd.Timestamp(f"{year - 1}-12-31")
        scores = {k: sharpe(v["bt"]["ret"].loc[train_start:train_end]) for k, v in cands.items()}
        best = max(scores, key=scores.get)
        sel = slice(f"{year}-01-01", f"{year}-12-31")
        stitched.loc[sel] = cands[best]["target"].loc[sel]
        picks.append({"year": year, "pick": best, "train_sharpe": scores[best]})
    # la decisión del 31-dic del año previo ya pertenece a la regla elegida
    prev = pd.Timestamp(f"{first_test_year - 1}-12-31")
    if prev in stitched.index:
        stitched.loc[prev] = cands[picks[0]["pick"]]["target"].loc[prev]
    bt = simulate(close, stitched, cost, band)
    return {"bt": bt, "picks": picks, "target": stitched}


# ------------------------------------------------ placebo: ¿el timing importa?
def placebo_shift_test(asset_ret: pd.Series, position: pd.Series, cost: float,
                       n: int = 1000, min_shift: int = 60, seed: int = 7, ann: int = ANN) -> dict:
    """Desfasa al azar la serie de posiciones contra los rendimientos.

    Conserva exactamente cuánto tiempo estás dentro y cuántas operaciones haces,
    pero destruye el "cuándo". Si la estrategia real no le gana a sus versiones
    desfasadas, su timing no aporta nada.
    """
    rng = np.random.default_rng(seed)
    r = asset_ret.values
    p = position.values
    L = len(p)

    def sr_of(pos):
        to = np.abs(np.diff(pos, prepend=pos[0]))
        s = pos * r - to * cost
        return s.mean() / s.std(ddof=1) * np.sqrt(ann)

    actual = sr_of(p)
    shifts = rng.integers(min_shift, L - min_shift, size=n)
    sims = np.array([sr_of(np.roll(p, k)) for k in shifts])
    return {"actual_sharpe": float(actual), "placebo_median": float(np.median(sims)),
            "placebo_p95": float(np.percentile(sims, 95)),
            "p_value": float((sims >= actual).mean()), "sims": sims}


# ------------------------------------------------ bootstrap por bloques
def _block_indices(n: int, length: int, block: int, rng) -> np.ndarray:
    starts = rng.integers(0, n - block, size=int(np.ceil(length / block)))
    return np.concatenate([np.arange(s, s + block) for s in starts])[:length]


def bootstrap_compare(ret_a: pd.Series, ret_b: pd.Series, n: int = 2000,
                      block: int = 30, seed: int = 11) -> dict:
    """Re-muestrea bloques de días (mismos días para A y B) para medir la incertidumbre."""
    rng = np.random.default_rng(seed)
    a, b = ret_a.values, ret_b.values
    d_sr, d_cagr, d_dd = [], [], []
    for _ in range(n):
        idx = _block_indices(len(a), len(a), block, rng)
        ra, rb = a[idx], b[idx]
        d_sr.append(ra.mean() / ra.std() - rb.mean() / rb.std())
        d_cagr.append(np.log1p(ra).sum() - np.log1p(rb).sum())
        d_dd.append(max_drawdown(pd.Series(ra)) - max_drawdown(pd.Series(rb)))
    d_sr, d_cagr, d_dd = map(np.array, (d_sr, d_cagr, d_dd))
    return {"p_sharpe_better": float((d_sr > 0).mean()),
            "p_return_better": float((d_cagr > 0).mean()),
            "p_drawdown_smaller": float((d_dd > 0).mean())}


def monte_carlo(ret: pd.Series, horizon: int = 365, n: int = 5000, block: int = 30,
                capital: float = 10_000, seed: int = 3) -> dict:  # horizon en filas (365 cripto, 252 bolsa)
    """Simula muchos "próximos 12 meses" armados con pedazos del pasado.

    Supone que el futuro se parece al pasado; en cripto eso es optimista
    (el BTC de 2026 no va a repetir los x100 de 2015-2021).
    """
    rng = np.random.default_rng(seed)
    r = ret.values
    finals, dds = np.empty(n), np.empty(n)
    for i in range(n):
        path = r[_block_indices(len(r), horizon, block, rng)]
        eq = np.cumprod(1 + path)
        finals[i] = eq[-1]
        dds[i] = (eq / np.maximum.accumulate(eq) - 1).min()
    q = lambda x, p: float(np.percentile(x, p))  # noqa: E731
    return {"capital": capital,
            "final_p5": capital * q(finals, 5), "final_p25": capital * q(finals, 25),
            "final_median": capital * q(finals, 50), "final_p75": capital * q(finals, 75),
            "final_p95": capital * q(finals, 95),
            "p_loss": float((finals < 1).mean()), "p_loss_20": float((finals < 0.8).mean()),
            "p_dd_30": float((dds < -0.30).mean()), "p_dd_50": float((dds < -0.50).mean()),
            "dd_median": float(np.median(dds)), "finals": finals, "dds": dds}
