"""Prospective, immutable paper evidence; never selects or promotes a strategy.

Payloads and their index live in the existing SQLite documents table, so normal
transactional backups and restores include the evidence without sidecar files.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import yaml

PREFIX = "evidence.capture."


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def persist(db, kind, payload, *, now=None):
    """Append once within the caller's transaction; original captures never change."""
    from .storage import SQLiteStore

    if kind not in {"market", "execution"} or not isinstance(payload, dict):
        raise ValueError("Captura no válida")
    stamp = now or datetime.now(timezone.utc).isoformat()
    digest = fingerprint(payload)
    name = PREFIX + kind + "." + digest
    encoded = canonical(payload)
    previous = db.execute("SELECT payload FROM documents WHERE name=?", (name,)).fetchone()
    if previous:
        if previous[0] != encoded:
            raise ValueError("Conflicto de integridad de captura")
        return digest
    db.execute("INSERT INTO documents VALUES(?,?,?)", (name, encoded, stamp))
    index = SQLiteStore._read(db, "evidence_index", {}) or {}
    index.setdefault("schema_version", 1)
    index.setdefault("counts", {})[kind] = index.get("counts", {}).get(kind, 0) + 1
    key = kind if kind == "market" else "execution." + str(payload.get("sleeve", "unknown"))
    index.setdefault("latest", {})[key] = {"document": name, "sha256": digest,
        "recorded_at_utc": stamp, "status": payload.get("status", "unverified")}
    SQLiteStore._write(db, "evidence_index", index)
    return digest


def build_summary(db=None, *, now=None):
    """Small authenticated API projection, with hashes checked on every read."""
    from .storage import SQLiteStore

    result = {"schema_version": 1, "status": "pending", "counts": {},
              "market": None, "execution": {}, "errors": [],
              "profitability_verified": False, "live_authorized": False,
              "limitations": [
                  "Reproducir una simulación no demuestra rentabilidad ni ejecución con dinero real.",
                  "Los listados observados hoy no reconstruyen el universo histórico.",
                  "Los precios ajustados de ETFs no prueban una contabilidad de dividendos y splits.",
                  "La validación independiente y las cuatro semanas prospectivas siguen pendientes."]}
    if db is None:
        return result
    index = SQLiteStore._read(db, "evidence_index", {}) or {}
    result["counts"] = index.get("counts", {})
    result["last_collection"] = SQLiteStore._read(db, "evidence_collection", {}) or {}
    current = now or datetime.now(timezone.utc)
    for key, ref in index.get("latest", {}).items():
        try:
            payload = SQLiteStore._read(db, ref["document"])
            if not isinstance(payload, dict) or fingerprint(payload) != ref["sha256"]:
                raise ValueError("digest")
            item = {"sha256": ref["sha256"], "recorded_at_utc": ref["recorded_at_utc"],
                    "status": payload.get("status", "unverified"), "integrity": "verified"}
            if key == "market":
                item.update(observed_at_utc=payload.get("observed_at_utc"),
                            panels={name: {k: value for k, value in panel.items()
                                            if k not in {"csv", "data", "values", "prices"}}
                                    for name, panel in payload.get("panels", {}).items()},
                            signal_replay=payload.get("signal_replay", {}),
                            errors=payload.get("errors", []), record_count=len(payload.get("records", [])))
                observed = datetime.fromisoformat(item["observed_at_utc"])
                age = (current - observed).total_seconds()
                item["stale"] = observed.tzinfo is None or age > 36 * 3600 or age < -60
                result["market"] = item
            elif key.startswith("execution."):
                item.update({k: payload.get(k) for k in ("sleeve", "candle", "observed_at", "checks", "limitations", "replay")})
                result["execution"][key.split(".", 1)[1]] = item
        except (KeyError, ValueError, TypeError):
            result["errors"].append({"capture": key, "error": "integrity_or_metadata_invalid"})
    if result["errors"]:
        result["status"] = "error"
    elif result["market"]:
        result["status"] = "stale" if result["market"]["stale"] else "collecting"
        if result["market"]["status"] != "ok":
            result["status"] = "partial"
    if result["status"] != "error" and (result["last_collection"].get("status") in {"error", "partial", "timeout"}
            or any(item.get("status") in {"mismatch", "unavailable"} for item in result["execution"].values())):
        result["status"] = "partial"
    return result


def collect_once(config, store, *, collector=None, now=None):
    """One completed capture daily (including partial); failures retry hourly."""
    from .runtime import validate_config

    cfg = yaml.safe_load(Path(config).read_text())
    validate_config(cfg)
    current = now or datetime.now(timezone.utc)
    previous = store.read_document("evidence_collection", {}) or {}
    try:
        last = datetime.fromisoformat(previous["attempted_at_utc"])
        age = (current - last).total_seconds()
        if 0 <= age and (previous.get("status") in {"ok", "partial"} and last.date() == current.date() or age < 3600):
            return {"status": "skip", "reason": "daily_capture_or_retry_backoff"}
    except (KeyError, ValueError, TypeError):
        pass
    attempt = {"status": "running", "attempted_at_utc": current.isoformat(),
               "build_id": os.environ.get("TRADING_LAB_BUILD_ID", "local-uncommitted")}
    store.write_document("evidence_collection", attempt)
    try:
        if collector is None:
            from .data_evidence import collect_market_observation
            collector = collect_market_observation
        payload = collector(cfg, now=current)
        payload["build_id"] = attempt["build_id"]
        payload["config_sha256"] = hashlib.sha256(Path(config).read_bytes()).hexdigest()
        payload["digest"] = fingerprint({k: v for k, v in payload.items() if k != "digest"})
        with store.transaction() as db:
            digest = persist(db, "market", payload)
            attempt.update(status=payload.get("status", "error"), sha256=digest,
                           completed_at_utc=datetime.now(timezone.utc).isoformat())
            store._write(db, "evidence_collection", attempt)
    except Exception as exc:
        attempt.update(status="error", error=type(exc).__name__)
        store.write_document("evidence_collection", attempt)
    return attempt


def main(argv=None):
    from .storage import SQLiteStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true", required=True)
    args = parser.parse_args(argv)
    cfg = yaml.safe_load(args.config.read_text())
    path = Path(cfg.get("paths", {}).get("database", ""))
    if not path.is_file():
        raise ValueError("La captura requiere una base operativa existente")
    result = collect_once(args.config, SQLiteStore(path))
    print(canonical(result))
    return 0 if result["status"] in {"ok", "skip"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
