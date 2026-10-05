from contextlib import closing
import copy
import fcntl
import json

import pytest
from lab import arena, arena_fees as fees
from lab.arena_fees_upgrade import upgrade, SOURCE_COMMIT
from lab.arena_hosted import PREREG
from test_arena import frame, TS
from test_arena_hosted import cloud, request


def policy(directory, ts=TS-1):
    cfg=fees.plan()
    with closing(arena.connect(directory)) as db,db:
        manifest=json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
        value={'model_id':cfg['model_id'],'schedule_sha256':arena.canonical_hash(cfg),'scope':cfg['scope'],
               'activated_ms':ts,'after_fill_id':db.execute('SELECT COALESCE(MAX(id),0) FROM fills').fetchone()[0], 'proof':{}}
        manifest['fee_policy']=value
        db.execute("UPDATE meta SET value=? WHERE key='manifest'",(arena._json(manifest),))
    return value


@pytest.mark.parametrize('threshold,maker,taker',[(r['above_usd'],r['maker'],r['taker']) for r in fees.plan()['tiers'][1:]])
def test_strict_tier_boundaries(threshold,maker,taker):
    assert fees.tier(threshold)['taker']>taker
    assert fees.tier(threshold+.000001)=={'above_usd':threshold,'maker':maker,'taker':taker}


@pytest.mark.parametrize('value',[-1,float('nan'),float('inf')])
def test_invalid_volume_rejected(value):
    with pytest.raises(ValueError):fees.tier(value)


def row(fid, ts, amount, wid='scalping-v1'):
    return (fid,{'ts':ts,'strategy':wid,'value':amount},None)


def test_rolling_volume_expiry_future_independence_and_current_fill_exclusion():
    rows=[row(1,TS-fees.WINDOW_MS,900),row(2,TS-1,1000),row(3,TS+1,8000),row(4,TS,9000,'swing-v1')]
    ctx=fees.context_from_rows(rows,'scalping-v1',TS,'taker')
    assert ctx['volume_30d_usd']==1000 and ctx['rate']==.0036
    ctx=fees.context_from_rows(rows+[row(5,TS,1)],'scalping-v1',TS,'taker')
    assert ctx['volume_30d_usd']==1001 and ctx['rate']==.00333
    assert fees.context_from_rows(rows,'scalping-v1',TS+fees.WINDOW_MS+2,'taker')['rate']==.0036


def test_new_funded_fills_use_tier_metadata_restart_and_duplicate_guard(tmp_path):
    arena.initialize(tmp_path,'synthetic')
    with closing(arena.connect(tmp_path)) as db,db:
        w=json.loads(db.execute("SELECT payload FROM wallets WHERE id='scalping-v1'").fetchone()[0])
        # Financed turnover above US$1,000, without counting the other portfolios.
        for _ in range(3):
            arena._fill(db,w,'buy',2,100,.0036,TS-10,'taker','fixture','fixture')
            arena._fill(db,w,'sell',2,100,.0036,TS-9,'taker','fixture','fixture')
        db.execute('UPDATE wallets SET payload=? WHERE id=?',(arena._json(w),w['id']))
    p=policy(tmp_path)
    with closing(arena.connect(tmp_path)) as db,db:
        w=json.loads(db.execute("SELECT payload FROM wallets WHERE id='scalping-v1'").fetchone()[0])
        f=arena.taker(db,w,'buy',999,frame(),arena.plan(),'test','fixture')
        assert f['fee_context']['rate']==.00333
        assert f['fee_context']['volume_30d_usd']==1200
        assert f['fee']==pytest.approx(f['value']*.00333)
        assert 0<=w['cash']<.00001
        db.execute('UPDATE wallets SET payload=? WHERE id=?',(arena._json(w),w['id']))
    arena.initialize(tmp_path,'synthetic')
    arena.tick(tmp_path,frame(TS+15000))
    before=arena.status(tmp_path)
    assert arena.tick(tmp_path,frame(TS+15000))['status']=='duplicate'
    assert arena.status(tmp_path)['wallets']==before['wallets']
    assert arena.audit(tmp_path)['status']=='verified'
    result=fees.report(tmp_path,at_ms=TS+16000)
    assert result['strategies'][0]['fee_difference_usd']>0
    assert result['strategies'][1]['tier']['taker']==.0036
    assert result['totals']['historical_fees_usd']==pytest.approx(4.32)
    assert result['totals']['new_fees_usd']+result['totals']['historical_fees_usd']==pytest.approx(sum(w['fees'] for w in before['wallets']))


def test_maker_keeps_queue_rules_and_uses_recognition_time(tmp_path):
    arena.initialize(tmp_path,'synthetic');arena.tick(tmp_path,frame());policy(tmp_path,TS+1)
    state=arena.status(tmp_path);w=next(w for w in state['wallets'] if w['id']=='market-making-v1')
    bid=next(q for q in w['quotes'] if q['side']=='buy')
    follow=frame(TS+15000);follow['trades']=[{'tid':2,'ts':TS+2000,'price':bid['price']-.1,'qty':1.,'side':'buy'}]
    arena.tick(tmp_path,follow)
    f=arena.status(tmp_path)['fills'][0]
    assert f['liquidity']=='maker' and f['ts']==TS+2000
    assert f['fee_context']['as_of_ms']==TS+15000 and f['fee_context']['rate']==.003
    assert arena.audit(tmp_path)['status']=='verified'
    assert arena.tick(tmp_path,follow)['status']=='duplicate'


