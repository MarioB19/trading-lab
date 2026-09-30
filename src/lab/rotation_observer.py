"""Observador local aislado de la candidata fija, con respaldo e identidad exacta.

No accede a cuentas ni al runtime operativo. Se invoca periódicamente desde un
paquete congelado; un reintento no cuenta como otra observación.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .aggressive_plan import comparison_plan, isolated_directory
from .data import ROOT
from .experiments import ResearchGateError
from .paper_comparison import run_once, status
from .paper_ops import backup, verify_backup

PLAN = ROOT / "configs/experiments/rotation_paper_v1.yaml"
ATTESTATION = ROOT / "reports/attestations/rotation-paper-v1.json"


def prospective_decision(report: dict) -> dict:
    control = report.get("portfolios", {}).get("control", {}).get("blocks", {}).get("crypto", {})
    candidate = report.get("portfolios", {}).get("candidate", {}).get("blocks", {}).get("crypto", {})
    checks = {
        "identity": report.get("experiment_id") == "rotation-paper-v1" and report.get("mode") == "paper"
                    and report.get("live_authorized") is False,
        "observation": report.get("complete") is True and report.get("observed_days", 0) >= 28
                       and report.get("elapsed_days", 0) >= 28,
        "continuity": not report.get("observation_gaps") and report.get("unresolved_errors") == 0
                      and report.get("health", {}).get("status", "ok") == "ok",
        "net_return": bool(control) and bool(candidate)
                      and candidate["return_pct"] >= control["return_pct"],
        "drawdown": bool(control) and bool(candidate)
                    and candidate["max_drawdown_pct"] >= control["max_drawdown_pct"] - 1.0,
        # Ambos empiezan con USD500: volumen normalizado por el mismo capital
        # inicial. Esta medida prospectiva difiere del turnover del backtest.
        "turnover": bool(control) and bool(candidate) and control["traded_notional_usd"] > 0
                    and candidate["traded_notional_usd"] <= .85 * control["traded_notional_usd"],
    }
    return {"checks": checks, "paper_criteria_pass": all(checks.values()),
            "operational_execution_equivalence_verified": False,
            "ready_for_human_review": False, "candidate_promoted": False, "live_authorized": False}


def observe(commit: str, data_dir: Path, backups: Path) -> dict:
    directory = isolated_directory(backups)
    if directory == data_dir.resolve() or data_dir.resolve() in directory.parents or directory in data_dir.resolve().parents:
        raise ResearchGateError("el respaldo requiere otro directorio dedicado")
    comparison_plan(PLAN)  # verifica identidad y evidencia antes del primer fetch
    previous = status(data_dir, PLAN)
    if previous.get("complete"):
        return {"status": "observation_complete_awaiting_review", "report": previous,
                "decision": prospective_decision(previous)}
    report = run_once(commit, data_dir, fetch=True, plan_path=PLAN, attestation=ATTESTATION)
    target = directory / (report["run_id"] + "-" + report["generated_at"][:10])
    if target.exists():
        verify_backup(target)
    else:
        backup(data_dir, target)
    return {"status": "collecting_forward_observations", "report": report, "backup": str(target),
            "decision": prospective_decision(report)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration-commit", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--backups", type=Path, required=True)
    args = parser.parse_args(argv)
    result = observe(args.preregistration_commit, args.data_dir, args.backups)
    report = result["report"]
    print(json.dumps({"status": result["status"], "experiment_id": report["experiment_id"],
                      "run_id": report.get("run_id"), "observed_days": report.get("observed_days"),
                      "elapsed_days": report.get("elapsed_days"), "complete": report.get("complete"),
                      "unresolved_errors": report.get("unresolved_errors"), "live_authorized": False,
                      "backup": result.get("backup"), "decision": result["decision"]}), flush=True)


if __name__ == "__main__":
    main()
