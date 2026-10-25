"""Carriles de candidatas (F4): el control da exactamente lo mismo con y sin carriles."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
import yaml

from lab import lanes, ops, runtime
from lab.storage import SQLiteStore

COMMIT = "a" * 40


def registry(tmp_path, *states):
    data = {"version": 1, "max_activos": 2, "capital_usd": 500, "carriles": [
        {"id": f"carril-{i + 1}", "estado": state, "hipotesis": "H1b" if state == "activo" else None,
         "plan": "configs/experiments/rotation_paper_v1.yaml" if state == "activo" else None,
         "preregistro_commit": COMMIT if state == "activo" else None}
        for i, state in enumerate(states)]}
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "carriles.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def pilot(tmp_path, name):
    source = tmp_path / f"{name}-legacy"
    source.mkdir()
    (source / "state.json").write_text(json.dumps({"sleeves": {"crypto": {
        "mode": "paper", "capital_base": 500, "peak": 500,
        "ledger": {"cash": 400, "positions": {"BTC": 1}}, "last_candle": "2026-09-26"}}}))
    (source / "snapshot.json").write_text(json.dumps({"mode": "paper", "sleeves": {
        "crypto": {"mode": "paper", "status": "ok", "equity": 500}}}))
    (source / "live.json").write_text(json.dumps({"mode": "paper", "sleeves": {
        "crypto": {"mode": "paper", "status": "ok", "equity": 500}}}))
    (source / "trades.csv").write_text("run_at_utc,sleeve,mode,asset,side,qty,price,value,status\n"
                                       "2026-09-26 00:20,crypto,paper,BTC,buy,1,100,100,filled\n")
    (source / "equity.csv").write_text("date,sleeve,mode,equity,cash,flow\n2026-09-26,crypto,paper,500,400,\n")
    target = tmp_path / name / "runtime"
    ops.import_legacy(source, target)
    config = target / "config.yaml"
    config.write_text("mode: paper\nsleeves:\n  crypto:\n    enabled: true\n")
    return target, SQLiteStore(target / runtime.DATABASE_NAME), config


def cycle(tmp_path, name, registry_path, monkeypatch, *, lane_fails=False):
    target, store, config = pilot(tmp_path, name)
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[2] == "lab.realtime":
            store.write_document("live", {"mode": "paper", "sleeves": {"crypto": {"status": "ok"}}})
        if cmd[2] == "lab.paper_comparison":
            assert str(target) not in " ".join(cmd) and str(config) not in cmd
            if lane_fails:
                raise OSError("carril roto")
            return subprocess.CompletedProcess(cmd, 1, "", "falla del carril")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(lanes, "REGISTRY", registry_path)
    health = runtime.run_cycle(config, store, 300, runner=runner)
    docs = {name: store.read_document(name) for name in ("state", "snapshot", "live")}
    rows = {table: store.rows(table) for table in ("trades", "equity")}
    pilot_calls = [c[2:3] + [a for a in c[3:] if not str(a).startswith(str(tmp_path))] for c in calls
                   if c[2] != "lab.paper_comparison"]
    lane_calls = [c for c in calls if c[2] == "lab.paper_comparison"]
    stable = {k: v for k, v in health.items() if k not in {"last_attempt_utc", "last_success_utc", "last_completed_utc",
                                                           "duration_seconds", "config_sha256"}}
    return stable, docs, rows, pilot_calls, lane_calls, calls


def test_control_is_identical_with_and_without_lanes(tmp_path, monkeypatch):
    without = cycle(tmp_path, "sin", registry(tmp_path / "r0", "vacio", "vacio"), monkeypatch)
    with_lane = cycle(tmp_path, "con", registry(tmp_path / "r1", "activo", "vacio"), monkeypatch)
    failing = cycle(tmp_path, "falla", registry(tmp_path / "r2", "activo", "activo"), monkeypatch, lane_fails=True)
    assert without[0]["status"] == "ok"
    for other in (with_lane, failing):
        assert other[0] == without[0]          # salud del ciclo del piloto
        assert other[1] == without[1]          # documentos del piloto
        assert other[2] == without[2]          # operaciones y patrimonio del piloto
        assert other[3] == without[3]          # mismos comandos del piloto, en el mismo orden
    assert without[4] == [] and len(with_lane[4]) == 1 and len(failing[4]) == 2
    calls = with_lane[5]
    lane_index = next(i for i, c in enumerate(calls) if c[2] == "lab.paper_comparison")
    assert [c[2] for c in calls[:lane_index]] == ["lab.bot", "lab.realtime"]  # el carril corre después del piloto
    assert str(tmp_path / "con" / "lanes" / "carril-1") in calls[lane_index]


def test_lanes_run_once_per_day_and_only_when_active(tmp_path):
    path = registry(tmp_path, "activo", "pausado")
    seen = []
    runner = lambda cmd, **k: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
    assert len(lanes.run_active(tmp_path / "lanes", registry_path=path, runner=runner, today="2026-11-09")) == 1
    assert lanes.run_active(tmp_path / "lanes", registry_path=path, runner=runner, today="2026-11-09") == []
    assert len(lanes.run_active(tmp_path / "lanes", registry_path=path, runner=runner, today="2026-11-10")) == 1
    assert len(seen) == 2 and all("--data-dir" in c and "carril-1" in c[c.index("--data-dir") + 1] for c in seen)


@pytest.mark.parametrize("states,error", [(("activo", "activo", "activo"), "carril"), (("bogus",), "estado")])
def test_registry_limits(tmp_path, states, error):
    with pytest.raises(ValueError, match=error):
        lanes.load(registry(tmp_path, *states))


def test_active_lane_requires_preregistered_plan(tmp_path):
    path = registry(tmp_path, "activo")
    data = yaml.safe_load(path.read_text())
    data["carriles"][0]["preregistro_commit"] = None
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="preregistro"):
        lanes.load(path)


def test_versioned_registry_is_empty_and_panel_status_reads_it(tmp_path):
    data = lanes.load()
    assert [lane["estado"] for lane in data["carriles"]] == ["vacio", "vacio"]
    status = lanes.status(tmp_path / "lanes")
    assert status["active"] == 0 and status["max_active"] == 2 and len(status["lanes"]) == 2
    assert not (tmp_path / "lanes").exists()  # leer no crea carpetas
