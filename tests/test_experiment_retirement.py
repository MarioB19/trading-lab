"""Retirement gate only: no data, Docker daemon, scheduler or market access."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("arguments", [[], ["--force"], ["--once", "--fetch"]])
def test_archived_entrypoint_refuses_valid_old_authorization_before_preflight_or_docker(tmp_path, arguments):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    run = scripts / "run.sh"
    run.write_bytes((ROOT / "scripts/paper/run.sh").read_bytes())
    release = tmp_path / "release.json"
    code = "f6c19fdcac943978011b3e096280beb7d0528884"
    release.write_text(json.dumps({"mode": "paper", "code_commit": code,
                                  "preregistration_commit": "1fe6c8c586b6a9899190b4f987807daf9134846c",
                                  "image": "us-central1-docker.pkg.dev/example/trading-lab/runtime@sha256:" + "a" * 64}))
    enabled = tmp_path / "aggressive-v2.enabled"
    enabled.write_text(code + "\n")
    assert enabled.read_text().strip() == json.loads(release.read_text())["code_commit"]
    # An installed legacy setup could pass preflight. It must not even be sourced.
    (scripts / "common.sh").write_text(
        'printf sourced > "$TRIPWIRE_SOURCE"\n'
        'paper_preflight() { printf called > "$TRIPWIRE_PREFLIGHT"; }\n')
    fake_docker = tmp_path / "docker"
    fake_docker.write_text('#!/bin/sh\nprintf called > "$TRIPWIRE_DOCKER"\nexit 0\n')
    fake_docker.chmod(0o755)
    tripwires = {"TRIPWIRE_SOURCE": tmp_path / "sourced", "TRIPWIRE_PREFLIGHT": tmp_path / "preflight",
                 "TRIPWIRE_DOCKER": tmp_path / "docker-called"}
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
           "PAPER_RELEASE": str(release), "PAPER_ENABLED": str(enabled),
           **{key: str(path) for key, path in tripwires.items()}}
    before = (release.read_bytes(), enabled.read_bytes())
    result = subprocess.run(["bash", str(run), *arguments], env=env, text=True,
                            capture_output=True, timeout=5)
    assert result.returncode == 2
    assert "aggressive-v2 archivado" in result.stderr and "7 criterios" in result.stderr
    assert all(not path.exists() for path in tripwires.values())
    assert (release.read_bytes(), enabled.read_bytes()) == before


def test_prepared_service_still_points_to_the_blocked_entrypoint():
    service = (ROOT / "scripts/paper/trading-lab-comparison.service").read_text()
    assert "ExecStart=/usr/local/lib/trading-lab-paper/run.sh" in service
    subprocess.run(["bash", "-n", str(ROOT / "scripts/paper/run.sh")], check=True)
