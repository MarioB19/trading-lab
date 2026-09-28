"""Comparación preregistrada, retrospectiva y exclusivamente simulada.

``--describe`` es offline. La ejecución exige ExperimentRun antes de leer precios;
los helpers numéricos aceptan paneles explícitos para pruebas sintéticas offline.
No optimiza parámetros, no cambia el bot y no autoriza operar dinero real.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .aggressive_plan import (assert_current_control,
                              comparison_plan, isolated_directory, validate_registered_variants,
                              preregistration_path, AVAILABILITY_EVIDENCE)
from .backtest import sharpe
from .data import ROOT
from .experiments import ExperimentRun, ResearchGateError, canonical_hash
from .portfolio import (PortfolioParams, fixed_weights, listed_universe,
                        simulate_portfolio, target_weights)
from .research_multi import load_sleeve
from .validation import finite_randomization_pvalue


ROLES = ("control", "aggressive")
LIMITATIONS = [
    "Histórico ya inspeccionado: no es un holdout no visto ni evidencia prospectiva.",
    "Subconjunto Bitso actual retrospectivo; no hay fechas históricas verificadas de listings/delistings.",
    "Precios históricos del proveedor de research, no cotizaciones/fills históricos exactos de Bitso.",
    "El pipeline CoinMetrics/Yahoo puede aproximar historia temprana con capitalización escalada; "
    "el cache no conserva procedencia ni banderas de proxy por observación.",
    "Cierre diario con costo proporcional: no reproduce libros, colas maker, fills parciales, mínimos, "
    "límites por orden ni el filtro operativo max_price_jump. No certifica equivalencia exacta con el bot.",
    "Un kill se verifica en la siguiente decisión diaria: una caída puede superar el umbral entre cierres.",
    "SPY/IEF usa sesiones presentes en el panel; no verifica un calendario bursátil externo.",
    "Placebo prueba timing de la candidata en esta ventana, no superioridad incremental al control.",
    "Bootstrap pareado describe incertidumbre retrospectiva; no garantiza resultados futuros.",
    "No calcula DSR global: dos variantes de esta corrida no representan todos los intentos históricos.",
    "Requiere 28 días futuros completos en paper y revisión humana; live_authorized permanece false.",
]


def _index_ok(prices: pd.DataFrame) -> None:
    idx = prices.index
    if (not isinstance(idx, pd.DatetimeIndex) or not len(idx) or not idx.is_unique
            or not idx.is_monotonic_increasing or idx.tz is not None or not idx.equals(idx.normalize())):
        raise ResearchGateError("el panel requiere cierres diarios UTC sin zona, únicos y ordenados")


def prepare_panels(plan: dict, crypto: pd.DataFrame, eligible: pd.DataFrame,
                   stocks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fija ventana y columnas antes del congelado; conserva ausencias como NaN."""
    for prices in (crypto, stocks):
        _index_ok(prices)
    if not crypto.index.equals(eligible.index) or not crypto.columns.equals(eligible.columns):
        raise ResearchGateError("la elegibilidad no corresponde al panel cripto")
    ev = plan["evaluation"]
    crypto = crypto.loc[ev["history_start"]:ev["end"]].reindex(
        columns=plan["portfolios"]["control"]["crypto"]["universe"]).copy()
    stocks = stocks.loc[ev["history_start"]:ev["end"]].reindex(
        columns=list(plan["portfolios"]["control"]["stocks"]["mix"])).copy()
    eligible = (eligible.reindex_like(crypto).fillna(False).astype(bool)
                & listed_universe(crypto, min_history=ev["min_history"]))
    return crypto, eligible, stocks