def test_fee_audit_detects_rate_or_prior_volume_tampering(tmp_path):
    arena.initialize(tmp_path,'synthetic');policy(tmp_path);arena.tick(tmp_path,frame())
    with closing(arena.connect(tmp_path)) as db,db:
        fid,raw=db.execute('SELECT id,payload FROM fills LIMIT 1').fetchone();f=json.loads(raw)
        f['fee_context']['volume_30d_usd']+=1
        db.execute('UPDATE fills SET payload=? WHERE id=?',(arena._json(f),fid))
    with pytest.raises(ValueError,match='Comisión'):arena.audit(tmp_path)
    with pytest.raises(ValueError,match='Comisión'):fees.report(tmp_path)


def migration_setup(tmp_path,monkeypatch):
    arena.initialize(tmp_path,'synthetic');arena.tick(tmp_path,frame())
    old={'code_commit':SOURCE_COMMIT,'commit':PREREG};new={**old,'code_commit':'a'*40}
    with closing(arena.connect(tmp_path)) as db,db:
        m=json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0]);m.update(kind='paper',proof=old)
        db.execute("UPDATE meta SET value=? WHERE key='manifest'",(arena._json(m),))
    monkeypatch.setattr(arena,'execution_proof',lambda _:new)
    monkeypatch.setattr(fees,'proof',lambda :{'code_commit':'a'*40,'commit':fees.PREREG})
    monkeypatch.setattr(arena,'now_ms',lambda:TS+15000)
    return old,new


def test_migration_is_idempotent_stopped_only_and_preserves_all_historical_rows(tmp_path,monkeypatch):
    old,new=migration_setup(tmp_path,monkeypatch)
    def history():
        with closing(arena.connect(tmp_path)) as db:
            return {t:db.execute(f'SELECT * FROM {t}').fetchall() for t in ('fills','captures','inputs','equity','decisions')}
    before=arena.status(tmp_path);hist=history()
    with pytest.raises(ValueError):upgrade(tmp_path)
    (tmp_path/'arena.enabled').write_text('on')
    with pytest.raises(ValueError):upgrade(tmp_path,cutover_confirmed=True)
    (tmp_path/'arena.enabled').unlink()
    with (tmp_path/'arena-worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):upgrade(tmp_path,cutover_confirmed=True)
    assert upgrade(tmp_path,cutover_confirmed=True)['status']=='upgraded'
    after=arena.status(tmp_path)
    assert history()==hist
    for a,b in zip(before['wallets'],after['wallets']):
        assert {k:v for k,v in a.items() if k!='quotes'}=={k:v for k,v in b.items() if k!='quotes'}
        assert b['quotes']==[]
    assert before['manifest']['started_at']==after['manifest']['started_at']
    assert after['events'][0]['previous_proof']==old
    assert upgrade(tmp_path,cutover_confirmed=True)['status']=='already_upgraded'
    assert len(arena.status(tmp_path)['events'])==len(after['events'])
    r=fees.report(tmp_path,at_ms=TS+16000)
    assert r['totals']['new_fills']==0 and r['totals']['fee_difference_usd']==0
    assert r['totals']['recorded_fees_usd']>0
    backup=tmp_path/'copy.sqlite3';arena.backup(tmp_path,backup)
    restored=arena.restore(backup,tmp_path/'restored')
    assert restored['manifest']['fee_policy']==after['manifest']['fee_policy']
    assert not (tmp_path/'restored/arena.enabled').exists()
    assert fees.report(tmp_path/'restored',at_ms=TS+16000)==r


def test_fee_endpoints_require_auth_and_are_read_only(cloud):
    directory,server=cloud
    before=arena.status(directory)
    for path in ['/api/fees','/api/fees.csv']:
        assert request(server,path)[0]==401
        code,raw=request(server,path,auth=True)
        assert code==200
        if path.endswith('csv'):assert 'costo_todo_maker_hipotetico_usd' in raw.decode('utf-8-sig')
        else:assert not json.loads(raw)['account_fees_verified']
    assert arena.status(directory)==before


def test_rate_returns_to_base_when_previous_volume_expires_in_fee_audit():
    p={'model_id':fees.plan()['model_id'],'schedule_sha256':arena.canonical_hash(fees.plan()),'activated_ms':TS,'after_fill_id':1}
    rows=[row(1,TS-10,1200)]
    for fid,ts,expected in [(2,TS,.00333),(3,TS+fees.WINDOW_MS+1,.0036)]:
        ctx=fees.context_from_rows(rows,'scalping-v1',ts,'taker')
        assert ctx['rate']==expected
        rows.append((fid,{'strategy':'scalping-v1','ts':ts,'value':100,'fee':100*expected,'fee_context':ctx,'liquidity':'taker'},None))
    fees.verify_ledger(rows,p)


def test_paper_tick_rejects_wrong_fee_proof_before_new_capture(tmp_path,monkeypatch):
    _,new=migration_setup(tmp_path,monkeypatch)
    upgrade(tmp_path,cutover_confirmed=True)
    before=arena.status(tmp_path)
    monkeypatch.setattr(fees,'proof',lambda:{'code_commit':'bad'})
    with pytest.raises(ValueError,match='Preregistro de comisiones'):
        arena.tick(tmp_path,frame(TS+30000,kind='paper'),proof=new)
    assert arena.status(tmp_path)['counts']==before['counts']
    assert arena.status(tmp_path)['wallets']==before['wallets']
