"""Ejecuta el plan fijo de rotación sobre originales verificados, sin red ni estado.

La política AVAX usa la función compartida ya existente. Este lanzador no cambia
parámetros, selecciona máximos del grid ni activa una estrategia.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import pandas as pd
import yaml

from lab import data, research_multi
from lab.experiments import ExperimentRun, ResearchGateError, file_hash
from lab.research_data import apply_availability_policy


ROOT = Path(__file__).resolve().parents[2]
NAMES = {"crypto_prices.csv", "crypto_mcap.csv", "etf_prices.csv"}


def verified_sources(source: Path, expected: dict, evidence: Path, policy: dict) -> dict:
    if set(expected) != NAMES:
        raise ResearchGateError("faltan entradas congeladas o hay entradas no declaradas")
    raw = {}
    for name, digest in expected.items():
        path = source / name
        if not path.is_file() or path.is_symlink() or file_hash(path) != digest:
            raise ResearchGateError(f"la entrada original cambió: {name}")
        raw[name] = path.read_bytes()
        # Verificar los bytes leídos, además del archivo: evita una lectura mixta.
        import hashlib
        if hashlib.sha256(raw[name]).hexdigest() != digest:
            raise ResearchGateError(f"la entrada cambió durante la lectura: {name}")
    if file_hash(evidence) != policy["evidence_sha256"]:
        raise ResearchGateError("la evidencia de disponibilidad cambió")
    raw["availability_evidence.json"] = evidence.read_bytes()
    if __import__("hashlib").sha256(raw["availability_evidence.json"]).hexdigest() != policy["evidence_sha256"]:
        raise ResearchGateError("la evidencia cambió durante la lectura")
    return raw


def corrected_csv(raw: bytes, policy: dict) -> tuple[bytes, dict]:
    prices = pd.read_csv(io.BytesIO(raw), index_col=0, parse_dates=True)
    derived, audit = apply_availability_policy(prices, policy)
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    avax = rows[0].index("AVAX")
    for row in rows[1:]:
        if pd.Timestamp(row[0]) < pd.Timestamp(policy["available_from"]):
            row[avax] = ""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    result = buffer.getvalue().encode("utf-8")
    actual = pd.read_csv(io.BytesIO(result), index_col=0, parse_dates=True)
    pd.testing.assert_frame_equal(actual, derived, check_exact=True)
    # El texto numérico de los otros activos y de AVAX posterior queda idéntico.
    return result, audit


def prepare_inputs(execution: ExperimentRun, source: Path) -> Path:
    meta = execution.proof["metadata"]
    policy = meta["availability_policy"]
    evidence = ROOT / "reports/data_quality/avax_spot_availability.json"
    raw = verified_sources(source, meta["source_sha256"], evidence, policy)
    crypto, audit = corrected_csv(raw["crypto_prices.csv"], policy)
    if audit["quarantined_count"] != 2:
        raise ResearchGateError("el panel no contiene las dos observaciones declaradas")
    for frame, names in ((pd.read_csv(io.BytesIO(crypto), index_col=0, parse_dates=True),
                          research_multi.BITSO_TRADABLE),
                         (pd.read_csv(io.BytesIO(raw["etf_prices.csv"]), index_col=0, parse_dates=True), None)):
        for asset in (names or frame.columns):
            if asset not in frame:
                raise ResearchGateError(f"falta el activo declarado: {asset}")
            observed = frame[asset].dropna()
            if not len(observed) or (observed <= 0).any():
                raise ResearchGateError(f"precios inválidos: {asset}")
            if frame.loc[observed.index[0]:observed.index[-1], asset].isna().any():
                raise ResearchGateError(f"huecos internos no declarados: {asset}")
    originals = execution.directory / "source_inputs"
    originals.mkdir()
    for name, payload in raw.items():
        (originals / name).write_bytes(payload)
    derived = execution.directory / "derived_inputs"
    derived.mkdir()
    for name in NAMES:
        (derived / name).write_bytes(crypto if name == "crypto_prices.csv" else raw[name])
    audit["evidence_verified_by_launcher"] = True
    audit["source_sha256"] = meta["source_sha256"]
    audit["derived_sha256"] = {name: file_hash(derived / name) for name in sorted(NAMES)}
    (execution.directory / "data_quality_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    execution.manifest["availability_correction"] = audit
    execution._save_manifest()
    execution.event("availability_policy_applied", quarantined_count=2,
                    evidence_sha256=policy["evidence_sha256"],
                    source_sha256=audit["source_sha256"], derived_sha256=audit["derived_sha256"])
    return derived


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration-commit", required=True)
    parser.add_argument("--source-cache", type=Path, required=True)
    args = parser.parse_args(argv)
    prereg = ROOT / "reports/rotation_v2_preregistro.md"
    declared = json.loads((ROOT / "reports/rotation_v2_plan.json").read_text())
    meta = yaml.safe_load(prereg.read_text().split("---", 2)[1])
    config, variants = research_multi.research_plan(universe="bitso", rotation_buffer=0.15)
    if (declared["config"] != config or declared["variants"] != variants
            or any(declared[key] != meta[key] for key in ("availability_policy", "source_sha256"))):
        raise ResearchGateError("el plan y las entradas difieren del preregistro")
    execution = ExperimentRun(ROOT, "rotation-v2", prereg, args.preregistration_commit,
                              config, variants, ROOT / "reports/experiments",
                              ROOT / "reports/experiments/ledger.jsonl")
    print(json.dumps({"run_id": execution.run_id, "directory": str(execution.directory),
                      "status": "started"}), flush=True)
    previous = data.DATA_DIR
    try:
        data.DATA_DIR = prepare_inputs(execution, args.source_cache)
        result = research_multi.run(False, execution=execution)
        comparison = result["crypto"]["rotation_comparison"]
        decision = {"selected_for_operation": "control",
                    "candidate_retrospective_pass": comparison["retrospective_checks_pass"],
                    "candidate_promoted": False, "live_authorized": False,
                    "reason": ("requiere equivalencia operable y 28 días prospectivos"
                               if comparison["retrospective_checks_pass"]
                               else "la candidata no cumple todos los criterios declarados"),
                    "checks": comparison["checks"]}
        (execution.directory / "decision.json").write_text(json.dumps(decision, indent=2) + "\n")
        execution.finish("completed")
        print(json.dumps({"run_id": execution.run_id, "status": "completed",
                          "comparison": comparison, "decision": decision}), flush=True)
    except BaseException as exc:
        (execution.directory / "failure.json").write_text(json.dumps(
            {"type": type(exc).__name__, "message": str(exc)}, indent=2) + "\n")
        execution.finish("failed")
        raise
    finally:
        data.DATA_DIR = previous


if __name__ == "__main__":
    main()