def availability(prices: pd.DataFrame, sleeve: str, plan: dict | None = None) -> dict:
    result = {"scope": "fixed_bitso_subset" if sleeve == "crypto" else "identical_SPY_IEF",
            "historical_listings_verified": False,
            "source": "research_multi.load_sleeve cached historical panel",
            "source_pipeline_expected": "CoinMetrics/Yahoo with possible market-cap proxy" if sleeve == "crypto"
                                        else "Yahoo adjusted daily closes",
            "source_by_observation_available": False,
            "proxy_flags_by_observation_available": False,
            "internal_missing_closes_allowed": False,
            "pre_first_observation_missing_allowed": True,
            "execution_prices_match_broker": False,
            "missing_assets": [asset for asset in prices if prices[asset].notna().sum() == 0],
            "first_observed_close": {asset: str(prices[asset].first_valid_index()) for asset in prices},
            "limitations": LIMITATIONS[:6]}
    if plan and "source_snapshot" in plan:
        result.update(source="pinned_original_run_snapshot", source_run_id=plan["source_snapshot"]["run_id"],
                      raw_sha256=plan["source_snapshot"][sleeve]["sha256"])
        if sleeve == "crypto":
            result["availability_policy"] = plan["availability_policy"]
    return result


def validate_panels(plan: dict, crypto: pd.DataFrame, eligible: pd.DataFrame,
                    stocks: pd.DataFrame) -> None:
    """Falla cerrado ante cobertura insuficiente; no sustituye activos silenciosamente."""
    ev = plan["evaluation"]
    start, end = pd.Timestamp(ev["start"]), pd.Timestamp(ev["end"])
    if not pd.Timestamp(ev["history_start"]) < start <= end:
        raise ResearchGateError("ventana de evaluación inválida")
    required = plan["portfolios"]["control"]["crypto"]["universe"]
    if list(crypto.columns) != required or list(stocks.columns) != list(
            plan["portfolios"]["control"]["stocks"]["mix"]):
        raise ResearchGateError("los activos no corresponden al plan")
    if not crypto.index.equals(eligible.index) or not crypto.columns.equals(eligible.columns):
        raise ResearchGateError("elegibilidad desalineada")
    for name, prices in (("crypto", crypto), ("stocks", stocks)):
        _index_ok(prices)
        observed = prices.to_numpy(dtype=float)
        if np.isinf(observed).any() or (observed[np.isfinite(observed)] <= 0).any():
            raise ResearchGateError(f"{name}: hay precios no positivos o infinitos")
        missing = availability(prices, name)["missing_assets"]
        if missing:
            raise ResearchGateError(f"{name}: faltan activos declarados: {', '.join(missing)}")
        if len(prices.loc[:start - pd.Timedelta(days=1)]) < ev["min_history"]:
            raise ResearchGateError(f"{name}: warmup insuficiente")
        # Incluso un hueco de una fila permite al motor vender al cierre imputado
        # antes de observar la caída siguiente. Rechazar también en warmup evita
        # formar señales sobre cierres inexistentes. Se permiten NaN pre-listing.
        for asset in prices:
            observed_history = prices[asset].loc[prices[asset].first_valid_index():]
            if observed_history.isna().any():
                gap = observed_history.index[observed_history.isna()][0].date()
                raise ResearchGateError(
                    f"{name}/{asset}: cierre ausente en {gap} tras el primer precio observado; "
                    "comparación no ejecutada para evitar valorar u operar a precio imputado")
        evaluation = prices.loc[start:end]
        if evaluation.empty:
            raise ResearchGateError(f"{name}: no hay cierres de evaluación")
        if name == "crypto":
            expected = pd.date_range(start - pd.Timedelta(days=1), end, freq="D")
            if not expected.isin(prices.index).all():
                raise ResearchGateError("crypto: faltan fechas diarias de evaluación o su ancla")
            regime = plan["portfolios"]["control"]["crypto"]["params"]["regime_asset"]
            if prices.loc[:start - pd.Timedelta(days=1), regime].notna().sum() < ev["min_history"]:
                raise ResearchGateError("crypto: warmup de BTC insuficiente")
        else:
            if ((evaluation.index[0] - start).days > 7 or (end - evaluation.index[-1]).days > 7
                    or evaluation.index.to_series().diff().dropna().max() > pd.Timedelta(days=7)):
                raise ResearchGateError("stocks: cobertura de sesiones insuficiente")
            if (prices.loc[:start - pd.Timedelta(days=1)].notna().sum() < ev["min_history"]).any():
                raise ResearchGateError("stocks: warmup SPY/IEF insuficiente")
            if evaluation.isna().any().any():
                raise ResearchGateError("stocks: falta un cierre de SPY/IEF en la evaluación")


