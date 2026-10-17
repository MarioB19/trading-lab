"""One package resolution per collection; SSH remains concurrent and fail closed."""
import json
import subprocess
from threading import Barrier

import pytest

from lab import improvement_sources as sources


def test_collection_resolves_once_before_two_concurrent_ssh_reads(monkeypatch, tmp_path):
    executable = tmp_path / "railway"
    executable.write_text("placeholder")
    executable.chmod(0o700)
    barrier, calls, installers = Barrier(2), [], []
    monkeypatch.setattr(sources.shutil, "which", lambda name: None)
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "npx":
            installers.append(command)
            assert len(installers) == 1
            return subprocess.CompletedProcess(command, 0, stdout=str(executable)+"\n", stderr="")
        assert command[:2] == [str(executable), "ssh"] and len(installers) == 1
        assert kwargs["timeout"] == 90
        barrier.wait(timeout=3)
        name = next(k for k,v in sources.SERVICES.items() if v in command)
        return subprocess.CompletedProcess(command, 0,
            stdout='IMPROVEMENT_SOURCE='+json.dumps({"mode":"paper","source":name}), stderr="")
    monkeypatch.setattr(sources.subprocess, "run", run)
    result = sources.collect()
    assert result["collection_errors"] == {}
    assert result["pilot"] == {"mode":"paper","source":"pilot"}
    assert result["arena"] == {"mode":"paper","source":"arena"}
    assert len(calls)==3 and calls[0][1]["timeout"]==30


def test_installed_cli_avoids_package_installer(monkeypatch):
    monkeypatch.setattr(sources.shutil, "which", lambda name: "/approved/bin/railway")
    monkeypatch.setattr(sources.subprocess, "run", lambda *a, **k: pytest.fail("npm must not run"))
    assert sources.railway_cli() == ["/approved/bin/railway"]


@pytest.mark.parametrize("stdout", ["", "railway", "/missing/railway", "/one\n/two", "\0"])
def test_invalid_resolved_executable_blocks_without_exposing_paths(monkeypatch, stdout):
    monkeypatch.setattr(sources.shutil, "which", lambda name: None)
    monkeypatch.setattr(sources.subprocess, "run", lambda *a, **k:
        subprocess.CompletedProcess(a,0,stdout=stdout,stderr="secret-value"))
    result=sources.collect()
    assert not any(name in result for name in sources.SERVICES)
    assert all(e["diagnostic"]=={"stage":"cli_resolution","reason":"invalid_cli_path"}
               for e in result["collection_errors"].values())
    assert "secret-value" not in json.dumps(result)


def test_installer_rename_failure_blocks_both_sources_before_ssh(monkeypatch):
    monkeypatch.setattr(sources.shutil, "which", lambda name: None)
    calls=[]
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command,190,stdout="secret-value",stderr="ENOTEMPTY secret-value")
    monkeypatch.setattr(sources.subprocess,"run",run)
    result=sources.collect()
    assert len(calls)==1 and set(result["collection_errors"])==set(sources.SERVICES)
    assert "secret-value" not in json.dumps(result)
    assert all(e["diagnostic"]=={"stage":"cli_resolution","reason":"nonzero_exit",
        "returncode":190,"observed_markers":["npm_enotempty"]} for e in result["collection_errors"].values())


@pytest.mark.parametrize("error,expected", [
    (subprocess.TimeoutExpired(["secret-value"],30,output="secret-value"),
     {"stage":"cli_resolution","reason":"timeout","timeout_seconds":30}),
    (OSError(13,"secret-value"), {"stage":"cli_resolution","errno":13}),
])
def test_resolver_process_errors_stay_redacted_and_fail_closed(monkeypatch,error,expected):
    monkeypatch.setattr(sources.shutil,"which",lambda name:None)
    def run(*args,**kwargs): raise error
    monkeypatch.setattr(sources.subprocess,"run",run)
    result=sources.collect()
    assert not any(name in result for name in sources.SERVICES)
    assert "secret-value" not in json.dumps(result)
    assert all(e["diagnostic"]==expected for e in result["collection_errors"].values())


def test_injected_reader_needs_no_cli_resolution(monkeypatch):
    monkeypatch.setattr(sources,"railway_cli",lambda:pytest.fail("no transport for injected reader"))
    result=sources.collect(lambda name:{"mode":"paper","source":name})
    assert result["collection_errors"]=={} and result["arena"]["source"]=="arena"
