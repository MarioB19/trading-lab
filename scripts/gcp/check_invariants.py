"""Local checks for deployment hard boundaries; no cloud API calls."""
from pathlib import Path
import json
from itertools import product
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
infra = ROOT / "infra/gcp"
scripts = ROOT / "scripts/gcp"
docker = (ROOT / "Dockerfile").read_text()
assert "@sha256:" in docker, "Pin the base image"
assert "USER 10001:10001" in docker
assert 'org.tradinglab.profile="operational-paper"' in docker
assert "TRADING_LAB_BUILD_ID=${SOURCE_SHA}" in docker
assert not re.search(r"COPY\s+\.\s", docker), "Never copy credentials/state with the build context"
for path in scripts.rglob("*.sh"):
    subprocess.run(["bash", "-n", str(path)], check=True)
for path in infra.glob("systemd/*.service"):
    assert "--live" not in path.read_text()
worker = (infra / "systemd/trading-lab-worker.service").read_text()
assert "ConditionPathExists=/var/lib/trading-lab/worker.enabled" in worker
assert "127.0.0.1:8080:8080" in (scripts / "host/run-container.sh").read_text()
assert "gcloud auth login" not in (scripts / "preflight.sh").read_text()
assert "roles/storage.objectCreator" in (infra / "main.tf").read_text()
assert re.search(r'ports\s*=\s*\["22"\]', (infra / "main.tf").read_text())
assert 'source_ranges' in (infra / "main.tf").read_text()
assert 'source_sha' in (infra / "variables.tf").read_text()
assert 'workflow_dispatch:' in (ROOT / ".github/workflows/gcp-image.yml").read_text()
assert 'requirements-dev.lock.txt' in (ROOT / ".github/workflows/gcp-image.yml").read_text()
# Render both bootstrap branches with a standalone Terraform console: no provider,
# credentials, state, cloud calls or execution of the generated script.
files = {}
for path in (scripts / "host").iterdir():
    if path.suffix not in {".sh", ".py"}:
        continue
    files[f"/usr/local/lib/trading-lab/{path.name}"] = {"content": path.read_text(), "mode": "0755"}
for path in (infra / "systemd").glob("*"):
    files[f"/etc/systemd/system/{path.name}"] = {"content": path.read_text(), "mode": "0644"}
for image, experimental in product(("", "us-central1-docker.pkg.dev/test-project/trading-lab/runtime@sha256:" + "a" * 64), (False, True)):
    args = dict(files=files, project_id="test-project", region="us-central1", bucket="test-project-backups",
                image_uri=image, source_sha="b" * 40, paper_refs_b64="e30=", experimental_storage=experimental)
    with tempfile.TemporaryDirectory(prefix="trading-bootstrap-check-") as temp:
        args_path = Path(temp) / "template-arguments.json"
        args_path.write_text(json.dumps(args))
        expression = f'templatefile({json.dumps(str(infra / "templates/startup.sh.tftpl"))}, jsondecode(file({json.dumps(str(args_path))})))\n'
        result = subprocess.run([os.environ.get("TERRAFORM_BIN", "terraform"), "console"],
                                input=expression, text=True, cwd=temp, capture_output=True, check=True)
        # Terraform console uses a heredoc for multiline strings.
        rendered = result.stdout
        if rendered.startswith("<<"):
            rendered = "\n".join(rendered.splitlines()[1:-1]) + "\n"
        else:
            rendered = json.loads(rendered)
        subprocess.run(["bash", "-n"], input=rendered, text=True, check=True)
        assert "lab.ops activate" not in rendered.replace("# Never enables the worker. Explicit lab.ops activate is required after cutover.", "")
        assert "mount_data_disk /dev/disk/by-id/google-trading-state /var/lib/trading-lab" in rendered
        assert ("mount_data_disk /dev/disk/by-id/google-trading-experiments /var/lib/trading-experiments" in rendered) == experimental
        assert ("/var/lib/trading-experiments/aggressive-v2 /var/lib/trading-experiments/backups" in rendered) == experimental
        assert ('install -d -o 10001 -g 10001 -m 0700 "$directory"' in rendered) == experimental
        assert 'findmnt -n -o UUID --mountpoint "$target"' in rendered
        assert "trading-lab-paper" not in rendered, "Do not install or activate experimental services implicitly"
print("Deployment boundaries verified locally")
