import copy

import pytest
import yaml

from lab import backlog


@pytest.fixture
def data():
    return backlog.load()


def test_real_backlog_loads_with_unique_ids(data):
    ids = [h['id'] for h in data['hipotesis']] + [d['id'] for d in data['descartadas'] if d.get('id')]
    assert len(ids) == len(set(ids))
    assert backlog.main(['check']) == 0


def test_render_is_deterministic_and_keeps_every_row(data):
    note = backlog.render_note(data)
    assert note == backlog.render_note(copy.deepcopy(data))
    assert backlog.AVISO in note and backlog.INDICE in note
    for h in data['hipotesis']:
        assert f"| {h['id']} | {backlog.TIPOS[h['tipo']]} |" in note
        assert backlog._cell(h['estado']) in note
    for d in data['descartadas']:
        assert backlog._cell(d['motivo']) in note
    for r in data['bitacora']:
        assert f"| {r['fecha']} | Sprint {r['sprint']}: {backlog._cell(r['hipotesis'])} |" in note
        assert backlog._cell(r['decision']) in note


def test_duplicate_id_and_empty_state_fail(data, tmp_path):
    bad = copy.deepcopy(data)
    bad['hipotesis'].append({**bad['hipotesis'][0], 'orden': 99})
    with pytest.raises(backlog.BacklogError, match='duplicado'):
        backlog.validate(bad)
    bad = copy.deepcopy(data)
    bad['hipotesis'][0]['estado'] = ' '
    path = tmp_path / 'backlog.yaml'
    path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding='utf-8')
    with pytest.raises(backlog.BacklogError):
        backlog.load(path)
    assert backlog.main(['check', '--file', str(path)]) == 1


def test_summary_next_skips_paused(data):
    s = backlog.summary(data)
    assert s['siguiente']['id'] == min((h for h in data['hipotesis'] if not h.get('pausada')),
                                       key=lambda h: h['orden'])['id']
    paused = copy.deepcopy(data)
    for h in paused['hipotesis']:
        h['pausada'] = True
    assert backlog.summary(paused)['siguiente'] is None
    assert [h['orden'] for h in s['hipotesis']] == sorted(h['orden'] for h in s['hipotesis'])
