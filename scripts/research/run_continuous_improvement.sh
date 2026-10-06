#!/bin/bash
set -euo pipefail
CI_TRADING_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$CI_TRADING_ROOT"
if [ "$#" -eq 0 ]; then
  set -- collect-run
fi
PYTHONPATH="$CI_TRADING_ROOT/src" exec "$CI_TRADING_ROOT/../trading-lab/.venv/bin/python" \
  -m lab.continuous_improvement "$@"
