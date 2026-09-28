"""Registered data correction and source chain, using synthetic prices only."""
import hashlib
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from lab import aggressive_plan as plans, aggressive_research as research
from lab.experiments import ResearchGateError, canonical_hash


def v2():
    return plans.comparison_plan(plans.ROOT / 'configs/experiments/aggressive_v2.yaml')[0]


def test_v2_changes_only_declared_data_availability():
    plan = v2()
    assert plans.preregistration_path(plan).name == 'aggressive_v2_preregistro.md'
    plan.pop('source_snapshot')
    plan.pop('availability_policy')
    plan['experiment_id'] = 'aggressive-v1'
    assert canonical_hash(plan) == plans.PLAN_V1_HASH


@pytest.mark.parametrize('change', ['cost', 'window', 'criteria', 'capital', 'source', 'policy'])
def test_v2_rejects_unregistered_changes(change):
    plan = v2()
    if change == 'cost':
        plan['costs']['crypto']['base'] = .003
    elif change == 'window':
        plan['evaluation']['start'] = '2022-01-01'
    elif change == 'criteria':
        plan['criteria']['bootstrap_n'] = 3
    elif change == 'capital':
        plan['initial_capital_usd'] = 2000
    elif change == 'source':
        plan['source_snapshot']['crypto']['path'] = 'data/cache.csv'
    else:
        plan['availability_policy']['available_from'] = '2021-01-01'
    with pytest.raises(ResearchGateError):
        plans.validate_plan(plan)


def synthetic_source(tmp_path, monkeypatch):
    plan = v2()
    directory = tmp_path / 'run'
    directory.mkdir()
    events = []
    context = SimpleNamespace(directory=directory, manifest={}, _save_manifest=lambda: None,
                              event=lambda name, **data: events.append((name, data)))
    dates = pd.date_range('2020-07-13', '2021-07-01')
    crypto = pd.DataFrame({'AVAX': 10., 'BTC': 100.}, index=dates)
    crypto.loc['2020-07-15':'2020-09-21', 'AVAX'] = float('nan')
    stocks = pd.DataFrame({'SPY': 100., 'IEF': 50.}, index=dates)
    source = plan['source_snapshot']
    for name, frame in [('crypto', crypto), ('stocks', stocks)]:
        path = tmp_path / source[name]['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index_label='date')
        source[name]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    parent = {'run_id': source['run_id'], 'experiment_id': 'aggressive-v1', 'status': 'failed',
              'variants': [{'status': 'declared'}, {'status': 'declared'}],
              'artifacts': [{'file': f'inputs/{name}_prices.csv', 'sha256': source[name]['sha256']}
                            for name in ('crypto', 'stocks')]}
    parent_path = tmp_path / source['manifest']['path']
    parent_path.write_text(json.dumps(parent))
    source['manifest']['sha256'] = hashlib.sha256(parent_path.read_bytes()).hexdigest()
    evidence = tmp_path / 'evidence.json'
    evidence.write_text('{"synthetic_evidence":true}')
    plan['availability_policy']['evidence_sha256'] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    monkeypatch.setattr(research, 'ROOT', tmp_path)
    monkeypatch.setattr(research, 'AVAILABILITY_EVIDENCE', evidence)
    monkeypatch.setattr(research, 'load_sleeve', lambda *a, **k: pytest.fail('v2 must not download'))
    return plan, context, crypto, events, evidence


def test_load_uses_pinned_bytes_and_recomputes_eligibility(tmp_path, monkeypatch):
    plan, context, original, events, _ = synthetic_source(tmp_path, monkeypatch)
    derived, eligible, stocks, audit = research.load_registered_panels(plan, context)
    assert audit['quarantined_count'] == 2 and not audit['raw_mutated']
    assert derived.loc[:'2020-09-21', 'AVAX'].isna().all()
    pd.testing.assert_series_equal(original['BTC'], derived['BTC'], check_names=False, check_freq=False)
    assert not eligible.loc['2021-05-28', 'AVAX']
    assert eligible.loc['2021-05-29', 'AVAX']
    assert events[0][0] == 'availability_policy_applied'
    assert context.manifest['source_snapshot'] == plan['source_snapshot']
    raw = context.directory / 'source_inputs/raw_crypto_prices.csv'
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == plan['source_snapshot']['crypto']['sha256']
    assert original.loc['2020-07-13', 'AVAX'] == 10
    provenance = research.availability(derived, 'crypto', plan)
    assert provenance['availability_policy'] == plan['availability_policy']
    assert provenance['source_run_id'] == plan['source_snapshot']['run_id']


@pytest.mark.parametrize('tamper', ['crypto', 'evidence', 'manifest', 'lineage'])
def test_source_or_evidence_tampering_stops_before_transformation(tmp_path, monkeypatch, tamper):
    plan, context, _, _, evidence = synthetic_source(tmp_path, monkeypatch)
    if tamper == 'evidence':
        evidence.write_text('changed')
    elif tamper == 'lineage':
        item = plan['source_snapshot']['manifest']
        path = tmp_path / item['path']
        parent = json.loads(path.read_bytes())
        parent['variants'][0]['status'] = 'evaluated'
        path.write_text(json.dumps(parent))
        item['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        (tmp_path / plan['source_snapshot'][tamper]['path']).write_text('changed')
    with pytest.raises(ResearchGateError):
        research.load_registered_panels(plan, context)
    assert not (context.directory / 'data_quality_audit.json').exists()
