"""Plan prospectivo fijo; describirlo no descarga datos ni calcula rendimiento."""
from __future__ import annotations

import json
from pathlib import Path

from .data import ROOT
from .experiments import ResearchGateError, canonical_hash, file_hash

EXPERIMENT_ID = "rotation-paper-v1"
PLAN_SHA256 = "5a700b6113c049a50ee8ac9b45366391514c46ed43eb30ff3503f75c8e4cf0e3"
CHECKS = {"net_cagr", "sharpe", "drawdown", "turnover", "annual_consistency",
          "bootstrap", "placebo", "cost_stress"}


def validate_plan(plan: dict):
    # La identidad completa fija costos, capital, fuentes, límites y criterios.
    if canonical_hash(plan) != PLAN_SHA256:
        raise ResearchGateError("el plan prospectivo de rotación cambió después del preregistro")
    evidence = plan["historical_evidence"]
    contents = {}
    for name in ("manifest", "results"):
        item = evidence[name]
        path = ROOT / item["path"]
        prefix = ROOT / "reports/experiments/rotation-v2" / evidence["run_id"]
        if (path.is_symlink() or path.resolve().parent != prefix.resolve()
                or file_hash(path) != item["sha256"]):
            raise ResearchGateError("la evidencia histórica de rotación cambió")
        contents[name] = json.loads(path.read_text())
    manifest = contents["manifest"]
    if (manifest.get("status") != "completed" or manifest.get("live_authorized") is not False
            or manifest.get("config_sha256") != evidence["config_sha256"]
            or manifest.get("run_id") != evidence["run_id"]
            or len(manifest.get("variant_states", {})) != 90
            or set(manifest["variant_states"].values()) != {"completed"}):
        raise ResearchGateError("la comparación histórica no está completa")
    comparison = contents["results"]["crypto"]["rotation_comparison"]
    if (set(comparison["checks"]) != CHECKS or not all(v is True for v in comparison["checks"].values())
            or comparison.get("promoted") is not False):
        raise ResearchGateError("la candidata no superó todos los criterios históricos")
