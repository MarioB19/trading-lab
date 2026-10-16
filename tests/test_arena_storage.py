from contextlib import closing
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest
from lab import arena, arena_storage as storage


def setup(tmp_path):
    source=tmp_path/'arena';arena.initialize(source)
    backups=tmp_path/'backups';backups.mkdir()
    return source,backups


def test_backup_is_consistent_compressed_atomic_and_restorable(tmp_path):
    source,backups=setup(tmp_path);before=arena.status(source)
    result=storage.backup_once(source,backups,now=1234567890)
    folder=Path(result['directory']);copy=tmp_path/'restored.sqlite3'
    with gzip.open(folder/'snapshot.sqlite3.gz','rb') as reader:copy.write_bytes(reader.read())
    assert hashlib.sha256(copy.read_bytes()).hexdigest()==result['sqlite_sha256']
    restored=arena.restore(copy,tmp_path/'restored')
    assert restored['wallets']==before['wallets'] and restored['manifest']==before['manifest']
    assert not list(backups.glob('*.sqlite3')) and not list(backups.glob('*.part'))
    assert storage.latest_backup_time(backups)==1234567890
    assert arena.status(source)==before


def test_retention_keeps_two_valid_copies_and_persists_across_restarts(tmp_path):
    source,backups=setup(tmp_path)
    for t in (1234567890,1234567891,1234567892):storage.backup_once(source,backups,now=t)
    assert [m['created_ms'] for _,m in storage.snapshots(backups)]==[1234567891000,1234567892000]
    assert storage.latest_backup_time(backups)==1234567892


def test_failed_copy_removes_partial_and_keeps_last_verified_snapshot(tmp_path,monkeypatch):
    source,backups=setup(tmp_path);good=storage.backup_once(source,backups,now=1234567890)
    def fail(*a,**k):raise OSError('artificial write failure')
    monkeypatch.setattr(storage.gzip,'GzipFile',fail)
    with pytest.raises(OSError):storage.backup_once(source,backups,now=1234567891)
    assert [m['sqlite_sha256'] for _,m in storage.snapshots(backups)]==[good['sqlite_sha256']]
    assert not list(backups.glob('*.part'))


def test_compressed_size_is_hard_bounded_and_cannot_fill_reserve(tmp_path,monkeypatch):
    source,backups=setup(tmp_path)
    with arena.connect(source) as db:db.execute('INSERT INTO meta VALUES (?,?)',('entropy',os.urandom(200000).hex()))
    monkeypatch.setattr(storage,'limits',lambda p:{'free_bytes':2000000,'total_bytes':5000000,'reserve_bytes':1000000,'backup_budget_bytes':128*1024})
    with pytest.raises(storage.StoragePressure):storage.backup_once(source,backups)
    assert not storage.snapshots(backups) and not list(backups.glob('*.part'))


def test_low_space_rejects_backup_before_copy_and_blocks_worker(tmp_path,monkeypatch):
    source,backups=setup(tmp_path)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda p:SimpleNamespace(total=5000*storage.MIB,free=100*storage.MIB))
    assert not storage.worker_space_available(source)
    with pytest.raises(storage.StoragePressure):storage.backup_once(source,backups)
    assert not storage.snapshots(backups)


def test_volume_policy_allows_two_growing_copies_and_keeps_twenty_percent_free(tmp_path,monkeypatch):
    total=4838498304
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda p:SimpleNamespace(total=total,free=4000000000))
    policy=storage.limits(tmp_path)
    assert policy['backup_budget_bytes']==total//5 and policy['reserve_bytes']==total//5
    assert policy['backup_budget_bytes']>=2*400000000


def test_corrupt_published_backup_is_not_counted_or_deleted(tmp_path):
    source,backups=setup(tmp_path);r=storage.backup_once(source,backups)
    p=Path(r['directory'])/'snapshot.sqlite3.gz';p.write_bytes(b'corrupt')
    with pytest.raises(ValueError):storage.latest_backup_time(backups)
    with pytest.raises(ValueError):storage.backup_once(source,backups)
    assert p.read_bytes()==b'corrupt'