def evaluation_simulation(prices: pd.DataFrame, weights: pd.DataFrame, params: PortfolioParams,
                          sleeve: dict, start: str, end: str, cost: float) -> pd.DataFrame:
    """Capital inicial una sola vez, ancla previa sin trades y kill continuo."""
    start_ts = pd.Timestamp(start)
    previous = prices.index[prices.index < start_ts]
    if not len(previous):
        raise ResearchGateError("falta el cierre anterior al inicio de evaluación")
    window = prices.loc[previous[-1]:end]
    bt = simulate_portfolio(window, weights.reindex_like(window), params, cost=cost,
                            band=sleeve["band"], kill_dd=sleeve["kill_drawdown"])
    # Las columnas son valores de cierre, con costos cobrados antes del retorno.
    bt = bt.loc[start:end].copy()
    bt.attrs = {}  # held es una matriz grande; los CSV guardan la curva neta.
    capital = float(sleeve["capital"])
    bt["equity_usd"] = capital * (1 + bt["ret"]).cumprod()
    prior_equity = bt["equity_usd"].shift(1, fill_value=capital)
    bt["turnover_usd"] = prior_equity * bt["turnover"]
    bt["cost_usd"] = bt["turnover_usd"] * cost
    bt["cumulative_cost_usd"] = bt["cost_usd"].cumsum()
    # Incluir el capital inicial evita esconder el costo/pérdida de la primera entrada.
    bt["drawdown"] = bt["equity_usd"] / bt["equity_usd"].cummax().clip(lower=capital) - 1
    if bt.empty or not np.isfinite(bt.to_numpy()).all() or (bt["ret"] <= -1).any():
        raise ResearchGateError("trayectoria vacía, no finita o insolvente")
    return bt


def curve_metrics(curve: pd.DataFrame, capital: float, ann: int) -> dict:
    ret = curve["ret"]
    mult = float(curve["equity_usd"].iloc[-1] / capital)
    return {"cagr": float(mult ** (ann / len(ret)) - 1), "sharpe": sharpe(ret, ann),
            "max_dd": float(curve["drawdown"].min()), "net_return": mult - 1,
            "final_equity_usd": float(curve["equity_usd"].iloc[-1]),
            "cost_usd": float(curve["cost_usd"].sum()),
            "turnover_usd": float(curve["turnover_usd"].sum()),
            "turnover_multiple": float(curve["turnover"].sum()), "observations": len(curve)}


def combine_sleeves(crypto: pd.DataFrame, stocks: pd.DataFrame, crypto_capital: float,
                    stocks_capital: float) -> pd.DataFrame:
    """Suma capitales independientes; ningún traspaso/rebalanceo entre bloques."""
    idx = crypto.index
    aligned = stocks.reindex(idx)
    stock_equity = aligned["equity_usd"].ffill().fillna(stocks_capital)
    total = pd.DataFrame(index=idx)
    total["equity_usd"] = crypto["equity_usd"] + stock_equity
    initial = crypto_capital + stocks_capital
    previous = total["equity_usd"].shift(1, fill_value=initial)
    total["ret"] = total["equity_usd"] / previous - 1
    for col in ("cost_usd", "turnover_usd"):
        total[col] = crypto[col] + aligned[col].fillna(0)
    total["turnover"] = total["turnover_usd"] / previous
    total["cumulative_cost_usd"] = total["cost_usd"].cumsum()
    total["drawdown"] = total["equity_usd"] / total["equity_usd"].cummax().clip(lower=initial) - 1
    return total


