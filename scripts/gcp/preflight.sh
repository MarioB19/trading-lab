#!/usr/bin/env bash
# Local/read-only inventory. No login, project selection, network mutations or secrets.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
printf 'Repository SHA: '
git rev-parse HEAD
printf 'Changes: '
git status --porcelain | wc -l | tr -d ' '
for executable in docker terraform gcloud gh; do
  if command -v "$executable" >/dev/null; then
    printf '%s: available\n' "$executable"
  else
    printf '%s: missing (only needed for the corresponding later step)\n' "$executable"
  fi
done
printf '\nNo cloud account has been accessed. Before connecting, verify:\n'
printf '%s\n' \
  '1. Account brandonmuro.work@gmail.com, project ID and billing account selected by operator.' \
  '2. Credits remaining, end date and Compute/Storage eligibility in Billing > Credits.' \
  '3. Region us-central1, costs before credits/tax, $60 alert budget.' \
  '4. git state clean, full tested SHA, image digest, paper configuration.' \
  '5. Latest state export, consistent backup/restore trial, both legacy cron triggers disabled before activation.'
