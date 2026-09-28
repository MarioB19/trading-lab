#!/usr/bin/env bash
# Terraform init downloads providers only; validate never accesses a GCP account.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
terraform_bin=${TERRAFORM_BIN:-terraform}
for script in "$root"/scripts/gcp/*.sh "$root"/scripts/gcp/host/*.sh; do bash -n "$script"; done
"$terraform_bin" -chdir="$root/infra/gcp" fmt -check -recursive
"$terraform_bin" -chdir="$root/infra/gcp" init -backend=false -input=false
"$terraform_bin" -chdir="$root/infra/gcp" validate
"$terraform_bin" -chdir="$root/infra/gcp" test -no-color
python3 "$root/scripts/gcp/check_invariants.py"
