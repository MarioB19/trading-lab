import hashlib
import json

import pytest

from lab.service import comparison_status


def test_comparison_read_does_not_create_state(tmp_path):
    paper = tmp_path / 'paper'
    result = comparison_status(paper, None)
    assert result['paper']['status'] == 'not_started'
    assert result['research']['status'] == 'not_configured'
    assert not paper.exists()


def test_report_integrity_verified_before_display(tmp_path):
    report = {'experiment_id': 'aggressive-v2', 'run_id': 'synthetic-test',
              'mode': 'paper', 'live_authorized': False, 'checks': {'test': False}}
    raw = json.dumps(report).encode()
    target = tmp_path / 'comparison.json'
    target.write_bytes(raw)
    (tmp_path / 'manifest.json').write_text(json.dumps({
        'status': 'completed', 'experiment_id': 'aggressive-v2', 'run_id': 'synthetic-test',
        'artifacts': [{'file': 'comparison.json', 'sha256': hashlib.sha256(raw).hexdigest()}]}))
    assert comparison_status(None, tmp_path)['research']['report'] == report
    report['checks']['test'] = True
    target.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='integridad'):
        comparison_status(None, tmp_path)


def test_failed_run_is_not_presented_as_completed(tmp_path):
    (tmp_path / 'manifest.json').write_text('{"status":"failed","run_id":"sample"}')
    assert comparison_status(None, tmp_path)['research'] == {'status': 'failed', 'run_id': 'sample'}
