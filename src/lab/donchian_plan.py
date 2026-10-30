"""Plan prospectivo fijo del carril Donchian 55/20 (H10); describirlo no descarga datos ni calcula nada.

La candidata NO superó la corrección por comparación múltiple del catálogo 100 (p ajustada 0.69): el
carril es observación hacia adelante contra el control, en los mismos días, con `lab.paper_comparison`.
Nunca autoriza dinero real ni cambia el piloto.
"""
from __future__ import annotations

import copy

from .data import ROOT
from .experiments import ResearchGateError, file_hash

EXPERIMENT_ID = "donchian-lane-v1"
PLAN_SHA256 = "7f1ec8f5cb54e35daf078640db82d47908f32d3d25e073059bac5def293365ba"
CANDIDATE_ONLY = {"signal": "donchian", "donchian_entry": 55, "donchian_exit": 20, "weighting": "equal", "regime_asset": None}


def validate_plan(plan: dict) -> None:
    from .experiments import canonical_hash

    if canonical_hash(plan) != PLAN_SHA256:
        raise ResearchGateError("el plan prospectivo Donchian cambió después del preregistro")
    if plan.get("mode") != "paper" or plan.get("live_authorized") is not False:
        raise ResearchGateError("el carril admite exclusivamente dinero simulado")
    if plan.get("initial_capital_usd") != 1000.0 or plan.get("max_price_jump") != 0.4:
        raise ResearchGateError("capital virtual o control de precios distintos del preregistro")
    for name, item in plan["historical_evidence"].items():
        if file_hash(ROOT / item["path"]) != item["sha256"]:
            raise ResearchGateError(f"la evidencia histórica cambió: {name}")
    portfolios = plan["portfolios"]
    if set(portfolios) != {"control", "candidate"}:
        raise ResearchGateError("se requieren exactamente control y candidata")
    control, candidate = portfolios["control"], portfolios["candidate"]
    if control["stocks"] != candidate["stocks"]:
        raise ResearchGateError("el bloque ETF debe ser idéntico")
    comparable = copy.deepcopy(candidate["crypto"])
    for key, value in CANDIDATE_ONLY.items():
        if comparable["params"].get(key) != value:
            raise ResearchGateError("la candidata no es Donchian 55/20 con partes iguales y sin régimen")
        comparable["params"].pop(key, None)
    comparable["params"]["regime_asset"] = control["crypto"]["params"]["regime_asset"]
    if comparable != control["crypto"]:
        raise ResearchGateError("solo cambian la señal, el reparto y el régimen")
    for blocks in portfolios.values():
        for name, sc in blocks.items():
            if sc.get("paper_broker") != "sim" or "live_broker" in sc or sc.get("capital") != 500.0:
                raise ResearchGateError("solo SimBroker aislado con 500 virtuales por bloque")
            if not sc.get("enabled") or sc.get("compound") is not True or sc.get("execution", {}).get("maker_first"):
                raise ResearchGateError("ejecución experimental incompatible")
            if sc.get("kill_drawdown") != (0.45 if name == "crypto" else 0.25):
                raise ResearchGateError("los límites de protección no se relajan")
            cost = plan["costs"][name]["base"]
            if abs(sc["fee"] + sc["slippage"] - cost) > 1e-10:
                raise ResearchGateError("costo base no corresponde a la simulación")
