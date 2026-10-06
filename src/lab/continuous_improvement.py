"""Daily learning from measured costs and evidence; never edits trading state.

This controller accumulates observations and priorities. Candidate testing remains
separate, preregistered and versioned. It cannot place orders or deploy a strategy.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .data import ROOT
from .experiments import (ResearchGateError, append_event, canonical_hash, file_hash,
                          promotion_gate, verify_preregistration)
from .runtime import exclusive_lock

POLICY_PATH = ROOT / "configs/research/continuous_improvement_v1.json"
PREREG_PATH = ROOT / "reports/continuous_improvement_v1_preregistro.md"
PREREG_COMMIT = "e0a3d3e74d318c098e2c80b61d759e4e9e203cf2"
DEFAULT_OUTPUT = ROOT / "runtime-data/continuous-improvement-v1"


def policy():
    return json.loads(POLICY_PATH.read_text())


def proof():
    cfg = policy()
    return verify_preregistration(ROOT, PREREG_PATH, PREREG_COMMIT,
                                 cfg["experiment_id"], cfg,
                                 [v["id"] for v in cfg["variants"]])


def _time(value):
    if not isinstance(value, str):
        raise ValueError("Falta fecha UTC verificable")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("La fecha requiere zona horaria")
    return stamp.astimezone(timezone.utc)


def _number(value, *, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Métrica numérica ausente o inválida")
    if minimum is not None and value < minimum:
        raise ValueError("Métrica fuera del rango declarado")
    return float(value)


def _output(path):
    target = Path(path).resolve()
    allowed = DEFAULT_OUTPUT.resolve()
    if target != allowed and allowed not in target.parents:
        raise ValueError("El controlador escribe solo en su directorio de investigación dedicado")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _atomic(path, value):
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.chmod(0o600)
    os.replace(temp, path)


def _archive(directory, value):
    directory.mkdir(parents=True, exist_ok=True)
    digest = canonical_hash(value)
    path = directory / (digest + ".json")
    if path.exists():
        if canonical_hash(json.loads(path.read_text())) != digest:
            raise ResearchGateError("Artefacto archivado alterado")
    else:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o600)
    return path, digest


def read_history(directory):
    ledger = Path(directory) / "ledger.jsonl"
    previous, records = None, []
    if not ledger.exists():
        return records
    for line in ledger.read_text().splitlines():
        record = json.loads(line)
        digest = record.pop("event_sha256")
        if record.get("previous_sha256") != previous or canonical_hash(record) != digest:
            raise ResearchGateError("Bitácora de mejora alterada")
        previous = digest
        records.append({**record, "event_sha256": digest})
    return records


def closed_cycles(fills, since_ms):
    """Attribute flat-to-flat cycles; do not count open positions as winners."""
    positions, cycles = {}, []
    for fill in sorted(fills, key=lambda f: f["ts"]):
        wid = fill["strategy"]
        qty, value, fee = (_number(fill[k], minimum=0) for k in ("qty", "value", "fee"))
        if qty <= 0 or fill.get("mode") != "paper" or fill.get("side") not in ("buy", "sell"):
            raise ValueError("Fill inválido o fuera de simulación")
        w = positions.setdefault(wid, {"qty": 0., "gross": 0., "fees": 0., "start_ms": fill["ts"]})
        if not w["qty"]:
            w["start_ms"] = fill["ts"]
        sign = 1 if fill["side"] == "buy" else -1
        w["qty"] += sign * qty
        w["gross"] -= sign * value
        w["fees"] += fee
        if w["qty"] < -1e-8:
            raise ValueError("Venta sin inventario propio")
        if abs(w["qty"]) <= 1e-8:
            if fill["ts"] >= since_ms:
                cycles.append({"strategy": wid, "started_ms": w["start_ms"], "closed_ms": fill["ts"],
                               "gross_pnl_usd": w["gross"], "fees_usd": w["fees"],
                               "net_pnl_usd": w["gross"] - w["fees"]})
            positions[wid] = {"qty": 0., "gross": 0., "fees": 0., "start_ms": fill["ts"]}
    return cycles


def _issues(snapshot, now, cfg):
    issues = []
    def add(key, category, priority, action, **evidence):
        issues.append({"id": key, "category": category, "base_priority": priority,
                       "action": action, "evidence": evidence,
                       "strategy_change_authorized": False})
    stamps = []
    for name, age_limit in (("pilot", cfg["pilot_max_age_seconds"]),
                            ("arena", cfg["arena_max_age_seconds"])):
        source = snapshot.get(name)
        if not isinstance(source, dict):
            add(name + ":unavailable", "technical", 1000, "Recuperar una lectura actual; no inferir resultados.")
            continue
        try:
            if source.get("mode") != "paper" or source.get("files_match") is not True:
                raise ValueError("Modo o identidad no verificados")
            _number(source["current"]["equity_usd"], minimum=0)
            _number(source["current"]["pnl_usd"])
            stamp = _time(source["as_of_utc"])
            stamps.append(stamp)
            age = (now - stamp).total_seconds()
            if not -60 <= age <= age_limit:
                raise ValueError("Observación vieja o futura")
            if source.get("healthy") is not True or source.get("reconciled") is not True:
                raise ValueError("Salud o conciliación fallida")
        except (KeyError, TypeError, ValueError) as exc:
            add(name + ":quality", "technical", 1000, "Comprobar frescura, identidad e integridad antes de investigar.",
                reason=str(exc))
    if len(stamps) == 2 and abs((stamps[0] - stamps[1]).total_seconds()) > cfg["maximum_source_skew_seconds"]:
        add("sources:skew", "technical", 900, "Repetir lecturas cercanas en tiempo; no comparar cortes distintos.")
    if issues:
        return issues, [], True
    arena, pilot = snapshot["arena"], snapshot["pilot"]
    since = int((now - timedelta(days=cfg["lookback_days"])).timestamp() * 1000)
    cycles = closed_cycles(arena["fills"], since)
    for wid in sorted({c["strategy"] for c in cycles}):
        group = [c for c in cycles if c["strategy"] == wid]
        inverted = [c for c in group if c["gross_pnl_usd"] > 0 and c["net_pnl_usd"] < 0]
        fees = sum(c["fees_usd"] for c in group)
        if inverted:
            add(wid + ":cost_inversion", "research", 600 + min(fees, 100),
                "Preparar hipótesis de ejecución/costos; requiere ensayo separado con control.",
                closed_cycles=len(group), positive_gross_negative_net=len(inverted),
                measured_fees_usd=fees,
                sufficient_sample=len(group) >= cfg["minimum_closed_cycles"]
                                  and len(inverted) >= cfg["cost_inversion_minimum_cycles"])
        if len(group) < cfg["minimum_closed_cycles"]:
            add(wid + ":sample", "evidence", 300, "Acumular ciclos completos; no extrapolar una ganadora.",
                observed=len(group), required=cfg["minimum_closed_cycles"])
    started = _time(arena["started_at_utc"])
    hours = (now - started).total_seconds() / 3600
    maker_fills = sum(f["liquidity"] == "maker" for f in arena["fills"])
    if maker_fills == 0:
        add("market-making-v1:execution", "execution", 500,
            "Medir vigencia, distancia al libro y prints posteriores de cotizaciones antes de cambiar reglas.",
            maker_fills=0, observed_hours=hours,
            sufficient_sample=hours >= cfg["minimum_maker_observation_hours"])
    days = arena["daily_report"]["days"]
    completed = [d for d in days if not d["in_progress"] and not d["no_data"]]
    latest_closed = next(iter(sorted(completed, key=lambda d: d["date"], reverse=True)), None)
    if latest_closed and (latest_closed["quality"]["coverage"] < cfg["minimum_coverage"]
                          or latest_closed["error_count"]):
        add("arena:coverage", "evidence", 750, "Investigar huecos y fallos documentados; conservar días incompletos.",
            date=latest_closed["date"], coverage=latest_closed["quality"]["coverage"],
            errors=latest_closed["error_count"], partial_start=latest_closed["partial_start"])
    quality = pilot["execution_quality"]["total"]
    if quality["maker_known_trades"] < cfg["minimum_closed_cycles"]:
        add("pilot:execution_coverage", "evidence", 400,
            "Completar evidencia de maker/taker y costos de las ejecuciones naturales.",
            maker_known_trades=quality["maker_known_trades"], filled_trades=quality["filled_trades"])
    execution = pilot["evidence"].get("execution", {})
    if not all(execution.get(k, {}).get("integrity") == "verified" for k in ("crypto", "stocks")):
        add("pilot:replay", "technical", 800, "Verificar reproducción de decisiones e integridad archivada.")
    return issues, cycles, False


def diagnose(snapshot, *, now=None, cfg=None, history=()):
    cfg = cfg or policy()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("El reloj requiere zona horaria")
    if snapshot.get("schema_version") != 1:
        raise ValueError("Snapshot sin esquema compatible")
    collected = _time(snapshot["collected_at_utc"])
    if not -60 <= (now - collected).total_seconds() <= cfg["pilot_max_age_seconds"]:
        raise ValueError("La colección es vieja o futura")
    day = now.astimezone(ZoneInfo(cfg["timezone"])).date().isoformat()
    try:
        issues, cycles, blocked = _issues(snapshot, now, cfg)
    except (KeyError, TypeError, ValueError) as exc:
        issues, cycles, blocked = [{"id": "sources:schema", "category": "technical", "base_priority": 1000,
            "action": "Corregir o recuperar el esquema de datos antes de investigar.",
            "evidence": {"reason": str(exc)}, "strategy_change_authorized": False}], [], True
    for issue in issues:
        dates = {event["date"] for event in history if event.get("action") == "daily_review"
                 and issue["id"] in event.get("issue_ids", [])}
        dates.add(day)
        issue.update(observed_days=len(dates), priority=issue.pop("base_priority") + 2 * min(len(dates), 14))
    issues.sort(key=lambda x: (-x["priority"], x["id"]))
    balances = {}
    for name in ("pilot", "arena"):
        source = snapshot.get(name, {})
        if source.get("current") and not blocked:
            balances[name] = source["current"]
    previous_ids = next((set(e.get("issue_ids", [])) for e in reversed(history)
                         if e.get("action") == "daily_review"), set())
    current_ids = {i["id"] for i in issues}
    return {"schema_version": 1, "date": day, "generated_at_utc": now.isoformat(),
            "status": "blocked_by_data_quality" if blocked else "review_complete",
            "mode": "paper", "objective": "Improve net outcomes through verified execution and research; no profit forecast",
            "balances": balances, "priorities": issues, "closed_cycles": cycles,
            "new_issues": sorted(current_ids - previous_ids),
            "no_longer_observed": sorted(previous_ids - current_ids) if not blocked else [],
            "evidence_changed": bool(current_ids != previous_ids),
            "daily_strategy_change_required": False, "candidate_promoted": False,
            "automatic_deployment": False, "live_authorized": False,
            "candidate_budget": {"maximum_active": cfg["maximum_active_candidates"],
                                 "minimum_interval_days": cfg["minimum_candidate_interval_days"]},
            "method": "Net results already include fees. Priorities use measured problems, evidence and persistence, not the sign of daily profit.",
            "limitations": ["Diagnostics do not establish an investment edge or future profits.",
                            "Priorities are research tasks, not orders or capital allocations.",
                            "Daily review is not repeated daily significance testing."]}


def markdown(report):
    lines = ["# Mejora continua — " + report["date"], "", "Estado: " + report["status"], "",
             "| Piloto | Patrimonio USD | Resultado acumulado USD |", "|---|---:|---:|"]
    for name, value in report["balances"].items():
        lines.append(f"| {name} | {value['equity_usd']:.2f} | {value['pnl_usd']:+.2f} |")
    lines.extend(["", "## Prioridades con evidencia", ""])
    for item in report["priorities"]:
        lines.append(f"- **{item['id']}** ({item['observed_days']} días observados): {item['action']}")
        lines.append("  Evidencia: " + json.dumps(item["evidence"], ensure_ascii=False))
    lines.extend(["", "No hay cambio obligatorio de estrategia ni promoción automática.",
                  "El resultado neto ya incluye comisiones. Las tareas no son órdenes ni pronósticos.", ""])
    return "\n".join(lines)


def run(snapshot, output=DEFAULT_OUTPUT, *, now=None, verified_proof=None):
    identity = verified_proof or proof()
    directory = _output(output)
    with exclusive_lock(directory / ".controller.lock"):
        history = read_history(directory)
        report = diagnose(snapshot, now=now, history=history)
        snapshot_hash = canonical_hash(snapshot)
        duplicate = next((e for e in reversed(history) if e.get("action") == "daily_review"
                          and e["date"] == report["date"] and e["snapshot_sha256"] == snapshot_hash), None)
        if duplicate:
            archived = json.loads((directory / duplicate["report_path"]).read_text())
            if canonical_hash(archived) != duplicate["report_sha256"]:
                raise ResearchGateError("Reporte de revisión alterado")
            return {"status": "already_recorded", "report": archived, "new_record": False}
        snapshot_path, _ = _archive(directory / "snapshots", snapshot)
        report["identity"] = identity
        report["snapshot_sha256"] = snapshot_hash
        report_path, report_hash = _archive(directory / "reviews", report)
        event = append_event(directory / "ledger.jsonl", {
            "action": "daily_review", "date": report["date"], "snapshot_sha256": snapshot_hash,
            "snapshot_path": str(snapshot_path.relative_to(directory)),
            "report_sha256": report_hash, "report_path": str(report_path.relative_to(directory)),
            "issue_ids": [i["id"] for i in report["priorities"]],
            "status": report["status"], "candidate_promoted": False})
        _atomic(directory / "latest.json", report)
        (directory / "latest.md").write_text(markdown(report))
        return {"status": report["status"], "report": report, "event_sha256": event["event_sha256"], "new_record": True}


def _grid(root):
    source = Path(root) / "src/lab/research_multi.py"
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SLEEVES" for t in node.targets):
            return ast.literal_eval(node.value), file_hash(source)
    raise ResearchGateError("No se encontró el grid científico")


def register_candidate(config_path, prereg_path, prereg_commit, output=DEFAULT_OUTPUT, *, root=ROOT, now=None):
    """Register before future evaluation; no data fetch or candidate execution."""
    now = now or datetime.now(timezone.utc)
    config = json.loads(Path(config_path).read_text())
    ids = [v["id"] for v in config["variants"]]
    if len(ids) != len(set(ids)) or not ids or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", config["experiment_id"]):
        raise ResearchGateError("IDs de candidata inválidos o duplicados")
    candidate_proof = verify_preregistration(root, prereg_path, prereg_commit,
                                           config["experiment_id"], config, ids)
    grid, grid_hash = _grid(root)
    for v in config["variants"]:
        declared = grid.get(v["sleeve"], {}).get("grid", {})
        if set(v["params"]) != set(declared) or any(v["params"][k] not in allowed for k, allowed in declared.items()):
            raise ResearchGateError("Candidata fuera del grid contado")
    start, end, final = (_time(config["evaluation"][k]) for k in ("holdout_start", "holdout_end", "final_evaluation_at"))
    if not now < start < end <= final or (end - start).total_seconds() < 28 * 86400:
        raise ResearchGateError("Se requieren fechas futuras reservadas y al menos 28 días")
    if config.get("mode") != "paper" or config.get("live_authorized") is not False:
        raise ResearchGateError("Solo se registran candidatas paper")
    directory = _output(output)
    with exclusive_lock(directory / ".controller.lock"):
        history = read_history(directory)
        registrations = [e for e in history if e.get("action") == "candidate_registered"]
        if any(e["candidate_id"] == config["experiment_id"] for e in registrations):
            raise ResearchGateError("Identidad ya registrada; no reiniciar ni reescribir un intento")
        cfg = policy()
        finished = {e["candidate_id"] for e in history if e.get("action") == "candidate_final_review"}
        if sum(e["candidate_id"] not in finished for e in registrations) >= cfg["maximum_active_candidates"]:
            raise ResearchGateError("Presupuesto de candidatas activas agotado")
        if registrations and (now - _time(registrations[-1]["registered_at_utc"])).total_seconds() < cfg["minimum_candidate_interval_days"] * 86400:
            raise ResearchGateError("El intervalo entre nuevos ensayos todavía no se cumple")
        payload = {"candidate_id": config["experiment_id"], "config": config,
                   "config_sha256": canonical_hash(config), "proof": candidate_proof,
                   "grid_sha256": grid_hash, "registered_at_utc": now.isoformat(),
                   "declared_trials": len(ids), "candidate_promoted": False, "live_authorized": False}
        path, digest = _archive(directory / "candidates", payload)
        return append_event(directory / "ledger.jsonl", {"action": "candidate_registered",
            "candidate_id": payload["candidate_id"], "registered_at_utc": now.isoformat(),
            "declared_trials": len(ids), "artifact_sha256": digest,
            "artifact_path": str(path.relative_to(directory))})


def candidate_decision(registration, validation, paper, *, now=None, total_trials=None):
    """At most readiness for review, only at the declared final evaluation."""
    now = now or datetime.now(timezone.utc)
    evaluation = registration["config"]["evaluation"]
    if now < _time(evaluation["final_evaluation_at"]):
        return {"status": "collecting_until_declared_evaluation", "ready_for_human_review": False,
                "candidate_promoted": False, "live_authorized": False,
                "reasons": ["No consultar significancia ni elegir una candidata antes de la fecha fijada"]}
    reasons = []
    expected = {"config_sha256": registration["config_sha256"], "code_commit": registration["proof"]["code_commit"]}
    if any(validation.get(k) != v or paper.get(k) != v for k, v in expected.items()):
        reasons.append("Evidencia distinta de la versión registrada")
    if validation.get("artifact_integrity_verified") is not True or paper.get("artifact_integrity_verified") is not True:
        reasons.append("Artefactos sin verificación de integridad")
    for check in policy()["candidate_requirements"]:
        if validation.get("checks", {}).get(check) is not True:
            reasons.append("Falta o falla: " + check)
    if paper.get("observation_gaps") or paper.get("continuous") is not True:
        reasons.append("Observación con huecos o continuidad no verificada")
    if (validation.get("holdout_start"), validation.get("holdout_end")) != (evaluation["holdout_start"], evaluation["holdout_end"]):
        reasons.append("Periodo reservado distinto del preregistro")
    try:
        if not (_time(registration["registered_at_utc"]) < _time(paper["started_at"])
                <= _time(evaluation["holdout_start"]) < _time(evaluation["holdout_end"])
                <= _time(paper["ended_at"]) <= now):
            reasons.append("La observación no cubre el periodo futuro registrado")
        if not _time(evaluation["final_evaluation_at"]) <= _time(validation["evaluated_at_utc"]) <= now:
            reasons.append("Evaluación fuera de la fecha final declarada")
    except (KeyError, TypeError, ValueError):
        reasons.append("Faltan fechas verificables de evaluación")
    if validation.get("evaluation_count") != 1 or isinstance(validation.get("evaluation_count"), bool):
        reasons.append("La evaluación final debe ser única, sin selección por revisiones diarias")
    if isinstance(validation.get("corrected_trial_count"), bool) or validation.get("corrected_trial_count", 0) < (total_trials or registration["declared_trials"]):
        reasons.append("Comparación múltiple no cubre todos los intentos declarados")
    gate = promotion_gate(validation, paper, now=now)
    reasons.extend(gate["reasons"])
    return {"status": "ready_for_human_review" if not reasons else "not_validated",
            "ready_for_human_review": not reasons, "reasons": sorted(set(reasons)),
            "candidate_promoted": False, "automatic_deployment": False, "live_authorized": False}


def final_review(candidate_id, manifest_path, output=DEFAULT_OUTPUT, *, now=None):
    """Verify local result hashes and record one final verdict per candidate."""
    directory = _output(output)
    now = now or datetime.now(timezone.utc)
    with exclusive_lock(directory / ".controller.lock"):
        history = read_history(directory)
        entry = next((e for e in history if e.get("action") == "candidate_registered"
                      and e["candidate_id"] == candidate_id), None)
        if not entry:
            raise ResearchGateError("No existe candidata registrada")
        registered = json.loads((directory / entry["artifact_path"]).read_text())
        if canonical_hash(registered) != entry["artifact_sha256"]:
            raise ResearchGateError("Registro de candidata alterado")
        if now < _time(registered["config"]["evaluation"]["final_evaluation_at"]):
            return candidate_decision(registered, {}, {}, now=now)
        if any(e.get("action") == "candidate_final_review" and e["candidate_id"] == candidate_id for e in history):
            raise ResearchGateError("La evaluación final ya fue registrada; no repetir selección")
        manifest_path = Path(manifest_path).resolve()
        permitted = (ROOT / "reports/experiments" / candidate_id).resolve()
        if permitted not in manifest_path.parents:
            raise ResearchGateError("Los artefactos requieren el directorio del ensayo registrado")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("candidate_id") != candidate_id:
            raise ResearchGateError("Manifiesto de otra candidata")
        artifacts = manifest["artifacts"]
        for name, digest in artifacts.items():
            path = (manifest_path.parent / name).resolve()
            if permitted not in path.parents or not path.is_file() or file_hash(path) != digest:
                raise ResearchGateError("Artefacto ausente, fuera de ruta o alterado")
        if any(manifest[k] not in artifacts for k in ("validation", "paper")):
            raise ResearchGateError("Faltan hashes de validación o paper")
        validation = json.loads((manifest_path.parent / manifest["validation"]).read_text())
        paper = json.loads((manifest_path.parent / manifest["paper"]).read_text())
        validation["artifact_integrity_verified"] = paper["artifact_integrity_verified"] = True
        trials = sum(e["declared_trials"] for e in history if e.get("action") == "candidate_registered")
        decision = candidate_decision(registered, validation, paper, now=now, total_trials=trials)
        decision.update(candidate_id=candidate_id, manifest_sha256=file_hash(manifest_path))
        path, digest = _archive(directory / "decisions", decision)
        append_event(directory / "ledger.jsonl", {"action": "candidate_final_review", "candidate_id": candidate_id,
            "status": decision["status"], "decision_sha256": digest,
            "decision_path": str(path.relative_to(directory)), "candidate_promoted": False})
        return decision


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    commands = parser.add_subparsers(dest="action", required=True)
    local = commands.add_parser("run")
    local.add_argument("--snapshot", type=Path, required=True)
    commands.add_parser("collect-run")
    reg = commands.add_parser("register")
    reg.add_argument("--config", type=Path, required=True)
    reg.add_argument("--preregistration", type=Path, required=True)
    reg.add_argument("--preregistration-commit", required=True)
    review = commands.add_parser("review")
    review.add_argument("--candidate-id", required=True)
    review.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "register":
        proof()
        result = register_candidate(args.config, args.preregistration, args.preregistration_commit, args.output)
        print(json.dumps({"status": "registered", "candidate": result["candidate_id"], "live_authorized": False}))
        return
    if args.action == "review":
        proof()
        print(json.dumps(final_review(args.candidate_id, args.manifest, args.output), ensure_ascii=False))
        return
    verified = proof()  # Fail before network if code/protocol has changed.
    if args.action == "collect-run":
        from .improvement_sources import collect
        snapshot = collect()
    else:
        snapshot = json.loads(args.snapshot.read_text())
    result = run(snapshot, args.output, verified_proof=verified)
    retried = False
    if args.action == "collect-run" and result["report"]["status"] == "blocked_by_data_quality":
        # Keep the first blocked snapshot too. The pilot may finish its normal
        # five-minute cycle during the second bounded read; never loop forever.
        retried = True
        snapshot = collect()
        result = run(snapshot, args.output, verified_proof=verified)
    report = result["report"]
    print(json.dumps({"status": result["status"], "date": report["date"], "new_record": result["new_record"],
                      "retried_once": retried, "priorities": [i["id"] for i in report["priorities"]],
                      "report": str(args.output / "latest.md"), "candidate_promoted": False,
                      "live_authorized": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