def test_symlinks_and_foreign_partial_directories_are_never_deleted(tmp_path):
    source,backups=setup(tmp_path);protected=tmp_path/'protected';protected.write_text('keep')
    folder=backups/'.arena-backup-foreign.part';folder.mkdir()
    (folder/'work.json').write_text(json.dumps({'kind':storage.KIND}))
    (folder/'snapshot.sqlite3.gz').symlink_to(protected)
    with pytest.raises(ValueError):storage.backup_once(source,backups)
    assert protected.read_text()=='keep' and folder.exists()


def test_abandoned_owned_partial_is_cleaned_but_legacy_backup_is_preserved(tmp_path):
    source,backups=setup(tmp_path);old=backups/'arena-100.sqlite3';old.write_bytes(b'legacy-preserved')
    folder=backups/'.arena-backup-old.part';folder.mkdir()
    (folder/'work.json').write_text(json.dumps({'kind':storage.KIND}));(folder/'snapshot.sqlite3.gz').write_bytes(b'partial')
    storage.backup_once(source,backups)
    assert not folder.exists() and old.read_bytes()==b'legacy-preserved'


def test_backup_lock_prevents_parallel_rotation(tmp_path):
    source,backups=setup(tmp_path)
    with (backups/'.backup.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):storage.backup_once(source,backups)
    assert not storage.snapshots(backups)


@pytest.mark.parametrize('low_space',[False,True])
def test_supervisor_survives_sqlite_backup_failure_and_enforces_disk_guard(tmp_path,monkeypatch,low_space,capsys):
    from lab import arena_hosted as hosted
    directory=Path('/data/arena')
    # Map only supervisor's fixed volume paths into an artificial test volume.
    real_path=hosted.Path
    def mapped(value):
        return tmp_path/str(value).removeprefix('/data/') if str(value).startswith('/data/') else real_path(value)
    monkeypatch.setattr(hosted,'Path',mapped)
    source=tmp_path/'arena';source.mkdir();(source/arena.DB_NAME).write_bytes(b'artificial')
    (source/'arena.enabled').write_text('paper')
    (tmp_path/'arena-backups').mkdir()
    monkeypatch.setattr(hosted,'prepare_volume',lambda p:None)
    monkeypatch.setattr(hosted.os,'geteuid',lambda:10001)
    monkeypatch.setenv('ARENA_WORKER_ALLOWED','true')
    monkeypatch.setattr(hosted.arena,'execution_proof',lambda _: {'proof':'same'})
    monkeypatch.setattr(hosted.arena,'status',lambda _: {'manifest':{'proof':{'proof':'same'}}})
    monkeypatch.setattr(hosted,'make_server',lambda *a,**k:SimpleNamespace(serve_forever=lambda:None,shutdown=lambda:None,server_close=lambda:None))
    monkeypatch.setattr(hosted.signal,'signal',lambda *a:None)
    class Event:
        n=0
        def wait(self,_):self.n+=1;return self.n>3
        def set(self):pass
    monkeypatch.setattr(hosted.threading,'Event',Event)
    monkeypatch.setattr(hosted.threading,'Thread',lambda *a,**k:SimpleNamespace(start=lambda:None,is_alive=lambda:True))
    calls={'backup':0,'started':0,'terminated':0,'space':0}
    class Worker:
        pid=123
        stopped=False
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True;calls['terminated']+=1
        def wait(self,**kw):return 0
    def spawn(*a,**kw):calls['started']+=1;return Worker()
    monkeypatch.setattr(hosted.subprocess,'Popen',spawn)
    monkeypatch.setattr(storage,'latest_backup_time',lambda p:0)
    def space(p):calls['space']+=1;return not low_space or calls['space']==1
    monkeypatch.setattr(storage,'worker_space_available',space)
    def backup(*a):calls['backup']+=1;raise sqlite3.OperationalError('artificial full')
    monkeypatch.setattr(storage,'backup_once',backup)
    hosted.run()
    assert calls['backup']==1 and calls['started']==1 and calls['terminated']==1
    output=capsys.readouterr().out
    assert 'OperationalError' in output and '3600' in output
    if low_space:assert '"storage_blocked": true' in output
