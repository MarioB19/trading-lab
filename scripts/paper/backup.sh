#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
event=paper_backup
paper_preflight
[[ -f "$PAPER_DATA/comparison.sqlite3" ]] || paper_fail 'La comparación no ha creado su base'
exec 9>"$PAPER_BACKUPS/.backup-run.lock"
flock -n 9 || paper_fail 'Hay otro respaldo experimental; reintento pendiente'
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import secrets;print(secrets.token_hex(4))')"
phase=backup
docker run "${common[@]}" --network none --name trading-lab-comparison-backup \
  --mount "type=bind,src=$PAPER_DATA,dst=/comparison" \
  --mount "type=bind,src=$PAPER_BACKUPS,dst=/backups" \
  "$PAPER_IMAGE" -m lab.paper_ops backup --data-dir /comparison --output "/backups/$stamp"
phase=verify
docker run "${common[@]}" --network none --name trading-lab-comparison-verify \
  --mount "type=bind,src=$PAPER_BACKUPS,dst=/backups,readonly" \
  "$PAPER_IMAGE" -m lab.paper_ops verify-backup --backup "/backups/$stamp"
phase=record
# This records local verification only. It does not claim an offsite GCS copy.
python3 - "$PAPER_BACKUPS" "$stamp" "$PAPER_CODE_SHA" <<'PY'
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,sys
root=Path(sys.argv[1]); bundle=root/sys.argv[2]
record={"type":"paper-local-backup-v1","bundle":bundle.name,"code_commit":sys.argv[3],
        "verified_at":datetime.now(timezone.utc).isoformat(),"gcs_copy_verified":False,
        "manifest_sha256":hashlib.sha256((bundle/"manifest.json").read_bytes()).hexdigest()}
temporary=root/".last-verified.json.tmp"
with temporary.open("w") as stream:
    json.dump(record,stream,indent=2); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
os.replace(temporary,root/"last-verified.json")
PY
phase=complete
paper_log ok 0