def annual_windows(control: pd.Series, aggressive: pd.Series, start: str, end: str,
                   minimum: int, win_fraction: float) -> dict:
    """Ventanas fijas sobre retornos continuos; no entrena ni reinicia capital."""
    if not control.index.equals(aggressive.index):
        raise ResearchGateError("retornos anuales desalineados")
    rows = []
    for year in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        first, last = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year}-12-31")
        expected = pd.date_range(first, last)
        complete = (first >= pd.Timestamp(start) and last <= pd.Timestamp(end)
                    and expected.isin(control.index).all())
        a, b = control.loc[first:last], aggressive.loc[first:last]
        if a.empty:
            continue
        ra, rb = float((1 + a).prod() - 1), float((1 + b).prod() - 1)
        rows.append({"year": year, "complete": bool(complete), "observations": len(a),
                     "control_return": ra, "aggressive_return": rb, "aggressive_wins": rb > ra})
    complete = [row for row in rows if row["complete"]]
    fraction = sum(row["aggressive_wins"] for row in complete) / len(complete) if complete else None
    return {"method": "fixed_parameters_continuous_path_annual_windows", "optimized": False,
            "unseen_holdout": False, "capital_reset_each_year": False, "windows": rows,
            "complete_years": len(complete), "win_fraction": fraction,
            "passed": len(complete) >= minimum and fraction >= win_fraction}


def paired_bootstrap(aggressive: pd.Series, control: pd.Series, n: int, block: int,
                     seed: int, ann: int = 365) -> tuple[dict, pd.DataFrame]:
    """Mismos bloques móviles para ambos, incluidos todos los inicios admisibles."""
    if (not aggressive.index.equals(control.index) or n < 1 or block < 1
            or len(control) <= block):
        raise ResearchGateError("bootstrap requiere series alineadas y más observaciones que el bloque")
    a, b = aggressive.to_numpy(), control.to_numpy()
    if not np.isfinite([a, b]).all() or (a <= -1).any() or (b <= -1).any():
        raise ResearchGateError("bootstrap requiere retornos finitos mayores a -1")
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n):
        starts = rng.integers(0, len(a) - block + 1, size=int(np.ceil(len(a) / block)))
        idx = (starts[:, None] + np.arange(block)).ravel()[:len(a)]
        ra, rb = a[idx], b[idx]
        sa, sb = ra.std(ddof=1), rb.std(ddof=1)
        delta = (ra.mean() / sa - rb.mean() / sb) * np.sqrt(ann) if sa > 0 and sb > 0 else np.nan
        samples.append((float(np.log1p(ra).sum() - np.log1p(rb).sum()), float(delta)))
    draws = pd.DataFrame(samples, columns=["log_return_delta", "sharpe_delta"])
    valid = bool(np.isfinite(draws.to_numpy()).all())
    return {"method": "paired_moving_blocks", "n": n, "block": block, "seed": seed,
            "valid": valid, "undefined_sharpe_draws": int(draws["sharpe_delta"].isna().sum()),
            "p_return_better": float((draws["log_return_delta"] > 0).mean()),
            "p_sharpe_better": float((draws["sharpe_delta"] > 0).mean()) if valid else None,
            "interpretation": "frecuencia bootstrap retrospectiva, no probabilidad de ganancia futura"}, draws


def timing_placebo(prices: pd.DataFrame, weights: pd.DataFrame, params: PortfolioParams,
                   sleeve: dict, plan: dict, actual_sharpe: float) -> tuple[dict, pd.DataFrame]:
    ev, criteria = plan["evaluation"], plan["criteria"]
    anchor = prices.index[prices.index < pd.Timestamp(ev["start"])][-1]
    px, wt = prices.loc[anchor:ev["end"]], weights.loc[anchor:ev["end"]]
    # Desfasar solamente la ventana evaluada, preservando su distribución de señales.
    min_shift = 90
    if len(px) <= 2 * min_shift:
        raise ResearchGateError("placebo necesita más de 180 cierres de evaluación")
    rng = np.random.default_rng(criteria["placebo_seed"])
    shifts = rng.integers(min_shift, len(px) - min_shift + 1, size=criteria["placebo_n"])
    scores = []
    for offset in shifts:
        shifted = pd.DataFrame(np.roll(wt.to_numpy(), int(offset), axis=0), index=px.index, columns=px.columns)
        shifted = shifted.where(px.notna(), 0.0)
        bt = evaluation_simulation(px, shifted, params, sleeve, ev["start"], ev["end"],
                                   plan["costs"]["crypto"]["base"])
        scores.append(sharpe(bt["ret"], params.ann))
    p = finite_randomization_pvalue(actual_sharpe, scores)
    return {"actual_sharpe": actual_sharpe, "p_value": p, "n": len(scores),
            "seed": criteria["placebo_seed"], "minimum_shift_days": min_shift,
            "scope": "aggressive_timing_only_not_incremental_superiority", "kill_enabled": True,
            "finite_correction": "(1 + placebo_sharpe >= actual count) / (n + 1)",
            "passed": p < criteria["placebo_p_max"]}, pd.DataFrame({"shift": shifts, "sharpe": scores})


