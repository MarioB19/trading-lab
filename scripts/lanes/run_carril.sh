#!/usr/bin/env bash
# Corre una observación diaria de un carril (ejecutor separado, fuera de Railway).
#   scripts/lanes/run_carril.sh carril-1 "<ruta al vault>/Trading Lab"
# Exige: checkout limpio (gate Git), Python 3.13 en <vault>/.venv-carriles, red hacia Kraken y Yahoo.
set -euo pipefail
LANE="${1:?carril}"; VAULT="${2:?ruta del vault}"
REPO="$VAULT/trading-lab"; VENV="$VAULT/.venv-carriles"; DATA="$VAULT/carriles/$LANE"
cd "$REPO"
git pull --ff-only >/dev/null
PLAN=$(PYTHONPATH=src "$VENV/bin/python" - "$LANE" <<'PY'
import sys, yaml
reg = yaml.safe_load(open("research/carriles.yaml"))
lane = next(l for l in reg["carriles"] if l["id"] == sys.argv[1])
assert lane["estado"] == "activo", "carril no activo"
print(lane["plan"], lane["preregistro_commit"])
PY
)
set -- $PLAN
mkdir -p "$DATA"
PYTHONPATH=src "$VENV/bin/python" -m lab.paper_comparison --once --fetch \
  --plan "$REPO/$1" --preregistration-commit "$2" --data-dir "$DATA"
PYTHONPATH=src "$VENV/bin/python" -m lab.paper_comparison --status --plan "$REPO/$1" --data-dir "$DATA" || true
