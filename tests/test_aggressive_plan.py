"""Specification and isolation checks, without market data or performance trials."""
import copy
from pathlib import Path

import pytest

from lab import aggressive_plan
from lab.experiments import ResearchGateError, canonical_hash, file_hash


# Los experimentos aggressive-v1/v2 y rotation-paper-v1 (cerrados) se registraron contra el config.yaml
# anterior a DEC-033 (25-oct-2026, orden mínima 5 → 25). Esa línea base queda congelada en
# configs/experiments/baseline_config_pre_dec033.yaml; el control vivo ya no coincide con esos planes.
PRE_DEC033_BASELINE = aggressive_plan.ROOT / "configs/experiments/baseline_config_pre_dec033.yaml"


def test_plan_is_fixed_and_matches_its_registered_baseline():
    plan, variants = aggressive_plan.comparison_plan()
    assert file_hash(PRE_DEC033_BASELINE) == plan["baseline_config_sha256"]
    aggressive_plan.validate_registered_variants(plan)
    assert len(variants) == 2 and {v['role'] for v in variants} == {'control', 'aggressive'}
    assert len({v['id'] for v in variants}) == 2
    control, candidate = (plan['portfolios'][k] for k in ('control', 'aggressive'))
    assert control['stocks'] == candidate['stocks']
    assert control['crypto']['params']['top_k'] == 5
    assert candidate['crypto']['params']['top_k'] == 3
    assert candidate['crypto']['params']['vol_target'] == .6
    assert all(sum(sc['capital'] for sc in blocks.values()) == 1000 for blocks in plan['portfolios'].values())
    mutated = copy.deepcopy(plan)
    mutated['portfolios']['aggressive']['crypto']['capital'] = 1000
    with pytest.raises(ResearchGateError):
        aggressive_plan.validate_plan(mutated)
    assert canonical_hash(aggressive_plan.comparison_plan()[0]) == canonical_hash(plan)


@pytest.mark.parametrize('path', ['state', 'state/subdir', 'data', 'src/new', 'configs', '.git', '.'])
def test_experimental_writer_cannot_use_operational_paths(path):
    with pytest.raises(ResearchGateError):
        aggressive_plan.isolated_directory(aggressive_plan.ROOT / path)


def test_experimental_paths_cannot_hide_inside_symlinks(tmp_path):
    link = tmp_path / 'pretend-experiment'
    link.symlink_to(aggressive_plan.ROOT / 'state', target_is_directory=True)
    with pytest.raises(ResearchGateError):
        aggressive_plan.isolated_directory(link / 'nested')
    assert aggressive_plan.isolated_directory(tmp_path/'paper') == (tmp_path/'paper').resolve()


def test_closed_experiments_no_longer_match_the_live_control():
    plan, _ = aggressive_plan.comparison_plan()
    with pytest.raises(ResearchGateError, match='nuevo protocolo'):
        aggressive_plan.assert_current_control(plan)


def test_configuration_change_requires_new_protocol():
    plan, _ = aggressive_plan.comparison_plan()
    plan['baseline_config_sha256'] = '0' * 64
    with pytest.raises(ResearchGateError, match='nuevo protocolo'):
        aggressive_plan.assert_current_control(plan)


def test_operational_volume_and_environment_cache_are_protected(tmp_path, monkeypatch):
    with pytest.raises(ResearchGateError):
        aggressive_plan.isolated_directory(Path('/var/lib/trading-lab/experiment'))
    runtime = tmp_path/'runtime'
    runtime.mkdir()
    (runtime/'trading.sqlite3').touch()
    with pytest.raises(ResearchGateError):
        aggressive_plan.isolated_directory(runtime/'experiment')
    monkeypatch.setenv('TRADING_LAB_DATA_DIR', str(tmp_path/'market-cache'))
    with pytest.raises(ResearchGateError):
        aggressive_plan.isolated_directory(tmp_path/'market-cache'/'experiment')