def _cost_key(cost: float) -> str:
    return f"{cost:.4f}"


def comparison_checks(plan: dict, metrics: dict, annual: dict, bootstrap: dict, placebo: dict) -> dict:
    c = plan["criteria"]
    base = metrics[_cost_key(plan["costs"]["crypto"]["base"])]
    a, b = base["aggressive"]["crypto"], base["control"]["crypto"]
    stress = metrics[_cost_key(c["stress_gate_cost"])]
    sa, sb = stress["aggressive"]["crypto"], stress["control"]["crypto"]
    cagr_ok = a["cagr"] - b["cagr"] >= c["cagr_delta_min"]
    sharpe_ok = a["sharpe"] - b["sharpe"] >= c["sharpe_delta_min"]
    return {"cagr": cagr_ok, "sharpe": sharpe_ok,
            "drawdown": (a["max_dd"] >= -c["max_drawdown_abs"]
                         and a["max_dd"] >= b["max_dd"] - c["drawdown_delta_max"]),
            # promotion_gate consume walk_forward, no los subchecks CAGR/Sharpe.
            # El gate compuesto conserva todos los criterios del preregistro.
            "walk_forward": bool(annual["passed"] and cagr_ok and sharpe_ok),
            "bootstrap": bool(bootstrap["valid"] and bootstrap["p_return_better"] >= c["bootstrap_return_min"]
                              and bootstrap["p_sharpe_better"] >= c["bootstrap_sharpe_min"]),
            "placebo": bool(placebo["passed"]),
            "cost_stress": sa["cagr"] >= sb["cagr"] and sa["sharpe"] >= sb["sharpe"]}


