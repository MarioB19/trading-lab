from contextlib import closing
import fcntl
import json
import pytest
from lab import arena, arena_fees as fees, arena_storage_upgrade as migration
import hashlib

# La migración de almacenamiento se aplicó el 15-oct y su candado congela el código de ese día.
# Desde F3 (25-oct, panel único) cambian hosted.py y service.py del piloto, que no son lógica de
# trading (runtime.py solo agrega los carriles F4 después del ciclo). Estas pruebas siguen verificando la migración con el resto del congelado intacto.
CHANGED_AFTER_FREEZE = ('src/lab/hosted.py', 'src/lab/service.py', 'src/lab/runtime.py')


@pytest.fixture(autouse=True)
def freeze_as_of_f3(monkeypatch):
    frozen = dict(migration.FROZEN_SOURCES)
    for name in CHANGED_AFTER_FREEZE:
        frozen[name] = hashlib.sha256((arena.ROOT / name).read_bytes()).hexdigest()
    monkeypatch.setattr(migration, 'FROZEN_SOURCES', frozen)


def fixture(tmp_path,monkeypatch):
    arena.initialize(tmp_path)
    with closing(arena.connect(tmp_path)) as db,db:
        m=json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        m['proof']={'code_commit':migration.SOURCE_COMMIT,'commit':migration.PREREG}
        m['fee_policy']={'proof':{'code_commit':migration.SOURCE_COMMIT,'commit':fees.PREREG},'model_id':fees.plan()['model_id'],'scope':'per_strategy','schedule_sha256':arena.canonical_hash(fees.plan()),'after_fill_id':0,'activated_ms':0,
            'opening_wallets':{wid:json.loads(raw) for wid,raw in db.execute('SELECT id,payload FROM wallets')}}
        db.execute("UPDATE meta SET value=? WHERE key='manifest'",(arena._json(m),))
        db.execute('INSERT INTO events(ts,payload) VALUES (?,?)',(1,'{"action":"historical-event"}'))
        for wid,raw in db.execute('SELECT id,payload FROM wallets').fetchall():
            w=json.loads(raw);w['quotes']=[{'artificial_pending_quote':True}]
            db.execute('UPDATE wallets SET payload=? WHERE id=?',(arena._json(w),wid))
    monkeypatch.setattr(arena,'execution_proof',lambda commit:{'code_commit':'f'*40,'commit':commit})
    monkeypatch.setattr(fees,'proof',lambda:{'code_commit':'f'*40,'commit':fees.PREREG})
    return arena.status(tmp_path)


def test_storage_upgrade_preserves_all_history_financial_state_and_start_date(tmp_path,monkeypatch):
    before=fixture(tmp_path,monkeypatch)
    result=migration.upgrade(tmp_path,cutover_confirmed=True)
    assert result['status']=='upgraded' and result['trading_sources_unchanged']==50
    after=arena.status(tmp_path)
    for key in ['fills','history','counts','capital_usd','last_observed_ms']:assert after[key]==before[key]
    for a,b in zip(before['wallets'],after['wallets']):
        assert {k:v for k,v in a.items() if k!='quotes'}=={k:v for k,v in b.items() if k!='quotes'}
        assert b['quotes']==[]
    old=json.loads(json.dumps(before['manifest']));new=json.loads(json.dumps(after['manifest']))
    for key in ['proof','storage_recovery']:old.pop(key,None);new.pop(key,None)
    old['fee_policy'].pop('proof');new['fee_policy'].pop('proof');assert old==new
    assert after['events'][0]['rule_change'] is False and after['events'][0]['history_removed'] is False
    assert after['events'][1]==before['events'][0]
    assert not (tmp_path/'arena.enabled').exists()
    assert migration.upgrade(tmp_path,cutover_confirmed=True)['status']=='already_upgraded'
    assert arena.status(tmp_path)==after


def test_storage_upgrade_needs_stopped_writer_and_confirmed_cut(tmp_path,monkeypatch):
    fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError):migration.upgrade(tmp_path)
    (tmp_path/'arena.enabled').write_text('paper')
    with pytest.raises(ValueError):migration.upgrade(tmp_path,cutover_confirmed=True)
    (tmp_path/'arena.enabled').unlink()
    with (tmp_path/'arena-worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):migration.upgrade(tmp_path,cutover_confirmed=True)


@pytest.mark.parametrize('change',['source','mode','plan','fee_schedule'])
def test_storage_upgrade_rejects_different_rules_and_source(tmp_path,monkeypatch,change):
    fixture(tmp_path,monkeypatch)
    with closing(arena.connect(tmp_path)) as db,db:
        m=json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        if change=='source':m['proof']['code_commit']='a'*40
        elif change=='mode':m['mode']='unexpected'
        elif change=='plan':m['plan']['variants'][0]['stop_loss']=0.5
        else:m['fee_policy']['schedule_sha256']='0'*64
        db.execute("UPDATE meta SET value=? WHERE key='manifest'",(arena._json(m),))
    with pytest.raises(ValueError):migration.upgrade(tmp_path,cutover_confirmed=True)
    assert arena.status(tmp_path)['events'][0]['action']=='historical-event'


def test_frozen_engine_guard_detects_a_changed_trading_file(tmp_path,monkeypatch):
    monkeypatch.setattr(arena,'ROOT',tmp_path)
    path=tmp_path/'src/lab/arena.py';path.parent.mkdir(parents=True);path.write_text('changed')
    monkeypatch.setattr(migration,'FROZEN_SOURCES',{'src/lab/arena.py':'0'*64})
    with pytest.raises(ValueError,match='congelado'):migration.verify_frozen_engine()


def test_storage_upgrade_rejects_unreconciled_wallet_without_changing_identity(tmp_path,monkeypatch):
    before=fixture(tmp_path,monkeypatch)
    with closing(arena.connect(tmp_path)) as db,db:
        wid,raw=db.execute('SELECT id,payload FROM wallets LIMIT 1').fetchone();w=json.loads(raw);w['cash']+=1
        db.execute('UPDATE wallets SET payload=? WHERE id=?',(arena._json(w),wid))
    with pytest.raises(ValueError,match='concilia'):migration.upgrade(tmp_path,cutover_confirmed=True)
    assert arena.status(tmp_path)['manifest']==before['manifest']
