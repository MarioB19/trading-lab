#!/usr/bin/env bash
set -euo pipefail
[[ -f /var/lib/trading-lab/worker.enabled ]] || exit 0
stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if curl --fail --silent --max-time 10 http://127.0.0.1:8080/readyz >/dev/null; then
  printf '{"event":"heartbeat","status":"ok","time":"%s"}\n' "$stamp"
else
  printf '{"event":"heartbeat","status":"failed","severity":"ERROR","time":"%s"}\n' "$stamp"
  exit 1
fi >>/var/log/trading-lab/health.jsonl
