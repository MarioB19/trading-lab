#!/usr/bin/env python3
"""Single-process, synthetic-only OCI smoke; no brokers, market fetch or pytest."""
import argparse
import hashlib
import importlib.util
import json
import os
import platform
import resource
from pathlib import Path
import sys
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-build-id", required=True)
    parser.add_argument("--app-root", type=Path, default=Path("/app"))
    args = parser.parse_args()
    assert sys.version_info >= (3, 13), sys.version
    assert platform.machine() == "x86_64", platform.machine()
    assert os.getuid() == os.geteuid() == 10001, (os.getuid(), os.geteuid())
    assert os.environ.get("TRADING_LAB_BUILD_ID") == args.expected_build_id
    assert len(args.expected_build_id) == 40
    for name in ("state", "data", ".git", ".env", "reports", "configs/experiments"):
        assert not (args.app_root / name).exists(), name
    assert not list(args.app_root.glob(".env.*"))
    assert importlib.util.find_spec("scipy") is None
    assert importlib.util.find_spec("pytest") is None
    import yaml
    from lab import ops, runtime, service
    from lab.bot import load_config
    from lab.storage import SQLiteStore
    config = args.app_root / "config.yaml"
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    assert yaml.safe_load(config.read_text())["mode"] == "paper"
    runtime.validate_config(load_config(config))

    with tempfile.TemporaryDirectory(prefix="trading-runtime-smoke-") as temporary:
        base = Path(temporary)
        target, source, restored = base / "runtime", base / "synthetic-legacy", base / "restored"
        source.mkdir()
        server = service.make_server(target, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"

        def request(endpoint, code=200, method="GET"):
            req = Request(url + endpoint, data=b"{}" if method != "GET" else None, method=method)
            try:
                response = urlopen(req, timeout=10)
            except HTTPError as error:
                response = error
            with response:
                assert response.status == code, (endpoint, response.status, code)
                body = response.read()
                assert response.headers.get("Cache-Control") == "no-store"
                return json.loads(body) if "application/json" in response.headers.get("Content-Type", "") else body

        try:
            assert request("/healthz")["read_only"] is True
            assert request("/readyz", 503)["ready"] is False
            assert request("/api/status")["mode"] == "unverified"
            comparison = request("/api/comparison")
            assert comparison["paper"]["status"] == comparison["research"]["status"] == "not_configured"
            assert not (target / runtime.DATABASE_NAME).exists()
            assert b"<html" in request("/").lower()
            assert request("/operations.js") and request("/operations.css")
            request("/api/orders", 405, "POST")
            state = {"mode": "paper", "sleeves": {"crypto": {
                "mode": "paper", "capital_base": 500, "peak": 500,
                "ledger": {"cash": 400, "positions": {"BTC": 1}}, "last_candle": "2026-09-26"}}}
            snapshot = {"mode": "paper", "sleeves": {"crypto": {
                "mode": "paper", "status": "ok", "equity": 500}}}
            for filename, document in (("state.json", state), ("snapshot.json", snapshot), ("live.json", snapshot)):
                (source / filename).write_text(json.dumps(document))
            (source / "trades.csv").write_text("run_at_utc,sleeve,mode,asset,side,qty,price,value,status\n"
                                                "2026-09-26 00:20,crypto,paper,BTC,buy,1,100,100,filled\n")
            (source / "equity.csv").write_text("date,sleeve,mode,equity,cash,flow\n"
                                                "2026-09-26,crypto,paper,500,400,\n")
            original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
            deployment = ops.import_legacy(source, target)
            assert deployment["mode"] == "paper" and deployment["cloud_connected"] is False
            assert deployment["source_sha256"] == original
            inspected = ops.inspect(target)
            assert inspected["health"]["integrity"] == "ok" and not inspected["worker_enabled"]
            status = request("/api/status")
            assert status["mode"] == "paper" and status["ready"] is False
            assert status["storage"]["schema_version"] == 1
            assert len(request("/api/trades")["items"]) == 1
            assert len(request("/api/equity")["items"]) == 1
            assert request("/readyz", 503)["ready"] is False
            destination = base / "backup" / "synthetic.sqlite3"
            backup = ops.backup(target, destination)
            assert ops.verify_backup(destination)["sha256"] == backup["sha256"]
            assert backup["build_id"] == args.expected_build_id
            # Emulate downloading only the two objects to a read-only directory.
            import shutil
            downloaded = base / "downloaded"
            downloaded.mkdir()
            for item in (destination, destination.with_suffix(".sqlite3.manifest.json")):
                copied = downloaded / item.name
                shutil.copyfile(item, copied)
                copied.chmod(0o444)
            downloaded.chmod(0o555)
            try:
                assert ops.verify_backup(downloaded / destination.name)["sha256"] == backup["sha256"]
                assert len(list(downloaded.iterdir())) == 2
            finally:
                downloaded.chmod(0o700)
            # Restore takes a lock beside its source; staging must be writable.
            ops.restore(downloaded / destination.name, restored)
            checked = ops.inspect(restored)
            assert checked["health"]["integrity"] == "ok" and not checked["worker_enabled"]
            assert checked["runtime"]["last_success_utc"] is None
            assert service.Reader(restored).status()["ready"] is False
            assert SQLiteStore(restored / runtime.DATABASE_NAME).rows("trades") == SQLiteStore(
                target / runtime.DATABASE_NAME).rows("trades")
            assert original == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
            assert not (restored / "worker.enabled").exists() and not (target / "worker.enabled").exists()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)
            assert not thread.is_alive()
    assert hashlib.sha256(config.read_bytes()).hexdigest() == config_hash
    for name in ("state", "data", ".git", ".env", "reports", "configs/experiments"):
        assert not (args.app_root / name).exists()
    print(json.dumps({"status": "passed", "build_id": args.expected_build_id, "uid": os.getuid(), "machine": platform.machine(), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      "config_sha256": config_hash, "synthetic_only": True, "external_effects": False,
                      "checks": ["paper_config", "runtime_imports", "no_operational_data_in_image",
                                 "empty_api_health_ready", "read_only_panel", "legacy_import",
                                 "sqlite_integrity", "backup_checksum", "downloaded_backup_readonly", "restore_disabled", "research_excluded"]}, sort_keys=True))


if __name__ == "__main__":
    main()
