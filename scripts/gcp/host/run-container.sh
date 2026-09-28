#!/usr/bin/env bash
set -euo pipefail
source /etc/trading-lab/settings.conf
source /etc/trading-lab/release.conf
kind=${1:?worker or api}
[[ "$TRADING_IMAGE" =~ @sha256:[a-f0-9]{64}$ ]] || exit 2
mountpoint -q "$DATA_DIR" || { echo 'State disk not mounted' >&2; exit 1; }
name="trading-lab-$kind"
common=(--rm --name "$name" --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 128
  --tmpfs /tmp:rw,nosuid,nodev,size=128m --log-driver json-file --log-opt max-size=10m --log-opt max-file=3
  --env PYTHONUNBUFFERED=1)
case "$kind" in
  worker)
    [[ -f "$DATA_DIR/worker.enabled" ]] || { echo 'Worker not activated' >&2; exit 1; }
    common+=(--memory 2g --cpus 1.5 --mount "type=bind,src=$DATA_DIR,dst=/var/lib/trading-lab")
    # References only, provisioned explicitly later. No Bitso/live credentials are allowed.
    secret_file=$(mktemp /run/trading-paper.XXXXXX)
    refs_file=$(mktemp /run/trading-refs.XXXXXX)
    chmod 0600 "$secret_file"
    trap 'rm -f "$secret_file" "$refs_file"' EXIT
    python3 -c 'import json; refs=json.load(open("/etc/trading-lab/paper-secret-refs.json")); assert isinstance(refs,dict); assert not refs or set(refs)=={"ALPACA_KEY_ID","ALPACA_SECRET_KEY"}; [print(k,*v.split("/"),sep="\t") for k,v in refs.items()]' >"$refs_file"
    while IFS=$'\t' read -r key secret version; do
      [[ -n "$key" ]] || continue
      case "$key" in ALPACA_KEY_ID|ALPACA_SECRET_KEY) ;; *) exit 2 ;; esac
      value=$(gcloud secrets versions access "$version" --secret "$secret" --project "$PROJECT_ID")
      [[ -n "$value" && "$value" != *$'\n'* && "$value" != *$'\r'* ]] || exit 2
      printf '%s=%s\n' "$key" "$value" >>"$secret_file"
      unset value
    done <"$refs_file"
    common+=(--env-file "$secret_file")
    command=(python -m lab.runtime --config /app/config.yaml --data-dir /var/lib/trading-lab --interval 300)
    ;;
  api)
    common+=(--memory 512m --cpus 0.5 --publish 127.0.0.1:8080:8080
      --mount "type=bind,src=$DATA_DIR,dst=/var/lib/trading-lab")
    command=(python -m lab.service --data-dir /var/lib/trading-lab --host 0.0.0.0 --port 8080)
    ;;
  *) echo 'worker or api required' >&2; exit 2 ;;
esac
if [[ $(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true) == true ]]; then
  echo "Container $name already running; refusing a second writer/replacement" >&2
  exit 1
fi
docker rm "$name" >/dev/null 2>&1 || true
docker run "${common[@]}" "$TRADING_IMAGE" "${command[@]}"
