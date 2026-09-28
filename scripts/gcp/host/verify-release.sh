#!/usr/bin/env bash
# Read back the restarted operational API. Readiness may be 503 before activation.
set -euo pipefail
[[ $# == 2 ]] || exit 2
image=$1 sha=$2
[[ "$image" =~ ^[a-z0-9-]+-docker\.pkg\.dev/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9./_-]+@sha256:[a-f0-9]{64}$ && "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
contract="$(dirname "$0")/release_contract.py"
for attempt in $(seq 1 30); do
  if docker inspect trading-lab-api 2>/dev/null | python3 "$contract" api "$sha" --image "$image" >/dev/null 2>&1 \
    && curl --fail --silent --max-time 2 http://127.0.0.1:8080/healthz \
       | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("status")=="alive" and d.get("read_only") is True' 2>/dev/null; then
    printf 'Operational API verified: SHA=%s; digest=%s. Worker activation is separate.\n' "$sha" "$image"
    exit 0
  fi
  sleep 2
done
echo 'API verification failed; inspect trading-lab-api logs and previous-release.conf. No worker has been activated.' >&2
exit 1
