"""Carriles de candidatas en simulado (F4): la candidata corre contra el control en los mismos días.

Reutiliza `lab.paper_comparison`: cada carril es una comparación pareada (control + candidata) en su
propia carpeta y su propia base, con un único escritor (el candado de paper_comparison). El piloto
nunca lee ni escribe en un carril, y un carril nunca toca la base del piloto:

- el registro vive en `research/carriles.yaml` (máximo dos carriles activos, US$500 ficticios cada uno);
- `lab.runtime` los corre **después** de cerrar el ciclo del piloto, en procesos aparte, con
  `--data-dir /data/lanes/<id>`; si un carril falla, el ciclo del piloto ya quedó escrito y no cambia;
- sin carriles activos no se importa ni se ejecuta nada.

Activar un carril exige un plan preregistrado (commit propio) y su DEC; no cambia el piloto.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "research" / "carriles.yaml"
MAX_ACTIVE = 2
STATES = {"vacio", "activo", "pausado", "cerrado"}
_ID = re.compile(r"carril-\d+")
_COMMIT = re.compile(r"[0-9a-f]{40}")


def load(path: Path | None = None) -> dict:
    data = yaml.safe_load(Path(path or REGISTRY).read_text(encoding="utf-8")) or {}
    lanes = data.get("carriles") or []
    ids = [lane.get("id") for lane in lanes]
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and _ID.fullmatch(i) for i in ids):
        raise ValueError("Ids de carril inválidos o repetidos")
    if int(data.get("max_activos", MAX_ACTIVE)) > MAX_ACTIVE:
        raise ValueError(f"Máximo {MAX_ACTIVE} carriles activos")
    if float(data.get("capital_usd", 500)) != 500:
        raise ValueError("Cada carril usa US$500 ficticios, igual que el bloque cripto del piloto")
    active = [lane for lane in lanes if lane.get("estado") == "activo"]
    if len(active) > int(data.get("max_activos", MAX_ACTIVE)):
        raise ValueError("Demasiados carriles activos")
    for lane in lanes:
        if lane.get("estado") not in STATES:
            raise ValueError(f"{lane['id']}: estado desconocido")
        if lane.get("estado") == "activo":
            if not lane.get("plan") or not _COMMIT.fullmatch(str(lane.get("preregistro_commit", ""))):
                raise ValueError(f"{lane['id']}: un carril activo exige plan y commit de preregistro")
            if Path(lane["plan"]).is_absolute() or ".." in Path(lane["plan"]).parts:
                raise ValueError(f"{lane['id']}: el plan debe ser una ruta del repositorio")
    return data


def lane_dir(root: Path, lane_id: str) -> Path:
    if not _ID.fullmatch(lane_id):
        raise ValueError("Id de carril inválido")
    return Path(root) / lane_id


def commands(registry: dict, lanes_root: Path) -> list[tuple[str, list[str]]]:
    """Comandos de los carriles activos. Nunca reciben la configuración ni la carpeta del piloto."""
    out = []
    for lane in registry.get("carriles") or []:
        if lane.get("estado") != "activo":
            continue
        out.append((lane["id"], [sys.executable, "-m", "lab.paper_comparison", "--once",
                                 "--preregistration-commit", lane["preregistro_commit"],
                                 "--plan", str(ROOT / lane["plan"]),
                                 "--data-dir", str(lane_dir(lanes_root, lane["id"])), "--fetch"]))
    return out


def run_active(lanes_root: Path, *, registry_path: Path | None = None, runner=subprocess.run, timeout: int = 600,
               today: str | None = None) -> list[dict]:
    """Corre una vez al día (UTC) cada carril activo. No lanza excepciones: el piloto ya cerró su ciclo."""
    try:
        registry = load(registry_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [{"lane": None, "status": "error", "detail": f"registro de carriles: {type(exc).__name__}"}]
    today = today or datetime.now(timezone.utc).date().isoformat()
    results = []
    for lane_id, command in commands(registry, lanes_root):
        folder = lane_dir(lanes_root, lane_id)
        marker = folder / "ultimo-dia.json"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if marker.is_file() and json.loads(marker.read_text()).get("day") == today:
                continue
            result = runner(command, timeout=timeout, capture_output=True, text=True, check=False)
            results.append({"lane": lane_id, "status": "ok" if result.returncode == 0 else "error",
                            "returncode": result.returncode})
            if result.returncode == 0:
                marker.write_text(json.dumps({"day": today}) + "\n")
        except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
            results.append({"lane": lane_id, "status": "error", "detail": type(exc).__name__})
    return results


def status(lanes_root: Path | None, *, registry_path: Path | None = None) -> dict:
    """Lectura para el panel: registro y, si existe, el resultado de cada comparación (sin ejecutar nada)."""
    registry = load(registry_path)
    lanes = []
    for lane in registry.get("carriles") or []:
        row = {"id": lane["id"], "status": lane.get("estado"), "hypothesis": lane.get("hipotesis"),
               "plan": lane.get("plan"), "started_at": lane.get("desde")}
        if lane.get("estado") != "vacio" and lanes_root is not None:
            try:
                from .paper_comparison import status as comparison
                report = comparison(lane_dir(lanes_root, lane["id"]), ROOT / lane["plan"])
                row["comparison_status"] = report.get("status")
                portfolios = report.get("portfolios") or {}
                control = (portfolios.get("control") or {}).get("equity")
                candidate = next((v.get("equity") for k, v in portfolios.items() if k != "control"), None)
                if control is not None and candidate is not None:
                    row.update(equity_usd=candidate, control_equity_usd=control, vs_control_usd=candidate - control)
            except Exception as exc:  # El panel muestra el problema; no inventa cifras.
                row["comparison_status"] = f"sin lectura ({type(exc).__name__})"
        lanes.append(row)
    active = sum(1 for lane in lanes if lane["status"] == "activo")
    return {"lanes": lanes, "active": active, "max_active": int(registry.get("max_activos", MAX_ACTIVE)),
            "capital_usd": registry.get("capital_usd", 500), "note": registry.get("nota"), "live_authorized": False}
