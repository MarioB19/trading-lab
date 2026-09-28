#!/usr/bin/env bash
# Sourced only by the manually installed paper scripts. No secrets are loaded.
set -Eeuo pipefail
umask 077
readonly PAPER_ROOT=/var/lib/trading-experiments
readonly PAPER_DATA=/var/lib/trading-experiments/aggressive-v2
readonly PAPER_BACKUPS=/var/lib/trading-experiments/backups
readonly PAPER_RELEASE=/etc/trading-lab-paper/release.json
readonly PAPER_ENABLED=/etc/trading-lab-paper/aggressive-v2.enabled
phase=preflight
event=paper_operation

paper_log() {
  python3 -c 'import datetime,json,sys; print(json.dumps({"event":sys.argv[1],"status":sys.argv[2],"phase":sys.argv[3],"exit_code":int(sys.argv[4]),"severity":"INFO" if sys.argv[2]=="ok" else "WARNING" if sys.argv[2]=="pending" else "ERROR","time_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}))' \
    "$event" "$1" "$phase" "$2"
}
paper_failed() {
  local status=$?
  trap - ERR
  paper_log failed "$status" >&2 || true
  exit "$status"
}
trap paper_failed ERR
paper_fail() { printf '%s\n' "$1" >&2; return 2; }

paper_preflight() {
  [[ -f "$PAPER_RELEASE" && ! -L "$PAPER_RELEASE" ]] || paper_fail 'Falta release.json regular'
  local fields
  fields=$(python3 - "$PAPER_RELEASE" <<'PY'
import json,re,sys
with open(sys.argv[1]) as stream:
    value=json.load(stream)
if (not isinstance(value,dict) or set(value)!={"image","code_commit","preregistration_commit","mode"}
    or value["mode"]!="paper"
    or not re.fullmatch(r"[a-z0-9.-]+-docker\.pkg\.dev/[a-z0-9._/-]+@sha256:[0-9a-f]{64}",str(value["image"]))
    or any(not re.fullmatch(r"[0-9a-f]{40}",str(value[key])) for key in ("code_commit","preregistration_commit"))
    or value["code_commit"]==value["preregistration_commit"]):
    raise SystemExit("Release inválida: paper, digest y dos commits distintos obligatorios; no se admiten campos secretos")
print(value["image"]); print(value["code_commit"]); print(value["preregistration_commit"])
PY
)
  { IFS= read -r PAPER_IMAGE; IFS= read -r PAPER_CODE_SHA; IFS= read -r PAPER_PREREG_SHA; } <<<"$fields"
  [[ -f "$PAPER_ENABLED" && ! -L "$PAPER_ENABLED" ]] || paper_fail 'Programación paper no autorizada: falta marca manual'
  [[ "$(cat "$PAPER_ENABLED")" == "$PAPER_CODE_SHA" ]] || paper_fail 'La marca manual no corresponde al código fijado'
  mountpoint -q "$PAPER_ROOT" || paper_fail 'Falta el montaje persistente experimental'
  [[ -d "$PAPER_DATA" && ! -L "$PAPER_DATA" && -d "$PAPER_BACKUPS" && ! -L "$PAPER_BACKUPS" ]] || paper_fail 'Faltan directorios dedicados, sin enlaces'
  # Share one host lock across run/backup/health so their container budgets cannot
  # accumulate on the 4 GiB VM. Keep fd 8 open until the calling script exits.
  phase=host_lock
  exec 8>"$PAPER_ROOT/.services.lock"
  if ! flock -n 8; then
    paper_log pending 75 >&2
    exit 75
  fi
  phase=image_validation
  local inspection
  inspection=$(docker image inspect "$PAPER_IMAGE")
  python3 -c '
import json,re,sys
images=json.load(sys.stdin)
if not isinstance(images,list) or len(images)!=1: raise SystemExit("Imagen local desconocida")
config=images[0].get("Config",{}); values=config.get("Env",[]) or []; env={}
for value in values:
    name,sep,content=value.partition("=")
    if not sep or name in env: raise SystemExit("Entorno de imagen ambiguo")
    if re.search(r"SECRET|TOKEN|PASSWORD|API_KEY|KEY_ID|CREDENTIAL",name,re.I): raise SystemExit("La imagen experimental contiene variables de credenciales")
    env[name]=content
if (config.get("User")!="10001:10001" or config.get("WorkingDir")!="/app"
    or env.get("TRADING_LAB_BUILD_ID")!=sys.argv[1]
    or env.get("PYTHONDONTWRITEBYTECODE")!="1"
    or config.get("Labels",{}).get("org.opencontainers.image.revision")!=sys.argv[1]):
    raise SystemExit("UID, build ID, revisión o bytecode de la imagen no coinciden")
' "$PAPER_CODE_SHA" <<<"$inspection"
  common=(--rm --pull never --user 10001:10001 --read-only --cap-drop ALL
    --security-opt no-new-privileges --pids-limit 128 --memory 768m --cpus 1
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m
    --log-driver json-file --log-opt max-size=10m --log-opt max-file=3
    --entrypoint python)
}