def compare_panels(plan: dict, crypto: pd.DataFrame, eligible: pd.DataFrame, stocks: pd.DataFrame,
                   variant_event: Callable[[str, str], None] | None = None) -> tuple[dict, dict[str, pd.DataFrame]]:
    """Núcleo con entradas explícitas; la CLI lo llama únicamente detrás del gate."""
    validate_panels(plan, crypto, eligible, stocks)
    ev, criteria = plan["evaluation"], plan["criteria"]
    stocks_cfg = plan["portfolios"]["control"]["stocks"]
    # Passive en el bot no aplica el freno táctico; conserva kill y la banda.
    stocks_params = replace(PortfolioParams.from_dict(stocks_cfg["params"]), dd_brake=False)
    stocks_bt = evaluation_simulation(stocks, fixed_weights(stocks, stocks_cfg["mix"]), stocks_params,
                                     stocks_cfg, ev["start"], ev["end"], plan["costs"]["stocks"]["base"])
    stock_metrics = curve_metrics(stocks_bt, stocks_cfg["capital"], stocks_params.ann)
    costs = [plan["costs"]["crypto"]["base"], *plan["costs"]["crypto"]["stress"]]
    curves, metrics, base_curves, targets = {}, {}, {}, {}
    for role in ROLES:
        if variant_event:
            variant_event(role, "started")
        cfg = plan["portfolios"][role]["crypto"]
        p = PortfolioParams.from_dict(cfg["params"])
        targets[role] = target_weights(crypto, eligible, p)
        for cost in costs:
            key = _cost_key(cost)
            bt = evaluation_simulation(crypto, targets[role], p, cfg, ev["start"], ev["end"], cost)
            total = combine_sleeves(bt, stocks_bt, cfg["capital"], stocks_cfg["capital"])
            curves[f"{role}_crypto_{key}"] = bt
            curves[f"{role}_total_{key}"] = total
            metrics.setdefault(key, {})[role] = {
                "crypto": curve_metrics(bt, cfg["capital"], p.ann), "stocks": stock_metrics.copy(),
                "total_secondary": curve_metrics(total, plan["initial_capital_usd"], 365)}
            if cost == costs[0]:
                base_curves[role] = bt
        curves[f"{role}_stocks"] = stocks_bt.copy()
        if variant_event:
            variant_event(role, "completed")
    annual = annual_windows(base_curves["control"]["ret"], base_curves["aggressive"]["ret"],
                            ev["start"], ev["end"], ev["min_complete_years"], criteria["yearly_win_fraction_min"])
    bootstrap, draws = paired_bootstrap(base_curves["aggressive"]["ret"], base_curves["control"]["ret"],
                                       criteria["bootstrap_n"], criteria["bootstrap_block"], criteria["bootstrap_seed"])
    cfg = plan["portfolios"]["aggressive"]["crypto"]
    placebo, placebo_draws = timing_placebo(
        crypto, targets["aggressive"], PortfolioParams.from_dict(cfg["params"]), cfg, plan,
        metrics[_cost_key(costs[0])]["aggressive"]["crypto"]["sharpe"])
    curves["bootstrap_samples"], curves["placebo_samples"] = draws, placebo_draws
    checks = comparison_checks(plan, metrics, annual, bootstrap, placebo)
    result = {"experiment_id": plan["experiment_id"], "config_sha256": canonical_hash(plan),
              "mode": "paper", "live_authorized": False, "primary_sleeve": "crypto",
              "evaluation": ev, "execution_model": plan["execution_model"], "metrics": metrics,
              "costs": plan["costs"], "criteria": criteria, "checks": checks,
              "retrospective_checks_passed": all(checks.values()), "ready_for_promotion": False,
              "annual_fixed_windows": annual, "bootstrap": bootstrap, "placebo": placebo,
              "causality": {"status": "synthetic_prefix_tests_required_separately",
                            "verified_automatically_by_this_run": False,
                            "test_file": "tests/test_aggressive_research.py"},
              "dsr": {"computed": False, "reason": "incomplete global historical trial registry",
                      "declared_variants_this_run": 2, "global_historical_trial_count": None},
              "stocks_identical": True, "capital_rebalanced_between_sleeves": False,
              "informative_only_cost": criteria["stress_informative_cost"], "limitations": LIMITATIONS}
    return result, curves


