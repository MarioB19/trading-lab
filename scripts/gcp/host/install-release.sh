#!/usr/bin/env bash
# Run explicitly on the VM after reviewing the digest and source SHA.
set -euo pipefail
source /etc/trading-lab/settings.conf
image=${1:?Artifact Registry digest URI required}
sha=${2:?40-character Git SHA required}
[[ "$image" =~ ^[a-z0-9-]+-docker\.pkg\.dev/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9./_-]+@sha256:[a-f0-9]{64}$ ]] || exit 2
[[ "$image" == "$REGISTRY_HOST/$PROJECT_ID/"* && "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ ! -f "$DATA_DIR/worker.enabled" ]] || { echo 'Deactivate worker before replacing its image' >&2; exit 1; }
if systemctl is-active --quiet trading-lab-worker; then
  echo 'Stop worker and reconcile before installing release' >&2; exit 1
fi
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d /run/trading-docker.XXXXXX)
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
curl -fsS -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' \
  | docker login --username oauth2accesstoken --password-stdin "$REGISTRY_HOST" >/dev/null
docker pull "$image"
label=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image")
[[ "$label" == "$sha" ]] || { echo 'Image source SHA mismatch' >&2; exit 1; }
docker run --rm --network none --read-only "$image" python -c \
  'import yaml; from pathlib import Path; c=yaml.safe_load(Path("/app/config.yaml").read_text()); assert c["mode"]=="paper"; import lab.runtime,lab.service,lab.ops'
if [[ -f /etc/trading-lab/release.conf ]]; then
  cp /etc/trading-lab/release.conf /etc/trading-lab/previous-release.conf
fi
umask 077
printf 'TRADING_IMAGE=%q\nSOURCE_SHA=%q\n' "$image" "$sha" >/etc/trading-lab/release.conf.next
mv /etc/trading-lab/release.conf.next /etc/trading-lab/release.conf
printf 'Release installed, worker remains deactivated. SHA=%s\n' "$sha"
