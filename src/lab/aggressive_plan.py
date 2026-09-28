"""Frozen, credential-free specification for a paired paper experiment.

Describing this plan never fetches market data or computes performance.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

from .bot import SLEEVE_DEFAULTS, load_config, sleeve_params
from .data import ROOT
from .experiments import ResearchGateError, canonical_hash, file_hash, variant_id
from .portfolio import PortfolioParams

PLAN_PATH = ROOT / "configs/experiments/aggressive_v1.yaml"
EXPERIMENT_ID = "aggressive-v1"
PREREGISTRATION = ROOT / "reports/aggressive_v1_preregistro.md"


def comparison_plan() -> tuple[dict, list[dict]]:
    """Return independent copies of the exact plan and its two declared variants."""
    plan = yaml.safe_load(PLAN_PATH.read_text())
    validate_plan(plan)
    variants = []
    for role in ("control", "aggressive"):
        params = PortfolioParams.from_dict(plan["portfolios"][role]["crypto"]["params"]).to_dict()
        variants.append({"id": variant_id("crypto", params, "bitso"), "sleeve": "crypto",
                         "role": role, "params": params, "universe": "bitso", "status": "declared"})
    return copy.deepcopy(plan), variants


def validate_plan(plan: dict) -> None:
    if plan.get("mode") != "paper" or plan.get("live_authorized") is not False:
        raise ResearchGateError("el experimento admite exclusivamente dinero simulado")
    if plan.get("experiment_id") != EXPERIMENT_ID or plan.get("protocol_version") != 1:
        raise ResearchGateError("identidad de experimento desconocida")
    if plan.get("initial_capital_usd") != 1000.0:
        raise ResearchGateError("el capital virtual debe ser idéntico y preregistrado")
    if plan.get("max_price_jump") != .40:
        raise ResearchGateError("el control de precios debe conservarse")
    portfolios = plan.get("portfolios", {})
    if set(portfolios) != {"control", "aggressive"}:
        raise ResearchGateError("se requieren exactamente control y experimental")
    for blocks in portfolios.values():
        if set(blocks) != {"crypto", "stocks"}:
            raise ResearchGateError("la comparación requiere ambos bloques")
        for name, sc in blocks.items():
            if sc.get("paper_broker") != "sim" or "live_broker" in sc or sc.get("capital") != 500.0:
                raise ResearchGateError("solo SimBroker aislado con 500 virtuales por bloque")
            if not sc.get("enabled") or sc.get("compound") is not True or sc.get("execution", {}).get("maker_first"):
                raise ResearchGateError("ejecución experimental incompatible")
            if sc.get("kill_drawdown") != (0.45 if name == "crypto" else 0.25):
                raise ResearchGateError("los límites de protección no se relajan")
    control, aggressive = portfolios["control"], portfolios["aggressive"]
    if control["stocks"] != aggressive["stocks"]:
        raise ResearchGateError("el bloque ETF debe ser idéntico")
    p0, p1 = control["crypto"]["params"], aggressive["crypto"]["params"]
    if (p0["top_k"], p0["vol_target"], p1["top_k"], p1["vol_target"]) != (5, .40, 3, .60):
        raise ResearchGateError("candidatas distintas del protocolo agresivo v1")
    comparable = copy.deepcopy(aggressive["crypto"])
    comparable["params"].update(top_k=5, vol_target=.40)
    if comparable != control["crypto"]:
        raise ResearchGateError("solo cambian top_k y vol_target")
    if control["crypto"]["universe"] != SLEEVE_DEFAULTS["crypto"]["universe"]:
        raise ResearchGateError("universo distinto del subconjunto Bitso declarado")
    for name, sc in control.items():
        cost = plan["costs"][name]["base"]
        if abs(sc["fee"] + sc["slippage"] - cost) > 1e-10:
            raise ResearchGateError("costo base no corresponde a la simulación")


def validate_registered_variants(plan: dict) -> None:
    """Research/CI check; paper runtime does not import SciPy to read its plan."""
    from .research_multi import SLEEVES, grid_variants, params_for

    grid, _ = grid_variants(SLEEVES["crypto"])
    registered = {canonical_hash(params_for("crypto", params).to_dict()) for params in grid}
    for blocks in plan["portfolios"].values():
        params = PortfolioParams.from_dict(blocks["crypto"]["params"]).to_dict()
        if canonical_hash(params) not in registered:
            raise ResearchGateError("variante fuera del grid de SLEEVES")


def assert_current_control(plan: dict) -> None:
    """Refuse to compare to a silently changed production baseline."""
    if file_hash(ROOT / "config.yaml") != plan["baseline_config_sha256"]:
        raise ResearchGateError("config.yaml cambió: se necesita un nuevo protocolo, no adaptar el control a posteriori")
    cfg = load_config(ROOT / "config.yaml")
    if cfg["mode"] != "paper":
        raise ResearchGateError("el modo operativo actual no es paper")
    if cfg["max_price_jump"] != plan["max_price_jump"]:
        raise ResearchGateError("el control de saltos de precio cambió")
    for name, sc in plan["portfolios"]["control"].items():
        actual = cfg["sleeves"][name]
        for key in ("strategy", "universe", "capital", "band", "kill_drawdown", "compound"):
            if actual[key] != sc[key]:
                raise ResearchGateError(f"control distinto de la estrategia actual: {name}.{key}")
        if canonical_hash(sleeve_params(actual).to_dict()) != canonical_hash(sc["params"]):
            raise ResearchGateError(f"parámetros del control cambiaron: {name}")
        if name == "stocks" and actual.get("mix") != sc.get("mix"):
            raise ResearchGateError("la mezcla ETF del control cambió")


def isolated_directory(path: Path) -> Path:
    """No experimental writer may use the active repo state/data or its ancestors."""
    path = Path(path).resolve()
    if path == ROOT.resolve() or path in ROOT.resolve().parents:
        raise ResearchGateError("el destino experimental debe ser un directorio dedicado")
    protected_paths = [ROOT / name for name in ("state", "data", "src", ".git", "infra", "configs")]
    protected_paths.append(Path("/var/lib/trading-lab"))
    if os.environ.get("TRADING_LAB_DATA_DIR"):
        protected_paths.append(Path(os.environ["TRADING_LAB_DATA_DIR"]))
    for protected in map(Path.resolve, protected_paths):
        if path == protected or path in protected.parents or protected in path.parents:
            raise ResearchGateError("el destino experimental invade archivos operativos o código")
    for parent in (path, *path.parents):
        if any((parent / marker).exists() for marker in ("trading.sqlite3", "runtime.yaml", "worker.enabled")):
            raise ResearchGateError("el destino pertenece a un runtime operativo")
    return path
