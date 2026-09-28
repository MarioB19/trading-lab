#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/common.sh"
event=paper_comparison
paper_preflight
phase=run
# Docker's fixed name and the comparison's own lock both reject a second writer.
# No env file, broker credentials, operational volume or automatic pull is used.
docker run "${common[@]}" --name trading-lab-comparison \
  --mount "type=bind,src=$PAPER_DATA,dst=/comparison" \
  "$PAPER_IMAGE" -m lab.paper_comparison --once \
  --plan /app/configs/experiments/aggressive_v2.yaml \
  --attestation /app/reports/attestations/aggressive-v2.json \
  --preregistration-commit "$PAPER_PREREG_SHA" --data-dir /comparison --fetch
phase=complete
paper_log ok 0
