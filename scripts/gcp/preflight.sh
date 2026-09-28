#!/usr/bin/env bash
# Local/read-only checks. Never authenticates, selects accounts or reads secrets.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
python_bin=${PYTHON_BIN:-"$root/.venv/bin/python"}
[[ -x "$python_bin" ]] || python_bin=python3
export PYTHONDONTWRITEBYTECODE=1
exec "$python_bin" "$root/scripts/gcp/preflight.py" "$@"