def report_markdown(result: dict) -> str:
    lines = [f"# Comparación retrospectiva paper — {result['experiment_id']}", "",
             "Histórico inspeccionado; no es holdout no visto. Comparación primaria: cripto.",
             "Capital virtual: 500 USD cripto + 500 USD SPY/IEF por cartera; sin traspasos entre bloques.", "",
             "| Costo cripto | Cartera | CAGR neto | Sharpe | Caída máxima | Costos USD | Rotación USD |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for cost, roles in result["metrics"].items():
        for role, data in roles.items():
            m = data["crypto"]
            lines.append(f"| {float(cost):.2%} | {role} | {m['cagr']:.2%} | {m['sharpe']:.3f} | "
                         f"{m['max_dd']:.2%} | {m['cost_usd']:.2f} | {m['turnover_usd']:.2f} |")
    lines += ["", "Criterios preregistrados (el estrés de 1% es informativo):", ""]
    lines += [f"- {name}: {'pasa' if passed else 'no pasa'}" for name, passed in result["checks"].items()]
    annual, boot, placebo = result["annual_fixed_windows"], result["bootstrap"], result["placebo"]
    lines += ["", f"Años completos: {annual['complete_years']}; fracción con ventaja: {annual['win_fraction']}.",
              f"Bootstrap pareado: retorno {boot['p_return_better']}; Sharpe {boot['p_sharpe_better']}.",
              f"Placebo de timing: p={placebo['p_value']:.6f} ({placebo['n']} desfases).", "",
              "Las curvas y métricas agregadas son secundarias y están en comparison.json/curves/.",
              "Los costos incluyen comisión y deslizamiento modelados, no comisiones reales verificadas.",
              "No promueve ni activa esta estrategia. Faltan 28 días futuros completos en paper.", "",
              "Limitaciones:", "", *[f"- {item}" for item in result["limitations"]], ""]
    return "\n".join(lines)


def load_registered_panels(plan: dict, context: ExperimentRun):
    """Only called after the registration gate; v2 never refreshes the source cache."""
    if "source_snapshot" not in plan:
        crypto, eligible = load_sleeve("crypto", refresh=plan["evaluation"]["refresh"], universe="bitso")
        stocks, _ = load_sleeve("stocks", refresh=plan["evaluation"]["refresh"])
        return crypto, eligible, stocks, None
    from .research_data import apply_availability_policy

    source = plan["source_snapshot"]
    frozen = context.directory / "source_inputs"
    frozen.mkdir()
    raw = {}
    for name in ("manifest", "crypto", "stocks"):
        item = source[name]
        path = ROOT / item["path"]
        if path.is_symlink() or not path.resolve().is_relative_to((ROOT / "reports/experiments").resolve()):
            raise ResearchGateError("la fuente original debe permanecer dentro de los experimentos")
        raw[name] = path.read_bytes()
        if hashlib.sha256(raw[name]).hexdigest() != item["sha256"]:
            raise ResearchGateError(f"la captura original cambió: {name}")
        destination = frozen / ("parent_manifest.json" if name == "manifest" else f"raw_{name}_prices.csv")
        destination.write_bytes(raw[name])
    parent = json.loads(raw["manifest"])
    if parent.get("run_id") != source["run_id"] or parent.get("experiment_id") != "aggressive-v1":
        raise ResearchGateError("la captura no corresponde al intento original")
    if (parent.get("status") != "failed" or len(parent.get("variants", [])) != 2
            or any(v.get("status") != "declared" for v in parent["variants"])):
        raise ResearchGateError("el intento original ya evaluó variantes o cambió de estado")
    artifacts = {item["file"]: item["sha256"] for item in parent.get("artifacts", [])}
    if any(artifacts.get(f"inputs/{name}_prices.csv") != source[name]["sha256"]
           for name in ("crypto", "stocks")):
        raise ResearchGateError("los hashes de precios no corresponden al manifiesto original")
    policy = plan["availability_policy"]
    evidence = AVAILABILITY_EVIDENCE.read_bytes()
    if hashlib.sha256(evidence).hexdigest() != policy["evidence_sha256"]:
        raise ResearchGateError("la evidencia de disponibilidad cambió después del preregistro")
    (frozen / "availability_evidence.json").write_bytes(evidence)
    crypto = pd.read_csv(io.BytesIO(raw["crypto"]), index_col=0, parse_dates=True)
    stocks = pd.read_csv(io.BytesIO(raw["stocks"]), index_col=0, parse_dates=True)
    crypto, audit = apply_availability_policy(crypto, policy)
    (context.directory / "data_quality_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    context.manifest["source_snapshot"] = source
    context.manifest["availability_correction"] = audit
    context._save_manifest()
    context.event("availability_policy_applied", evidence_sha256=policy["evidence_sha256"],
                  quarantined_count=audit["quarantined_count"], source_run_id=source["run_id"])
    return crypto, listed_universe(crypto, min_history=plan["evaluation"]["min_history"]), stocks, audit


def _destinations(output_root: Path, ledger: Path) -> tuple[Path, Path]:
    output = isolated_directory(output_root)
    # Validar archivo y directorio: nunca escribir sobre state/, config o fuente.
    ledger = Path(ledger).resolve()
    isolated_directory(ledger)
    isolated_directory(ledger.parent)
    if ledger.exists() and not ledger.is_file():
        raise ResearchGateError("ledger debe ser un archivo JSONL dedicado")
    if ledger == output or ledger in output.parents:
        raise ResearchGateError("ledger no puede ocupar el directorio de resultados")
    return output, ledger


def run(preregistration_commit: str | None = None, output_root: Path | None = None,
        ledger: Path | None = None, plan_path: Path | None = None) -> Path:
    plan, variants = comparison_plan(plan_path) if plan_path else comparison_plan()
    validate_registered_variants(plan)
    if not preregistration_commit:
        raise ResearchGateError("se requiere --preregistration-commit; --describe no corre investigación")
    output = Path(output_root) if output_root is not None else ROOT / "reports/experiments"
    ledger_path = Path(ledger) if ledger is not None else output / "ledger.jsonl"
    output, ledger_path = _destinations(output, ledger_path)
    assert_current_control(plan)
    # Este constructor verifica commit previo/aprobación/árbol limpio/config exacta.
    # Debe permanecer ANTES de toda carga de panel y todo cálculo de rendimiento.
    context = ExperimentRun(ROOT, plan["experiment_id"], preregistration_path(plan), preregistration_commit,
                            plan, variants, output, ledger_path)
    ids = {v["role"]: v["id"] for v in variants}
    try:
        crypto, eligible, stocks, data_audit = load_registered_panels(plan, context)
        crypto, eligible, stocks = prepare_panels(plan, crypto, eligible, stocks)
        context.freeze_dataset("crypto", crypto, eligible, availability(crypto, "crypto", plan))
        context.freeze_dataset("stocks", stocks, listed_universe(stocks, plan["evaluation"]["min_history"]),
                               availability(stocks, "stocks", plan))
        result, curves = compare_panels(plan, crypto, eligible, stocks,
                                       lambda role, status: context.variant(ids[role], status))
        result.update(run_id=context.run_id, code_commit=context.proof["code_commit"])
        if data_audit is not None:
            result["data_quality_audit"] = data_audit
        curve_dir = context.directory / "curves"
        curve_dir.mkdir()
        for name, curve in curves.items():
            curve.to_csv(curve_dir / f"{name}.csv", float_format="%.17g", index_label="date_or_sample")
        (context.directory / "comparison.json").write_text(json.dumps(result, indent=2, ensure_ascii=False,
                                                                       allow_nan=False) + "\n")
        (context.directory / "comparison.md").write_text(report_markdown(result))
        context.event("comparison_evaluated", checks=result["checks"], ready_for_promotion=False)
        context.finish("completed")
        return context.directory
    except Exception as exc:
        for identity, state in context.variant_states.items():
            if state == "started":
                context.variant(identity, "failed")
        failure = {"error_type": type(exc).__name__, "message": str(exc),
                   "live_authorized": False, "ready_for_promotion": False, "limitations": LIMITATIONS}
        (context.directory / "failure.json").write_text(json.dumps(failure, indent=2, ensure_ascii=False) + "\n")
        context.finish("failed")
        raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true", help="describir plan e IDs sin cargar datos")
    parser.add_argument("--plan", type=Path, help="plan congelado; default aggressive_v1.yaml")
    parser.add_argument("--preregistration-commit", help="SHA40 del preregistro aprobado en commit anterior")
    parser.add_argument("--output-root", type=Path, help="directorio aislado (default reports/experiments)")
    parser.add_argument("--ledger", type=Path, help="JSONL aislado (default OUTPUT_ROOT/ledger.jsonl)")
    args = parser.parse_args(argv)
    if args.describe:
        plan, variants = comparison_plan(args.plan) if args.plan else comparison_plan()
        validate_registered_variants(plan)
        print(json.dumps({"plan": plan, "config_sha256": canonical_hash(plan), "variants": variants,
                          "executed": False, "live_authorized": False}, indent=2, ensure_ascii=False))
        return
    try:
        print(run(args.preregistration_commit, args.output_root, args.ledger, args.plan))
    except ResearchGateError as exc:
        parser.exit(2, f"Investigación no ejecutada o incompleta: {exc}\n")


if __name__ == "__main__":
    main()
