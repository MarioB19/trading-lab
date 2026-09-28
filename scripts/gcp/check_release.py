"""Offline regression checks: temporary files and command doubles, never Docker/GCP."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "scripts/gcp/host"
sys.path.insert(0, str(HOST))
from release_contract import WORKER_COMMAND, validate_config, validate_image

SHA = "a" * 40
IMAGE = "us-central1-docker.pkg.dev/test-project/trading-lab/runtime@sha256:" + "b" * 64
CONFIG = {"mode": "paper", "sleeves": {
    "crypto": {"enabled": True, "capital": 500, "strategy": "tactical", "params": {"top_k": 5, "vol_target": .4, "max_weight": .4}},
    "stocks": {"enabled": True, "capital": 500, "strategy": "passive", "mix": {"SPY": .6, "IEF": .4}},
    "multi": {"enabled": False}}, "realtime": {"enabled": True, "action": "observe"}}
IMAGE_CONFIG = {"User": "10001:10001", "WorkingDir": "/app", "Entrypoint": None, "Cmd": WORKER_COMMAND,
                "Labels": {"org.opencontainers.image.revision": SHA, "org.tradinglab.profile": "operational-paper"},
                "Env": ["TRADING_LAB_BUILD_ID=" + SHA, "PYTHONDONTWRITEBYTECODE=1"]}
IMAGE_INFO = [{"Os": "linux", "Architecture": "amd64", "Config": IMAGE_CONFIG}]
count = 0


def expect_rejection(call):
    global count
    try:
        call()
    except (ValueError, TypeError):
        count += 1
    else:
        raise AssertionError("invalid input accepted")


validate_config(CONFIG)
changed_capital = deepcopy(CONFIG)
changed_capital["sleeves"]["crypto"]["capital"] = 1200
validate_config(changed_capital)
count += 2
for key, value in (("top_k", 4), ("vol_target", .8), ("max_weight", 1)):
    config = deepcopy(CONFIG)
    config["sleeves"]["crypto"]["params"][key] = value
    expect_rejection(lambda: validate_config(config))
for change in ("live", "mix", "multi", "realtime", "capital", "zero_capital", "new_sleeve"):
    config = deepcopy(CONFIG)
    if change == "live": config["mode"] = "live"
    if change == "mix": config["sleeves"]["stocks"]["mix"] = {"SPY": 1}
    if change == "multi": config["sleeves"]["multi"]["enabled"] = True
    if change == "realtime": config["realtime"]["action"] = "trade"
    if change == "zero_capital": config["sleeves"]["crypto"]["capital"] = 0
    if change == "capital": config["sleeves"]["crypto"]["capital"] = float("nan")
    if change == "new_sleeve": config["sleeves"]["aggressive"] = {"enabled": True}
    expect_rejection(lambda: validate_config(config))

# Fake commands execute only against this test's temporary tree. The Docker double
# feeds the validator a synthetic config; imports are separately tested in the real image smoke.
FAKE = r'''
import json,os,pathlib,subprocess,sys
root=pathlib.Path(os.environ["FAKE_ROOT"]); name=pathlib.Path(sys.argv[0]).stem; args=sys.argv[1:]
case=os.environ["CASE"]
with (root/"events").open("a") as out: out.write(json.dumps([name,*args])+"\n")
if name=="flock": raise SystemExit(1 if case=="locked" else 0)
if name=="sleep": raise SystemExit(0)
if name=="systemctl": raise SystemExit(0 if case=="systemd_active" else 3)
if name=="curl":
    if case=="token_failure": raise SystemExit(22)
    print(json.dumps({"access_token":"synthetic-test-value"} if "Metadata-Flavor: Google" in args else {"status":"alive","read_only":case!="bad_health"}))
    raise SystemExit(0)
if args[:2]==["ps","-a"]:
    if case=="daemon_failure": raise SystemExit(1)
    calls=sum(json.loads(line)[:3]==["docker","ps","-a"] for line in (root/"events").read_text().splitlines())
    if case in ("running","paused") or case=="activated_during_pull" and calls>1: print("running")
elif args[:2]==["image","inspect"]: print((root/"image.json").read_text())
elif args[0]=="inspect": print((root/"api.json").read_text())
elif args[0]=="login": sys.stdin.read()
elif args[0]=="pull": pass
elif args[0]=="run":
    assert "--entrypoint" in args and args[args.index("--entrypoint")+1]=="python"
    assert "--runtime-imports" in args and "--network" in args and args[args.index("--network")+1]=="none"
    code=sys.stdin.read()
    completed=subprocess.run([sys.executable,"-","config",str(root/"config.json")],input=code,text=True)
    raise SystemExit(completed.returncode)
else: raise SystemExit("unexpected Docker command")
'''
for case in ("success", "flag", "locked", "systemd_active", "running", "paused", "daemon_failure", "activated_during_pull", "bad_profile", "bad_entrypoint", "bad_build_id", "bad_arch", "bad_config", "token_failure"):
    with tempfile.TemporaryDirectory(prefix="trading-release-test-") as temp:
        root = Path(temp)
        for directory in ("bin", "host", "etc", "run", "data"):
            (root / directory).mkdir()
        for name in ("docker", "curl", "flock", "systemctl", "sleep"):
            executable = root / "bin" / name
            python_file = root / "bin" / (name + ".py")
            python_file.write_text(FAKE)
            executable.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(python_file)) + ' "$@"\n')
            executable.chmod(0o755)
        (root / "host/release_contract.py").write_text((HOST / "release_contract.py").read_text())
        settings = f"PROJECT_ID=test-project\nREGISTRY_HOST=us-central1-docker.pkg.dev\nDATA_DIR={root/'data'}\n"
        (root / "etc/settings.conf").write_text(settings)
        original = "TRADING_IMAGE=previous\nSOURCE_SHA=previous\n"
        (root / "etc/release.conf").write_text(original)
        image = deepcopy(IMAGE_INFO)
        config = deepcopy(CONFIG)
        if case == "flag": (root / "data/worker.enabled").write_text("enabled")
        if case == "bad_profile": image[0]["Config"]["Labels"]["org.tradinglab.profile"] = "research"
        if case == "bad_entrypoint": image[0]["Config"]["Entrypoint"] = ["true"]
        if case == "bad_build_id": image[0]["Config"]["Env"][0] = "TRADING_LAB_BUILD_ID=" + "c" * 40
        if case == "bad_arch": image[0]["Architecture"] = "arm64"
        if case == "bad_config": config["sleeves"]["crypto"]["params"]["top_k"] = 6
        (root / "image.json").write_text(json.dumps(image))
        (root / "config.json").write_text(json.dumps(config))
        script = (HOST / "install-release.sh").read_text().replace("/etc/trading-lab", str(root / "etc")).replace("/run/trading", str(root / "run/trading"))
        script_path = root / "host/install-release.sh"
        script_path.write_text(script)
        env = {**os.environ, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"], "CASE": case, "FAKE_ROOT": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(["bash", str(script_path), IMAGE, SHA], env=env, text=True, capture_output=True)
        assert (result.returncode == 0) == (case == "success"), (case, result.stderr)
        current = (root / "etc/release.conf").read_text()
        assert (current != original) == (case == "success"), (case, current)
        if case == "success": assert (root / "etc/previous-release.conf").read_text() == original
        else: assert not (root / "etc/previous-release.conf").exists(), case
        count += 1
        if case == "success":
            api_config = deepcopy(IMAGE_CONFIG)
            api_config["Image"] = IMAGE
            api = [{"State": {"Running": True}, "Config": api_config,
                    "HostConfig": {"ReadonlyRootfs": True, "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}}}]
            (root / "api.json").write_text(json.dumps(api))
            verifier = root / "host/verify-release.sh"
            verifier.write_text((HOST / "verify-release.sh").read_text())
            for check in ("healthy", "wrong_digest", "bad_health"):
                env["CASE"] = check
                api[0]["Config"]["Image"] = IMAGE if check != "wrong_digest" else IMAGE[:-1] + "c"
                (root / "api.json").write_text(json.dumps(api))
                verified = subprocess.run(["bash", str(verifier), IMAGE, SHA], env=env, text=True, capture_output=True)
                assert (verified.returncode == 0) == (check == "healthy"), (check, verified.stderr)
                count += 1

spec = importlib.util.spec_from_file_location("preflight_under_test", ROOT / "scripts/gcp/preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
for case in ("clean", "dirty", "wrong_sha", "image", "research_image", "remote_docker", "missing_tools"):
    with tempfile.TemporaryDirectory(prefix="trading-preflight-test-") as temp:
        fixture = Path(temp)
        (fixture / "config.yaml").write_text(json.dumps(CONFIG))
        def fake_run(command):
            if command == ["git", "rev-parse", "HEAD"]: return SHA
            if command == ["git", "status", "--porcelain", "--untracked-files=all"]: return " M example" if case == "dirty" else ""
            if command[:3] == ["docker", "context", "inspect"]: return "tcp://remote:2376" if case == "remote_docker" else "unix:///docker.sock"
            if command[:3] == ["docker", "image", "inspect"]:
                document = deepcopy(IMAGE_INFO)
                if case == "research_image": document[0]["Config"]["Labels"]["org.tradinglab.profile"] = "research"
                return json.dumps(document)
            raise AssertionError("Unexpected external command " + repr(command))
        args = ["--expected-sha", "c" * 40 if case == "wrong_sha" else SHA]
        if case in ("image", "research_image", "remote_docker"): args += ["--image", IMAGE]
        if case == "missing_tools": args += ["--require-tools"]
        stream = io.StringIO()
        with patch.object(preflight, "ROOT", fixture), patch.object(preflight, "run", fake_run), patch.object(preflight.shutil, "which", lambda name: None if case == "missing_tools" else "/fake/tool"), patch.dict(os.environ, {"DOCKER_HOST": ""}), redirect_stdout(stream):
            result = preflight.main(args)
        report = json.loads(stream.getvalue())
        assert (result == 0) == (case in ("clean", "image")), (case, report)
        assert report["cloud_accessed"] is False and report["connection_attempted"] is False
        count += 1
print(f"{count} offline configuration, installer, API readback and preflight checks passed")
