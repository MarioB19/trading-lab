#!/usr/bin/env bash
set -Eeuo pipefail
# Keep this terminal disposition before common.sh/preflight: old release files,
# activation markers and timers cannot reactivate a rejected experiment.
printf '%s\n' 'aggressive-v2 archivado: rechaza los 7 criterios preregistrados. Ejecución retirada; sólo consulta y respaldo de evidencia.' >&2
exit 2
