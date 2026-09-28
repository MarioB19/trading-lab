"""Content-addressed Git proof for preregistered paper in images without .git.

The operator pins TRADING_LAB_BUILD_ID (and the image digest at deployment).
This is an ancestry/content proof anchored to that commit, not a signature or
authorization for real orders. Generate outside the checkout before packaging.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import yaml

from .experiments import ResearchGateError, _git, canonical_hash, verify_preregistration


def _fail(message):
    raise ResearchGateError("attestation: " + message)


def _relative(root: Path, path: Path) -> str:
    try:
        relative = Path(path).absolute().relative_to(root.resolve())
    except ValueError:
        _fail("el artefacto debe estar dentro del código empaquetado")
    if ".." in relative.parts or any((root / Path(*relative.parts[:i])).is_symlink()
                                     for i in range(1, len(relative.parts) + 1)):
        _fail("ruta insegura o enlace simbólico")
    return relative.as_posix()


def _oid(kind: str, raw: bytes) -> str:
    return hashlib.sha1(f"{kind} {len(raw)}\0".encode() + raw).hexdigest()


def _commit(raw: bytes) -> tuple[str, list[str]]:
    headers = raw.split(b"\n\n", 1)[0].decode("utf-8").splitlines()
    trees = [line[5:] for line in headers if line.startswith("tree ")]
    parents = [line[7:] for line in headers if line.startswith("parent ")]
    if len(trees) != 1 or any(not re.fullmatch(r"[0-9a-f]{40}", x) for x in trees + parents):
        _fail("objeto commit inválido")
    return trees[0], parents


def _tree(raw: bytes) -> dict[str, tuple[str, str]]:
    result, offset = {}, 0
    while offset < len(raw):
        end = raw.find(b"\0", offset)
        if end < 0 or end + 21 > len(raw):
            _fail("objeto tree truncado")
        mode, name = raw[offset:end].decode("utf-8").split(" ", 1)
        if name in result or name in (".", "..") or "/" in name or not name:
            _fail("entrada tree inválida")
        result[name] = mode, raw[end + 1:end + 21].hex()
        offset = end + 21
    return result


def _metadata(blob: bytes, plan: dict, variant_ids: list[str]) -> dict:
    text = blob.decode("utf-8")
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        _fail("preregistro sin frontmatter")
    meta = yaml.safe_load(text.split("---", 2)[1])
    if not isinstance(meta, dict) or meta.get("status") != "approved":
        _fail("preregistro no aprobado")
    if meta.get("protocol_version") != 1 or meta.get("experiment_id") != plan["experiment_id"]:
        _fail("identidad de preregistro inválida")
    if meta.get("config_sha256") != canonical_hash(plan):
        _fail("hash del plan difiere del preregistro")
    if sorted(meta.get("variant_ids", [])) != sorted(variant_ids):
        _fail("variantes diferentes del preregistro")
    required = {"walk_forward", "placebo", "bootstrap", "cost_stress", "drawdown"}
    criteria = meta.get("criteria")
    if (not isinstance(criteria, dict) or not required.issubset(criteria)
            or not all(criteria.values()) or not meta.get("hypothesis") or not meta.get("evaluation_window")):
        _fail("preregistro incompleto")
    return meta


def generate_attestation(root: Path, plan_path: Path, preregistration: Path,
                         commit: str, plan: dict, variants: list[dict]) -> dict:
    """Requires an entirely clean checkout; no market data or experiment runs."""
    root = Path(root).resolve()
    if _git(root, "status", "--porcelain", "--untracked-files=all").strip():
        _fail("la generación exige git limpio, incluidos archivos sin seguimiento")
    proof = verify_preregistration(root, preregistration, commit, plan["experiment_id"],
                                   plan, [v["id"] for v in variants])
    objects = {}

    def add(oid, kind):
        if oid not in objects:
            raw = _git(root, "cat-file", kind, oid)
            if _oid(kind, raw) != oid:
                _fail("Git devolvió un objeto inconsistente")
            objects[oid] = {"type": kind, "data": base64.b64encode(raw).decode()}
        return base64.b64decode(objects[oid]["data"])

    head = proof["code_commit"]
    commits = _git(root, "rev-list", "--ancestry-path", f"{commit}..{head}").decode().split()
    for oid in commits + [commit.lower()]:
        add(oid, "commit")
    root_tree = _commit(add(head, "commit"))[0]
    add(root_tree, "tree")
    # Tree objects contain filenames and hashes only; no unrelated file contents.
    for entry in _git(root, "ls-tree", "-r", "-t", "-z", head).split(b"\0"):
        if entry:
            info, _ = entry.split(b"\t", 1)
            _, kind, oid = info.decode().split()
            if kind == "tree":
                add(oid, kind)

    prereg_path = _relative(root, preregistration)
    old_tree = _commit(add(commit.lower(), "commit"))[0]
    for part in prereg_path.split("/")[:-1]:
        entries = _tree(add(old_tree, "tree"))
        mode, old_tree = entries[part]
        if mode != "40000":
            _fail("ruta preregistrada no es un directorio")
    add(old_tree, "tree")
    artifacts = {}
    src_files = _git(root, "ls-tree", "-r", "--name-only", "-z", head, "--", "src").split(b"\0")
    paths = [p.decode() for p in src_files if p]
    paths += ["config.yaml", _relative(root, plan_path), prereg_path]
    for path in sorted(set(paths)):
        _relative(root, root / path)
        artifacts[path] = hashlib.sha256((root / path).read_bytes()).hexdigest()
    attestation = {"schema_version": 1, "proof_kind": "git-content-ancestry-v1",
                   "code_commit": head, "preregistration_commit": commit.lower(),
                   "plan_path": _relative(root, plan_path), "preregistration_path": prereg_path,
                   "config_sha256": canonical_hash(plan), "artifacts": artifacts, "objects": objects}
    # The exact verifier used in the image also checks generator completeness.
    verify_attestation(root, attestation, plan_path, preregistration, commit, plan,
                       [v["id"] for v in variants], head, allow_interpreter_cache=True)
    return attestation


def verify_attestation(root: Path, attestation: Path | dict, plan_path: Path,
                       preregistration: Path, commit: str, plan: dict,
                       variant_ids: list[str], expected_code_commit: str | None = None,
                       *, allow_interpreter_cache: bool = False) -> dict:
    """Verify Git ancestry and packaged bytes without invoking Git or the network."""
    root = Path(root).resolve()
    document = (json.loads(Path(attestation).read_text()) if not isinstance(attestation, dict)
                else attestation)
    if (not isinstance(document, dict) or not isinstance(document.get("objects"), dict)
            or not isinstance(document.get("artifacts"), dict)):
        _fail("documento o inventario inválido")
    expected = expected_code_commit or os.environ.get("TRADING_LAB_BUILD_ID", "")
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        _fail("se requiere TRADING_LAB_BUILD_ID con SHA completo fijado por la imagen")
    if (document.get("schema_version") != 1 or document.get("proof_kind") != "git-content-ancestry-v1"
            or document.get("code_commit") != expected or document.get("preregistration_commit") != commit.lower()
            or document.get("config_sha256") != canonical_hash(plan)):
        _fail("identidad, commit o plan no coinciden")
    paths = {"plan_path": _relative(root, plan_path), "preregistration_path": _relative(root, preregistration)}
    if any(document.get(key) != value for key, value in paths.items()):
        _fail("rutas diferentes de los artefactos registrados")
    if canonical_hash(yaml.safe_load(plan_path.read_text())) != canonical_hash(plan):
        _fail("el plan cargado difiere de su archivo empaquetado")
    objects = {}
    for oid, value in document.get("objects", {}).items():
        try:
            kind, raw = value["type"], base64.b64decode(value["data"], validate=True)
        except (KeyError, ValueError, TypeError) as exc:
            raise ResearchGateError("attestation: objeto codificado inválido") from exc
        if kind not in ("commit", "tree") or _oid(kind, raw) != oid:
            _fail("hash de objeto Git inválido")
        objects[oid] = kind, raw

    def obj(oid, kind):
        if oid not in objects or objects[oid][0] != kind:
            _fail("objeto requerido ausente")
        return objects[oid][1]

    if expected == commit.lower():
        _fail("preregistro debe preceder estrictamente al código")
    visited, pending = set(), [expected]
    while pending:
        oid = pending.pop()
        if oid in visited:
            continue
        visited.add(oid)
        _, parents = _commit(obj(oid, "commit"))
        pending.extend(p for p in parents if p in objects and p not in visited)
    if commit.lower() not in visited:
        _fail("no hay prueba de ascendencia del preregistro")

    def entry(tree, path):
        parts = path.split("/")
        for i, part in enumerate(parts):
            entries = _tree(obj(tree, "tree"))
            if part not in entries:
                _fail("artefacto ausente del árbol comprometido")
            mode, oid = entries[part]
            if i < len(parts) - 1 and mode != "40000":
                _fail("ruta Git no es directorio")
            tree = oid
        return mode, oid

    code_tree = _commit(obj(expected, "commit"))[0]
    source_tree = entry(code_tree, "src")
    if source_tree[0] != "40000":
        _fail("src no es un árbol Git")
    source_files = set()

    def walk(oid, prefix):
        for name, (mode, child) in _tree(obj(oid, "tree")).items():
            path = f"{prefix}/{name}"
            if mode == "40000":
                walk(child, path)
            elif mode in ("100644", "100755"):
                source_files.add(path)
            else:
                _fail("src contiene enlaces o submódulos")
    walk(source_tree[1], "src")
    # Packaged runtime disables bytecode writing; reject injectable orphan .pyc.
    caches = [p for p in (root / "src").rglob("*")
              if p.is_file() and ("__pycache__" in p.parts or p.suffix == ".pyc")]
    if caches and not allow_interpreter_cache:
        _fail("la imagen contiene bytecode no comprometido; usar PYTHONDONTWRITEBYTECODE=1")
    actual_source = {p.relative_to(root).as_posix() for p in (root / "src").rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
                     and not (allow_interpreter_cache and any(part.endswith(".egg-info") for part in p.parts))}
    if actual_source != source_files:
        _fail("el conjunto de archivos src difiere del commit")
    required = source_files | {"config.yaml", *paths.values()}
    if set(document.get("artifacts", {})) != required:
        _fail("inventario de artefactos incompleto o diferente")
    for path in required:
        _relative(root, root / path)
        mode, oid = entry(code_tree, path)
        raw = (root / path).read_bytes()
        if (mode not in ("100644", "100755") or _oid("blob", raw) != oid
                or hashlib.sha256(raw).hexdigest() != document["artifacts"][path]):
            _fail(f"contenido modificado: {path}")
    old_tree = _commit(obj(commit.lower(), "commit"))[0]
    old_mode, old_blob = entry(old_tree, paths["preregistration_path"])
    prereg_raw = preregistration.read_bytes()
    if old_mode not in ("100644", "100755") or old_blob != _oid("blob", prereg_raw):
        _fail("preregistro distinto de su commit anterior")
    meta = _metadata(prereg_raw, plan, variant_ids)
    return {"path": paths["preregistration_path"], "commit": commit.lower(),
            "sha256": hashlib.sha256(prereg_raw).hexdigest(), "code_commit": expected,
            "criteria": meta["criteria"], "metadata": meta,
            "proof_kind": document["proof_kind"], "attestation_sha256": canonical_hash(document)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--preregistration-commit", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--attestation", type=Path)
    args = parser.parse_args(argv)
    from .aggressive_plan import comparison_plan, preregistration_path
    from .data import ROOT
    try:
        plan, variants = comparison_plan(args.plan)
        prereg = preregistration_path(plan)
        if args.action == "generate":
            if not args.output:
                parser.error("generate exige --output fuera del repositorio")
            if args.output.resolve().is_relative_to(ROOT.resolve()):
                _fail("el output debe estar fuera del repositorio para evitar autorreferencia")
            result = generate_attestation(ROOT, args.plan, prereg, args.preregistration_commit, plan, variants)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"output": str(args.output), "code_commit": result["code_commit"],
                              "attestation_sha256": canonical_hash(result)}))
        else:
            if not args.attestation:
                parser.error("verify exige --attestation")
            result = verify_attestation(ROOT, args.attestation, args.plan, prereg,
                                        args.preregistration_commit, plan, [v["id"] for v in variants])
            print(json.dumps(result, indent=2))
        return 0
    except (ResearchGateError, ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Attestation bloqueada: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
