"""Preregistros verificables, entradas congeladas y registro de investigación.

Este módulo nunca cambia configuración del bot ni autoriza dinero real. Los gates
se aplican antes de descargar datos o calcular rendimientos en research_multi.
"""
from __future__ import annotations

import hashlib
import copy
from importlib.metadata import PackageNotFoundError, version
import json
import os
import platform
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import yaml


class ResearchGateError(ValueError):
    pass


class _PreregistrationLoader(yaml.SafeLoader):
    """Keep date metadata as its source text so the verified proof remains JSON-safe."""


_PreregistrationLoader.add_constructor(
    "tag:yaml.org,2002:timestamp", yaml.SafeLoader.construct_scalar)


def runtime_versions() -> dict:
    packages = {}
    for name in ("numpy", "pandas", "scipy", "scikit-learn", "ccxt", "PyYAML", "requests"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages}


def canonical_hash(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def variant_id(sleeve: str, params: dict, universe: str) -> str:
    return f"{sleeve}:{canonical_hash({'params': params, 'universe': universe})[:20]}"


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], check=False, capture_output=True)
    if result.returncode:
        raise ResearchGateError(f"Git no pudo verificar {' '.join(args[:2])}")
    return result.stdout


def verify_preregistration(root: Path, path: Path, commit: str, experiment_id: str,
                          config: dict, variant_ids: list[str]) -> dict:
    root, path = Path(root).resolve(), Path(path).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ResearchGateError("el preregistro debe estar dentro del repositorio") from exc
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ResearchGateError("se requiere el SHA completo del commit del preregistro")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    if commit.lower() == head:
        raise ResearchGateError("el preregistro debe ser un commit anterior al código ejecutado")
    _git(root, "merge-base", "--is-ancestor", commit, head)
    blob = _git(root, "show", f"{commit}:{relative}")
    if not path.is_file() or path.read_bytes() != blob:
        raise ResearchGateError("el preregistro difiere del contenido comprometido")
    # Los resultados tienen su propio ledger; el código y los documentos deben ser reproducibles.
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all", "--", ".",
                 ":(exclude)reports/experiments/**")
    if dirty.strip():
        raise ResearchGateError("el árbol de trabajo contiene cambios sin commit")
    text = blob.decode("utf-8")
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        raise ResearchGateError("falta frontmatter del preregistro")
    meta = yaml.load(text.split("---", 2)[1], Loader=_PreregistrationLoader)
    if not isinstance(meta, dict) or meta.get("status") != "approved":
        raise ResearchGateError("preregistro en borrador o sin aprobar")
    if meta.get("experiment_id") != experiment_id or meta.get("protocol_version") != 1:
        raise ResearchGateError("identidad o versión de preregistro inválida")
    if meta.get("config_sha256") != canonical_hash(config):
        raise ResearchGateError("la configuración no coincide con el preregistro")
    declared = meta.get("variant_ids")
    if not isinstance(declared, list) or sorted(declared) != sorted(variant_ids):
        raise ResearchGateError("el grid no coincide exactamente con las variantes declaradas")
    criteria = meta.get("criteria")
    required = {"walk_forward", "placebo", "bootstrap", "cost_stress", "drawdown"}
    if not isinstance(criteria, dict) or not required.issubset(criteria) or not all(criteria.values()):
        raise ResearchGateError("faltan criterios falsables de validación")
    if not meta.get("hypothesis") or not meta.get("evaluation_window"):
        raise ResearchGateError("faltan hipótesis y periodo de evaluación")
    return {"path": relative, "commit": commit.lower(), "sha256": hashlib.sha256(blob).hexdigest(),
            "code_commit": head, "criteria": criteria, "metadata": meta}


def append_event(path: Path, event: dict) -> dict:
    """JSONL con bloqueo entre procesos, fsync y cadena de hashes; detecta ediciones."""
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        previous = None
        for line in stream:
            record = json.loads(line)
            checksum = record.pop("event_sha256")
            if record.get("previous_sha256") != previous or canonical_hash(record) != checksum:
                raise ResearchGateError("el ledger no conserva su cadena de integridad")
            previous = checksum
        record = {**event, "recorded_at": datetime.now(timezone.utc).isoformat(),
                  "previous_sha256": previous}
        record["event_sha256"] = canonical_hash(record)
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        return record


