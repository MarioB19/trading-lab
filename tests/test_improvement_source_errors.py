"""Local source failure reproduction; no Railway or trading experiment calls."""
import json
import shlex
import subprocess
import sys

import pytest

from lab import improvement_sources as sources


@pytest.fixture(autouse=True)
def installed_cli(monkeypatch):
    # These tests exercise SSH response/error contracts, not package resolution.
    monkeypatch.setattr(sources, "railway_cli", lambda: ["railway"])


def run_reader(script):
    return subprocess.run([sys.executable, "-c", sources.diagnostic_script(script)],
                          capture_output=True, text=True, timeout=10)


def test_wrapper_keeps_successful_source_output_exactly():
    script = "print('IMPROVEMENT_SOURCE={\"mode\":\"paper\",\"current\":{\"equity_usd\":995}}')"
    result = run_reader(script)
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == 'IMPROVEMENT_SOURCE={"mode":"paper","current":{"equity_usd":995}}\n'


def test_remote_http_error_keeps_endpoint_code_and_source_lines_without_error_values():
    result = run_reader("""from urllib.error import HTTPError
def get(path):
    raise HTTPError('https://user:secret-value@private.invalid',503,'secret-value',None,None)
get('/api/status')
""")
    assert result.returncode == 1 and result.stderr == ""
    assert "secret-value" not in result.stdout and "private.invalid" not in result.stdout
    detail = json.loads(result.stdout.split(sources.ERROR_MARKER, 1)[1])
    assert detail == {"stage": "remote_python", "exception_type": "HTTPError",
                      "endpoint": "/api/status", "http_status": 503, "source_lines": [4, 3]}


@pytest.mark.parametrize("script,kind", [
    ("raise KeyError('secret-value')", "KeyError"),
    ("class secret_value(Exception): pass\nraise secret_value('secret-value')", "other"),
])
def test_wrapper_never_prints_arbitrary_exception_text_or_class(script, kind):
    result = run_reader(script)
    assert result.returncode == 1 and result.stderr == ""
    assert "secret" not in result.stdout
    detail = json.loads(result.stdout.split(sources.ERROR_MARKER, 1)[1])
    assert detail["exception_type"] == kind and detail["source_lines"]


def test_diagnostic_is_a_bounded_allowlist_even_if_modified_after_exception_creation():
    failure = sources.SourceReadError({"stage": "remote_python"})
    failure.diagnostic.update({"endpoint": "/secret-value", "message": "secret-value",
        "exception_type": "secret-value", "returncode": True, "errno": "secret-value",
        "http_status": 999, "source_lines": [True, "secret-value", -2, *range(1, 30)],
        "observed_markers": ["secret-value", "websocket", "websocket"]})
    def reader(name):
        if name == "arena":
            raise failure
        return {"mode": "paper"}
    result = sources.collect(reader)
    assert result["pilot"] == {"mode": "paper"} and "arena" not in result
    assert "secret-value" not in json.dumps(result)
    assert result["collection_errors"]["arena"]["diagnostic"] == {
        "stage": "remote_python", "source_lines": list(range(1, 9)),
        "observed_markers": ["websocket"]}


def test_transport_failure_records_only_known_markers_and_exit_code(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 1, stdout="secret-value", stderr="secret-value ENOTEMPTY websocket")
    monkeypatch.setattr(sources.subprocess, "run", run)
    with pytest.raises(sources.SourceReadError) as caught:
        sources._read("arena")
    assert caught.value.diagnostic == {"stage": "transport", "reason": "nonzero_exit",
                                       "returncode": 1, "observed_markers": ["npm_enotempty", "websocket"]}
    command, kwargs = calls[0]
    assert kwargs == {"capture_output": True, "text": True, "timeout": 90}
    assert shlex.split(command[-1]) == ["python", "-c", sources.diagnostic_script(sources.ARENA)]
    assert "secret-value" not in str(caught.value) + json.dumps(caught.value.diagnostic)


@pytest.mark.parametrize("error,expected", [
    (subprocess.TimeoutExpired(["secret-value"], 90, output="secret-value", stderr="secret-value"),
     {"stage": "transport", "reason": "timeout", "timeout_seconds": 90}),
    (OSError(13, "secret-value", "secret-value"), {"stage": "process_start", "errno": 13}),
])
def test_process_errors_remain_fail_closed_and_redacted(monkeypatch, error, expected):
    def run(*args, **kwargs):
        raise error
    monkeypatch.setattr(sources.subprocess, "run", run)
    with pytest.raises(sources.SourceReadError) as caught:
        sources._read("pilot")
    assert caught.value.diagnostic == expected
    result = sources.collect()
    assert "pilot" not in result and "arena" not in result
    assert "secret-value" not in json.dumps(result)


@pytest.mark.parametrize("stdout,reason", [
    ("secret-value", "missing_marker"),
    ("IMPROVEMENT_SOURCE=secret-value", "invalid_json"),
])
def test_invalid_response_never_exposes_payload(monkeypatch, stdout, reason):
    monkeypatch.setattr(sources.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, stdout=stdout, stderr="secret-value"))
    result = sources.collect()
    for failure in result["collection_errors"].values():
        assert failure["diagnostic"] == {"stage": "response", "reason": reason}
    assert "secret-value" not in json.dumps(result)


@pytest.mark.parametrize("packet", ['{"exception_type":"secret-value","endpoint":"/secret-value"}', '"secret-value"', 'secret-value'])
def test_failure_marker_blocks_even_if_success_is_also_reported(monkeypatch, packet):
    stdout = sources.ERROR_MARKER + packet + '\nIMPROVEMENT_SOURCE={"mode":"paper"}\n'
    monkeypatch.setattr(sources.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, stdout=stdout, stderr="secret-value"))
    result = sources.collect()
    assert "pilot" not in result and "arena" not in result
    assert "secret-value" not in json.dumps(result)
    assert all(e["diagnostic"] == {"stage": "remote_python", "returncode": 0}
               for e in result["collection_errors"].values())


def test_success_response_is_unchanged_after_wrapper(monkeypatch):
    expected = {"mode": "paper", "healthy": False, "reconciled": False}
    monkeypatch.setattr(sources.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, stdout="IMPROVEMENT_SOURCE=" + json.dumps(expected), stderr=""))
    result = sources.collect()
    assert result["pilot"] == expected and result["arena"] == expected
    assert result["collection_errors"] == {}
