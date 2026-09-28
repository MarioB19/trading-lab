#!/usr/bin/env bash
# Explicit remote mutation. Does not activate a worker or switch strategies/mode.
set -euo pipefail
if [[ $# != 6 || "$1" != --execute ]]; then
  echo 'Usage: deploy.sh --execute PROJECT ZONE INSTANCE IMAGE@sha256:DIGEST FULL_GIT_SHA' >&2
  exit 2
fi
project=$2 zone=$3 instance=$4 image=$5 sha=$6
[[ "$project" =~ ^[a-z][a-z0-9-]+$ && "$zone" =~ ^[a-z0-9-]+$ && "$instance" =~ ^[a-z][a-z0-9-]+$ ]] || exit 2
[[ "$image" =~ ^[a-z0-9-]+-docker\.pkg\.dev/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9./_-]+@sha256:[a-f0-9]{64}$ && "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
gcloud compute ssh "$instance" --project "$project" --zone "$zone" --tunnel-through-iap \
  --command="sudo /usr/local/lib/trading-lab/install-release.sh '$image' '$sha' && sudo systemctl restart trading-lab-api && sudo /usr/local/lib/trading-lab/verify-release.sh '$image' '$sha'"
printf 'Image installed and API verified; worker remains inactive. Review /readyz, import and cutover in docs/GCP_RUNBOOK.md.\n'
