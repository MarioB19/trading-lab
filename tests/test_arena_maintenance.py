import base64
import gzip
import hashlib
import json
from http.client import HTTPConnection
from pathlib import Path
import threading

import pytest

from lab import arena, arena_hosted, arena_maintenance as maint


def volume(tmp_path):
    mount = tmp_path / 'data'
    for name in ('arena', 'arena-backups', 'arena-imports'):
        (mount / name).mkdir(parents=True)
    maint.prepare_root(mount, 10001, 10001)
    arena.initialize(mount / 'arena', 'synthetic')
    old = mount / 'arena-backups' / 'arena-0000000000001-deadbeef'
    old.mkdir()
    (old / 'snapshot.sqlite3.gz').write_bytes(gzip.compress(b'respaldo anterior'))
    (old / 'manifest.json').write_text('{}')
    return mount


def ready_state(mount):
    state, lock = {'phase': 'starting'}, threading.Lock()
    maint.prepare(mount, state, lock)
    return state, lock


def test_prepare_inventories_backs_up_once_and_never_touches_old_backups(tmp_path):
    mount = volume(tmp_path)
    before = sorted(p.name for p in (mount / 'arena-backups').iterdir())
    old_bytes = (mount / 'arena-backups' / before[0] / 'snapshot.sqlite3.gz').read_bytes()
    state, _ = ready_state(mount)
    assert state['phase'] == 'ready', state.get('error')
    paths_before = {f['path'] for f in state['inventory_before']['files']}
    assert 'arena/arena.sqlite3' in paths_before and not any(p.startswith('arena-final/') for p in paths_before)
    folder = mount / state['backup']['directory']
    assert folder.parent.name == 'arena-final' and (folder / 'manifest.json').is_file()
    data = folder / arena.DB_NAME
    assert hashlib.sha256(data.read_bytes()).hexdigest() == state['backup']['sqlite_sha256']
    assert state['counts']['live'] == state['counts']['backup'] and state['counts']['live']['wallets'] == 4
    assert sorted(p.name for p in (mount / 'arena-backups').iterdir()) == before
    assert (mount / 'arena-backups' / before[0] / 'snapshot.sqlite3.gz').read_bytes() == old_bytes
    after = {f['path'] for f in state['inventory_after']['files']}
    assert f"arena-final/{folder.name}/{arena.DB_NAME}" in after and paths_before <= after
    assert sorted(p.name for p in folder.iterdir()) == [arena.DB_NAME, 'manifest.json']  # sin -wal ni -shm
    again, _ = ready_state(mount)  # un reinicio verifica y reutiliza, no crea otra copia
    assert again['backup']['reused'] and again['backup']['directory'] == f'arena-final/{folder.name}'
    assert len(list((mount / 'arena-final').iterdir())) == 1


def test_partial_final_backup_is_not_retried(tmp_path):
    mount = volume(tmp_path)
    (mount / 'arena-final' / '20261025T000000Z').mkdir()
    state, _ = ready_state(mount)
    assert state['phase'] == 'error' and 'a medias' in state['error']
    assert len(list((mount / 'arena-final').iterdir())) == 1


def test_no_space_blocks_backup_without_writing(tmp_path, monkeypatch):
    mount = volume(tmp_path)
    monkeypatch.setattr(maint.shutil, 'disk_usage', lambda _: type('U', (), {'free': 1, 'total': 2, 'used': 1})())
    state, _ = ready_state(mount)
    assert state['phase'] == 'error' and 'Espacio' in state['error']
    assert not any((mount / 'arena-final').iterdir())


@pytest.fixture
def served(tmp_path):
    mount = volume(tmp_path)
    state, lock = ready_state(mount)
    server = maint.make_server(mount, 0, public_domain='arena.example.com', username='tester',
                               password='test-only', state=state, lock=lock)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield mount, state, server
    server.shutdown(); server.server_close(); thread.join()


def get(server, path, auth=True, host='arena.example.com', method='GET'):
    connection = HTTPConnection('127.0.0.1', server.server_port)
    headers = {'Host': host}
    if auth:
        headers['Authorization'] = 'Basic ' + base64.b64encode(b'tester:test-only').decode()
    connection.request(method, path, headers=headers)
    response = connection.getresponse()
    body, code, head = response.read(), response.status, dict(response.getheaders())
    connection.close()
    return code, body, head


def test_parts_are_authenticated_hashed_and_limited_to_inventory(served):
    mount, state, server = served
    assert get(server, '/healthz', auth=False, host='healthcheck.railway.app')[0] == 200
    assert get(server, '/maintenance/status', auth=False)[0] == 401
    assert get(server, '/maintenance/status', host='attacker.example.com')[0] == 403
    code, body, _ = get(server, '/maintenance/status')
    assert code == 200 and json.loads(body)['phase'] == 'ready'
    rel = f"{state['backup']['directory']}/{arena.DB_NAME}"
    size = state['backup']['sqlite_bytes']
    rebuilt = b''
    for offset in range(0, size, 4096):
        length = min(4096, size - offset)
        code, body, head = get(server, f'/maintenance/part?path={rel}&offset={offset}&length={length}&gzip=1')
        raw = gzip.decompress(body)
        assert code == 200 and hashlib.sha256(raw).hexdigest() == head['X-Part-Sha256']
        rebuilt += raw
    assert hashlib.sha256(rebuilt).hexdigest() == state['backup']['sqlite_sha256']
    assert get(server, '/maintenance/part?path=../etc/passwd&offset=0&length=1')[0] == 404
    assert get(server, f'/maintenance/part?path={rel}&offset={size}&length=1')[0] == 416
    assert get(server, f'/maintenance/part?path={rel}&offset=0&length={maint.MAX_PART + 1}')[0] == 416
    assert get(server, '/maintenance/status', method='POST')[0] == 405


def test_hosted_run_dispatches_to_maintenance_without_worker(monkeypatch):
    calls = []
    monkeypatch.setenv(maint.MODE_ENV, maint.MODE_VALUE)
    monkeypatch.setattr(arena_hosted, 'prepare_volume', lambda mount: None)
    monkeypatch.setattr(arena_hosted.os, 'geteuid', lambda: arena_hosted.UID)
    monkeypatch.setattr(maint, 'prepare_root', lambda mount, uid, gid: calls.append(('root', mount)))
    monkeypatch.setattr(maint, 'serve', lambda mount: calls.append(mount))
    monkeypatch.setattr(arena_hosted.subprocess, 'Popen', lambda *a, **k: pytest.fail('worker iniciado'))
    monkeypatch.setattr(arena_hosted.arena_storage, 'backup_once', lambda *a, **k: pytest.fail('rotación'))
    monkeypatch.setattr(arena_hosted.arena, 'execution_proof', lambda *a: pytest.fail('ruta normal'))
    arena_hosted.run()
    assert calls == [('root', Path('/data')), Path('/data')]


def test_maintenance_requires_exact_image_flag(monkeypatch):
    monkeypatch.delenv(maint.MODE_ENV, raising=False)
    assert not maint.enabled()
    monkeypatch.setenv(maint.MODE_ENV, 'true')
    assert not maint.enabled()
