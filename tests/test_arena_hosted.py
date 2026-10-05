import base64
import copy
import json
from http.client import HTTPConnection
from pathlib import Path
import threading

import pytest
from lab import arena, arena_hosted
from lab.arena_service import make_server


@pytest.fixture
def cloud(tmp_path):
    arena.initialize(tmp_path)
    server = make_server(tmp_path, 0, public_domain='arena.example.com', username='tester', password='test-only')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield tmp_path, server
    server.shutdown(); server.server_close(); thread.join()


def request(server, path, method='GET', auth=False, origin=None, host='arena.example.com', payload=None):
    connection = HTTPConnection('127.0.0.1', server.server_port)
    headers = {'Host': host}
    if auth: headers['Authorization'] = 'Basic ' + base64.b64encode(b'tester:test-only').decode()
    if origin: headers['Origin'] = origin
    if payload is not None: headers['Content-Type'] = 'application/json'
    connection.request(method, path, json.dumps(payload) if payload else None, headers)
    response = connection.getresponse(); raw = response.read(); code = response.status
    connection.close()
    return code, raw


def test_hosted_requires_credentials_before_binding(tmp_path):
    with pytest.raises(ValueError): make_server(tmp_path, 0, public_domain='arena.example.com')
    assert not (tmp_path / arena.DB_NAME).exists()


def test_cloud_auth_protects_data_assets_and_readiness(cloud):
    directory, server = cloud
    for path in ['/', '/arena.js', '/arena.css', '/api/arena', '/api/export', '/readyz', '/api/daily-audit', '/api/daily-audit.csv', '/api/integrity']:
        assert request(server, path)[0] == 401
    assert request(server, '/api/arena', auth=True)[0] == 200
    assert request(server, '/readyz', auth=True)[0] == 503
    assert request(server, '/healthz', host='healthcheck.railway.app')[0] == 200
    assert request(server, '/api/arena', auth=True, host='attacker.example.com')[0] == 403


def test_hosted_controls_require_auth_and_exact_https_origin(cloud):
    directory, server = cloud
    payload = {'strategy': 'scalping-v1', 'action': 'pause'}
    for origin in [None, 'https://attacker.example.com', 'http://arena.example.com']:
        assert request(server, '/api/control', 'POST', True, origin, payload=payload)[0] == 403
    assert request(server, '/api/control', 'POST', False, 'https://arena.example.com', payload=payload)[0] == 401
    assert not arena.status(directory)['wallets'][0]['paused']
    assert request(server, '/api/control', 'POST', True, 'https://arena.example.com', payload=payload)[0] == 200
    assert arena.status(directory)['wallets'][0]['paused']
    assert all(not w['paused'] for w in arena.status(directory)['wallets'][1:])


def test_hosted_server_never_seeds_an_empty_cloud_database(tmp_path):
    server = make_server(tmp_path, 0, public_domain='arena.example.com', username='tester', password='test-only')
    server.server_close()
    assert not (tmp_path / arena.DB_NAME).exists()


def migration_fixture(tmp_path, monkeypatch):
    arena.initialize(tmp_path)
    old = {'code_commit': arena_hosted.LOCAL_SOURCE, 'commit': arena_hosted.PREREG}
    new = {**old, 'code_commit': '1' * 40, 'proof_kind': 'git-content-ancestry-v1'}
    with arena.connect(tmp_path) as db:
        manifest = json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        manifest['proof'] = old
        db.execute("UPDATE meta SET value=? WHERE key='manifest'", (arena._json(manifest),))
    monkeypatch.setattr(arena, 'execution_proof', lambda _: new)
    return old, new


def test_migration_preserves_balances_history_and_records_old_proof(tmp_path, monkeypatch):
    old, new = migration_fixture(tmp_path, monkeypatch)
    before = arena.status(tmp_path)
    with pytest.raises(ValueError, match='corte'): arena_hosted.migrate(tmp_path)
    assert arena_hosted.migrate(tmp_path, cutover_confirmed=True)['status'] == 'migrated'
    after = arena.status(tmp_path)
    for key in ['wallets', 'fills', 'decisions', 'counts', 'history', 'capital_usd']:
        assert after[key] == before[key]
    assert after['manifest']['proof'] == new
    assert after['events'][0]['previous_proof'] == old
    assert arena_hosted.migrate(tmp_path, cutover_confirmed=True)['status'] == 'already_migrated'
    assert len(arena.status(tmp_path)['events']) == 1
    assert not (tmp_path / 'arena.enabled').exists()
    with pytest.raises(ValueError): arena_hosted.activate(tmp_path)
    arena_hosted.activate(tmp_path, cutover_confirmed=True)
    assert (tmp_path / 'arena.enabled').is_file()


def test_migration_rejects_running_writer_and_unrelated_source(tmp_path, monkeypatch):
    import fcntl
    migration_fixture(tmp_path, monkeypatch)
    with (tmp_path / 'arena-worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError): arena_hosted.migrate(tmp_path, cutover_confirmed=True)
    with arena.connect(tmp_path) as db:
        manifest = json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        manifest['proof']['code_commit'] = '2' * 40
        db.execute("UPDATE meta SET value=? WHERE key='manifest'", (arena._json(manifest),))
    with pytest.raises(ValueError, match='Origen'): arena_hosted.migrate(tmp_path, cutover_confirmed=True)


def test_hosted_requires_a_real_volume(tmp_path):
    with pytest.raises(ValueError, match='Volumen'): arena_hosted.prepare_volume(tmp_path)


def test_image_proof_path_rejects_invalid_attestation(tmp_path, monkeypatch):
    bad = tmp_path / 'attestation.json'; bad.write_text('{}')
    monkeypatch.setenv('ARENA_ATTESTATION', str(bad))
    monkeypatch.setenv('TRADING_LAB_BUILD_ID', 'a' * 40)
    with pytest.raises(ValueError): arena.execution_proof(arena_hosted.PREREG)


def test_authenticated_daily_report_and_integrity_are_read_only(cloud):
    directory, server = cloud
    before = arena.status(directory)
    assert request(server, '/api/daily-audit', auth=True)[0] == 200
    code, raw = request(server, '/api/daily-audit.csv', auth=True)
    assert code == 200 and 'fecha_cdmx' in raw.decode('utf-8-sig')
    code, raw = request(server, '/api/integrity', auth=True)
    assert code == 200 and json.loads(raw)['status'] == 'verified'
    assert arena.status(directory)['wallets'] == before['wallets']
    assert arena.status(directory)['counts'] == before['counts']