class ExperimentRun:
    """Una ejecución registrada; distinguir declared, started, completed y failed."""

    def __init__(self, root: Path, experiment_id: str, preregistration: Path, commit: str,
                 config: dict, variants: list[dict], output_root: Path, ledger: Path):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", experiment_id):
            raise ResearchGateError("experiment-id inválido")
        ids = [v["id"] for v in variants]
        if len(ids) != len(set(ids)):
            raise ResearchGateError("hay variantes duplicadas")
        self.proof = verify_preregistration(root, preregistration, commit, experiment_id, config, ids)
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
        self.experiment_id, self.config_hash = experiment_id, canonical_hash(config)
        self.directory = Path(output_root) / experiment_id / self.run_id
        self.ledger = Path(ledger)
        self.variants = {v["id"]: copy.deepcopy(v) for v in variants}
        self.variant_states = dict.fromkeys(ids, "declared")
        self.directory.mkdir(parents=True, exist_ok=False)
        self.datasets: dict[str, dict] = {}
        self.manifest = {"protocol_version": 1, "experiment_id": experiment_id, "run_id": self.run_id,
                         "config": copy.deepcopy(config), "config_sha256": self.config_hash,
                         "preregistration": self.proof, "variants": copy.deepcopy(variants), "datasets": self.datasets,
                         "runtime": runtime_versions(),
                         "status": "started", "live_authorized": False}
        self._save_manifest()
        self.event("run_started", declared_variant_ids=ids)

    def _save_manifest(self):
        target = self.directory / "manifest.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.manifest, indent=2, sort_keys=True,
                                        ensure_ascii=False, allow_nan=False) + "\n")
        temporary.replace(target)

    def event(self, kind: str, **fields):
        return append_event(self.ledger, {"kind": kind, "experiment_id": self.experiment_id,
                            "run_id": self.run_id, "config_sha256": self.config_hash, **fields})

    def freeze_dataset(self, name: str, prices: pd.DataFrame, eligible: pd.DataFrame,
                       provenance: dict) -> dict:
        if name in self.datasets:
            raise ResearchGateError(f"dataset {name} ya fue congelado en esta ejecución")
        if not prices.index.equals(eligible.index) or not prices.columns.equals(eligible.columns):
            raise ResearchGateError("precios y elegibilidad no están alineados")
        if not len(prices) or not prices.index.is_unique or not prices.index.is_monotonic_increasing:
            raise ResearchGateError("índice de precios vacío, repetido o desordenado")
        inputs = self.directory / "inputs"
        inputs.mkdir(exist_ok=True)
        files = {}
        for label, frame in (("prices", prices), ("eligible", eligible)):
            path = inputs / f"{name}_{label}.csv"
            frame.to_csv(path, float_format="%.17g")
            files[label] = {"file": str(path.relative_to(self.directory)), "sha256": file_hash(path)}
        manifest = {"files": files, "first": str(prices.index[0]), "last": str(prices.index[-1]),
                    "rows": len(prices), "assets": list(prices.columns),
                    "missing_by_asset": {k: int(v) for k, v in prices.isna().sum().items()},
                    "provenance": provenance}
        manifest["dataset_sha256"] = canonical_hash(manifest)
        self.datasets[name] = manifest
        self._save_manifest()
        self.event("dataset_frozen", dataset=name, dataset_sha256=manifest["dataset_sha256"])
        return manifest

    def variant(self, variant: str, status: str):
        if variant not in self.variants or status not in {"started", "completed", "failed"}:
            raise ResearchGateError("variante no declarada o estado inválido")
        previous = self.variant_states[variant]
        if (status == "started" and previous != "declared") or (status != "started" and previous != "started"):
            raise ResearchGateError("transición de variante inválida")
        self.event(f"variant_{status}", variant_id=variant)
        self.variant_states[variant] = status

    def finish(self, status: str):
        if status not in {"completed", "failed"}:
            raise ValueError("estado de cierre inválido")
        if status == "completed" and any(state != "completed" for state in self.variant_states.values()):
            raise ResearchGateError("no se ejecutaron todas las variantes declaradas")
        self.manifest["status"] = status
        self.manifest["variant_states"] = self.variant_states
        self.manifest["artifacts"] = [
            {"file": str(path.relative_to(self.directory)), "sha256": file_hash(path)}
            for path in sorted(self.directory.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        ]
        self._save_manifest()
        self.event(f"run_{status}", manifest_sha256=file_hash(self.directory / "manifest.json"))


def promotion_gate(validation: dict, paper: dict, now: datetime | None = None) -> dict:
    """Solo aptitud para revisión humana; jamás cambia mode ni autoriza órdenes reales.

    Las evidencias deben corresponder al mismo artefacto/configuración y reunir
    28 días completos observados, además de todos los gates cuantitativos.
    """
    now = now or datetime.now(timezone.utc)
    reasons = []
    required = ("walk_forward", "placebo", "bootstrap", "cost_stress", "drawdown", "causality")
    if any(validation.get("checks", {}).get(key) is not True for key in required):
        reasons.append("validación cuantitativa incompleta o fallida")
    identity = ("config_sha256", "code_commit", "run_id")
    if any(not validation.get(key) or validation.get(key) != paper.get(key) for key in identity):
        reasons.append("las evidencias no corresponden a la misma versión")
    try:
        start = datetime.fromisoformat(paper["started_at"])
        end = datetime.fromisoformat(paper["ended_at"])
        if start.tzinfo is None or end.tzinfo is None or not start <= end <= now:
            raise ValueError("fechas inválidas")
        if (end - start).total_seconds() < 28 * 86400 or paper.get("observed_days", 0) < 28:
            reasons.append("faltan 28 días completos en simulado")
    except (KeyError, TypeError, ValueError):
        reasons.append("faltan fechas verificables del periodo simulado")
    if paper.get("complete") is not True or paper.get("unresolved_errors", 1) != 0:
        reasons.append("simulado incompleto o con incidencias sin resolver")
    return {"ready_for_human_review": not reasons, "live_authorized": False, "reasons": reasons}
