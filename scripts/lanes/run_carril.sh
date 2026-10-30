#!/usr/bin/env bash
# Observación diaria de un carril (ejecutor separado, fuera de Railway), con código CONGELADO.
#   scripts/lanes/run_carril.sh carril-1 "<ruta del vault>/Trading Lab" [setup|run|status]
#
# - El carril corre desde un clon congelado en <vault>/carriles/codigo-<carril> (la base del carril está
#   atada al commit exacto con el que se creó; el checkout de trabajo de la USB sigue avanzando con main).
# - La base vive en <vault>/carriles/<carril>, fuera de cualquier repo. Un solo escritor.
# - Python 3.13 en <vault>/.venv-carriles (uv). `setup` lo prepara; `run` hace una observación (idempotente
#   dentro del mismo día UTC); `status` solo lee.
set -euo pipefail
LANE="${1:?carril}"; VAULT="${2:?ruta del vault}"; ACTION="${3:-run}"
WORK="$VAULT/trading-lab"; FROZEN="$VAULT/carriles/codigo-$LANE"; VENV="$VAULT/.venv-carriles"; DATA="$VAULT/carriles/$LANE"
mkdir -p "$VAULT/carriles"

setup() {
  if [ ! -x "$VENV/bin/python" ]; then
    uv venv -p 3.13 "$VENV" -q
    uv pip install -q --python "$VENV/bin/python" -r "$WORK/requirements-runtime.txt"
  fi
  if [ ! -d "$FROZEN/.git" ]; then
    # clon local del checkout de la USB (sin red); queda fijo en el commit de main de ese momento
    git clone -q --no-hardlinks "$WORK" "$FROZEN"
    git -C "$FROZEN" checkout -q --detach "$(git -C "$WORK" rev-parse HEAD)"
    git -C "$FROZEN" rev-parse HEAD > "$FROZEN.commit"   # la base del carril exige un directorio vacío al arrancar
  fi
  echo "venv: $VENV"; echo "código congelado: $(git -C "$FROZEN" rev-parse --short HEAD) ($(cat "$FROZEN.commit"))"
}

lane_plan() {
  PYTHONPATH="$FROZEN/src" "$VENV/bin/python" - "$LANE" "$FROZEN/research/carriles.yaml" <<'PY'
import sys, yaml
reg = yaml.safe_load(open(sys.argv[2], encoding="utf-8"))
lane = next(l for l in reg["carriles"] if l["id"] == sys.argv[1])
assert lane["estado"] == "activo", "carril no activo"
print(lane["plan"], lane["preregistro_commit"])
PY
}

case "$ACTION" in
  setup) setup ;;
  run)
    [ -x "$VENV/bin/python" ] && [ -d "$FROZEN/.git" ] || { echo "falta setup"; exit 3; }
    read -r PLAN COMMIT <<<"$(lane_plan)"
    cd "$FROZEN"
    PYTHONPATH=src "$VENV/bin/python" -m lab.paper_comparison --once --fetch \
      --plan "$FROZEN/$PLAN" --preregistration-commit "$COMMIT" --data-dir "$DATA" | tail -25
    ;;
  status)
    read -r PLAN COMMIT <<<"$(lane_plan)"
    cd "$FROZEN"
    PYTHONPATH=src "$VENV/bin/python" -m lab.paper_comparison --status --plan "$FROZEN/$PLAN" --data-dir "$DATA"
    ;;
  *) echo "acción desconocida: $ACTION"; exit 2 ;;
esac
