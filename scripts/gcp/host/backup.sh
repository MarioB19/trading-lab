#!/usr/bin/env bash
set -Eeuo pipefail
phase=setup
backup_failed() {
  local status=$?
  trap - ERR
  printf '{"event":"backup","status":"failed","severity":"ERROR","phase":"%s","exit_code":%d,"time":"%s"}\n' \
    "$phase" "$status" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    | tee -a /var/log/trading-lab/health.jsonl >&2 || true
  exit "$status"
}
trap backup_failed ERR
source /etc/trading-lab/settings.conf
source /etc/trading-lab/release.conf
[[ -f "$DATA_DIR/trading.sqlite3" ]] || exit 0
mountpoint -q "$DATA_DIR"
exec 9>/run/trading-backup.lock
flock -n 9 || exit 0
stamp=$(date -u +%Y%m%dT%H%M%SZ)
destination="/var/lib/trading-lab/backups/$stamp.sqlite3"
phase=create
docker run --rm --read-only --network none --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m --mount "type=bind,src=$DATA_DIR,dst=/var/lib/trading-lab" \
  "$TRADING_IMAGE" python -m lab.ops backup --data-dir /var/lib/trading-lab --destination "$destination"
phase=verify
docker run --rm --read-only --network none --mount "type=bind,src=$DATA_DIR,dst=/var/lib/trading-lab,readonly" \
  "$TRADING_IMAGE" python -m lab.ops verify-backup --source "$destination"
phase=upload
gcloud storage cp "$destination" "$destination.manifest.json" "gs://$BACKUP_BUCKET/$stamp/" --project "$PROJECT_ID" --quiet
# Unique remote names and objectCreator prevent overwriting prior backups.
# Retain one week locally, thirty-five days remotely; deletion is only after upload success.
phase=retention
find "$DATA_DIR/backups" -type f -name '*.sqlite3*' -mtime +7 -delete
printf '{"event":"backup","status":"ok","time":"%s"}\n' "$stamp" >>/var/log/trading-lab/health.jsonl
