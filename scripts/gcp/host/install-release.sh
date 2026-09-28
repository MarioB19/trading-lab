#!/usr/bin/env bash
# Run explicitly on the VM after reviewing the digest and source SHA.
set -euo pipefail
[[ $# == 2 ]] || { echo 'Usage: install-release.sh IMAGE@sha256:DIGEST FULL_GIT_SHA' >&2; exit 2; }
source /etc/trading-lab/settings.conf
image=$1 sha=$2
contract="$(dirname "$0")/release_contract.py"
[[ "$image" =~ ^[a-z0-9-]+-docker\.pkg\.dev/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9./_-]+@sha256:[a-f0-9]{64}$ ]] || exit 2
[[ "$image" == "$REGISTRY_HOST/$PROJECT_ID/"* && "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
exec 9>/run/trading-release.lock
flock -n 9 || { echo 'Another release installation is running' >&2; exit 1; }
worker_stopped() {
  [[ ! -e "$DATA_DIR/worker.enabled" && ! -L "$DATA_DIR/worker.enabled" ]] || {
    echo 'Deactivate worker before replacing its image' >&2; return 1;
  }
  if systemctl is-active --quiet trading-lab-worker; then
    echo 'Stop worker and reconcile before installing release' >&2; return 1
  fi
  local worker_state
  worker_state=$(docker ps -a --filter 'name=^/trading-lab-worker$' --format '{{.State}}') || {
    echo 'Cannot establish Docker worker state' >&2; return 1;
  }
  case "$worker_state" in
    ''|created|exited|dead) ;;
    *) echo 'Docker worker is still active or its state is ambiguous' >&2; return 1 ;;
  esac
}
worker_stopped
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d /run/trading-docker.XXXXXX)
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
curl -fsS --max-time 10 -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' \
  | docker login --username oauth2accesstoken --password-stdin "$REGISTRY_HOST" >/dev/null
docker pull "$image"
docker image inspect "$image" | python3 "$contract" image "$sha"
# Force Python and pass the reviewed validator via stdin; image ENTRYPOINT cannot bypass it.
docker run --rm -i --network none --read-only --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  --entrypoint python "$image" - config /app/config.yaml --runtime-imports <"$contract"
worker_stopped
if [[ -f /etc/trading-lab/release.conf ]]; then
  cp /etc/trading-lab/release.conf /etc/trading-lab/previous-release.conf
fi
umask 077
printf 'TRADING_IMAGE=%q\nSOURCE_SHA=%q\n' "$image" "$sha" >/etc/trading-lab/release.conf.next
mv /etc/trading-lab/release.conf.next /etc/trading-lab/release.conf
printf 'Release installed, worker remains deactivated. SHA=%s\n' "$sha"
