"""Checks offline de trazabilidad; no calculan rentabilidad de mercado."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

from lab.experiments import ResearchGateError


spec = importlib.util.spec_from_file_location(
    "rotation_v2", Path(__file__).resolve().parents[1] / "scripts/research/rotation_v2.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_correction_preserves_raw_and_other_numeric_text():
    raw = b"date,BTC,AVAX\n2020-07-13,123.123456789,2.12\n2020-07-14,124.0,2.13\n2020-09-22,125.1,3.456789\n"
    policy = {"asset": "AVAX", "available_from": "2020-09-22", "evidence_sha256": "a" * 64}
    result, audit = launcher.corrected_csv(raw, policy)
    assert result == b"date,BTC,AVAX\n2020-07-13,123.123456789,\n2020-07-14,124.0,\n2020-09-22,125.1,3.456789\n"
    assert b"2.12" in raw and audit["quarantined_count"] == 2
    assert not audit["raw_mutated"] and not audit["interpolation"]


def test_sources_refuse_changed_bytes_missing_files_and_changed_evidence(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"evidence")
    policy = {"evidence_sha256": hashlib.sha256(b"evidence").hexdigest()}
    expected = {}
    for name in launcher.NAMES:
        (tmp_path / name).write_bytes(name.encode())
        expected[name] = hashlib.sha256(name.encode()).hexdigest()
    assert len(launcher.verified_sources(tmp_path, expected, evidence, policy)) == 4
    (tmp_path / "crypto_prices.csv").write_bytes(b"changed")
    with pytest.raises(ResearchGateError, match="original cambió"):
        launcher.verified_sources(tmp_path, expected, evidence, policy)
    (tmp_path / "crypto_prices.csv").write_bytes(b"crypto_prices.csv")
    evidence.write_bytes(b"changed evidence")
    with pytest.raises(ResearchGateError, match="evidencia"):
        launcher.verified_sources(tmp_path, expected, evidence, policy)
    with pytest.raises(ResearchGateError, match="entradas"):
        launcher.verified_sources(tmp_path, {}, evidence, policy)
