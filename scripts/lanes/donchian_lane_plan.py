"""Genera configs/experiments/donchian_lane_v1.yaml a partir de config.yaml (control = piloto exacto).

    PYTHONPATH=src python scripts/lanes/donchian_lane_plan.py

Describirlo no descarga datos ni calcula rendimiento. Ver reports/donchian_lane_v1_preregistro.md.
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from lab.bot import SLEEVE_DEFAULTS, load_config
from lab.data import ROOT
from lab.experiments import canonical_hash, file_hash
from lab.portfolio import PortfolioParams

OUT = ROOT / "configs/experiments/donchian_lane_v1.yaml"
EVIDENCE = {"preregistro": "reports/catalogo100_preregistro.md", "resultado": "reports/catalogo100_resultado.json",
            "resultado_md": "reports/catalogo100_resultado.md"}


def sleeve_block(sc: dict, params: dict, fee: float, slippage: float) -> dict:
    keys = ("enabled", "label", "strategy", "universe", "data", "quote", "capital", "compound", "band",
            "kill_drawdown", "max_order_value", "min_order_value", "max_data_age_hours", "benchmark", "min_history")
    out = {k: copy.deepcopy(sc[k]) for k in keys}
    out.update({"params": params, "paper_broker": "sim", "fee": fee, "slippage": slippage,
                "execution": {"maker_first": False}, "capital": 500.0, "max_order_value": 500.0})
    if sc["strategy"] == "passive":
        out["mix"] = copy.deepcopy(sc["mix"])
    return out


def build() -> dict:
    cfg = load_config(ROOT / "config.yaml")
    crypto, stocks = cfg["sleeves"]["crypto"], cfg["sleeves"]["stocks"]
    control_params = PortfolioParams.from_dict(crypto["params"]).to_dict()
    candidate_params = PortfolioParams.from_dict({**crypto["params"], "signal": "donchian", "donchian_entry": 55,
                                                  "donchian_exit": 20, "weighting": "equal", "regime_asset": None}).to_dict()
    stocks_params = PortfolioParams.from_dict({**SLEEVE_DEFAULTS["stocks"]["params"], **stocks.get("params", {})}).to_dict()
    control_crypto = sleeve_block(crypto, control_params, 0.0036, 0.0006)
    stocks_block = sleeve_block(stocks, stocks_params, 0.0, 0.0005)
    candidate_crypto = copy.deepcopy(control_crypto)
    candidate_crypto["params"] = candidate_params
    plan = {
        "protocol_version": 1, "mode": "paper", "initial_capital_usd": 1000.0,
        "baseline_config_sha256": file_hash(ROOT / "config.yaml"),
        "costs": {"crypto": {"base": 0.0042, "stress": [0.0063]}, "stocks": {"base": 0.0005}},
        "execution_model": "daily_close_simulated_fee_and_slippage_no_orderbook",
        "live_authorized": False, "max_price_jump": 0.4, "experiment_id": "donchian-lane-v1",
        "engine_version": "paired-paper-v1",
        "portfolios": {"control": {"crypto": control_crypto, "stocks": stocks_block},
                       "candidate": {"crypto": candidate_crypto, "stocks": copy.deepcopy(stocks_block)}},
        "evaluation": {"forward_min_days": 28, "min_history": 250, "historical_holdout_unseen": False,
                       "selection_basis": ("catalogo100: mejor variante de la familia F4 por Sharpe (1.34, +53.4% anual, "
                                           "rotación 15.9); NO superó la corrección por 101 comparaciones (p ajustada 0.69). "
                                           "El carril es observación prospectiva, no una aprobación"),
                       "earliest_observation_utc": None},
        "historical_evidence": {name: {"path": path, "sha256": file_hash(ROOT / path)} for name, path in EVIDENCE.items()},
        "criteria": {"prospective_days_min": 28, "no_observation_gaps": True, "no_unresolved_errors": True,
                     "net_return_noninferiority": True, "drawdown_noninferiority_tolerance": 0.02,
                     "turnover_ratio_max": 1.0, "promotion_requires_human_review": True, "live_authorized": False},
    }
    return plan


def main() -> None:
    plan = build()
    OUT.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    print(OUT.relative_to(ROOT), "config_sha256:", canonical_hash(plan))


if __name__ == "__main__":
    main()
