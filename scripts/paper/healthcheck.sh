#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
event=paper_health
paper_preflight
phase=observation
report=$(docker run "${common[@]}" --network none --name trading-lab-comparison-health \
  --mount "type=bind,src=$PAPER_DATA,dst=/comparison" \
  "$PAPER_IMAGE" -m lab.paper_comparison --status \
  --plan /app/configs/experiments/aggressive_v2.yaml --data-dir /comparison)
python3 -c '
from datetime import datetime,timezone
import json,sys
report=json.load(sys.stdin); health=report.get("health",{}); now=datetime.now(timezone.utc)
if report.get("experiment_id")!="aggressive-v2" or health.get("status")!="ok": raise SystemExit("Comparación no saludable")
for name,limit in (("last_attempt",7200),("last_success",129600)):
    value=health.get(name)
    if not value: raise SystemExit("Falta heartbeat experimental")
    age=(now-datetime.fromisoformat(value)).total_seconds()
    if not 0<=age<=limit: raise SystemExit("Observación experimental ausente o reloj incoherente")
if report.get("observation_gaps") or report.get("unresolved_errors",0): raise SystemExit("Hay incidencias experimentales pendientes")
' <<<"$report"
phase=local_backup
python3 - "$PAPER_BACKUPS" <<'PY'
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,re,sys
root=Path(sys.argv[1]); record=json.loads((root/"last-verified.json").read_text())
if record.get("type")!="paper-local-backup-v1" or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}",str(record.get("bundle",""))):
    raise SystemExit("Registro de respaldo local inválido")
age=(datetime.now(timezone.utc)-datetime.fromisoformat(record["verified_at"])).total_seconds()
manifest=root/record["bundle"]/"manifest.json"
if not 0<=age<=93600 or manifest.is_symlink() or not manifest.is_file() or hashlib.sha256(manifest.read_bytes()).hexdigest()!=record["manifest_sha256"]:
    raise SystemExit("Falta respaldo local verificado en las últimas 26 horas o cambió su manifiesto")
PY
phase=complete
paper_log ok 0
