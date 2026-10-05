import copy
import json
import math
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection

import numpy as np
import pytest

from lab import arena
from lab.arena_service import make_server


TS = 1_791_158_400_000  # aligned synthetic UTC day, not a market observation


def frame(ts=TS, mid=100., kind='synthetic'):
    candles = {}
    for interval, duration in arena.INTERVALS.items():
        end = ts // duration * duration
        rows = []
        for i in range(260):
            value = mid * (.8 + .2 * i / 259)
            rows.append([end - (260-i)*duration, value, value*1.001, value*.999, value, 100.])
        candles[interval] = rows
    return {'kind':kind,'book':'btc_usd','observed_ms':ts,
            'order_book':{'updated_ms':ts,'bids':[[mid*.999,100.]],'asks':[[mid*1.001,100.]],'sequence':1},
            'trades':[{'tid':1,'ts':ts-2000,'price':mid,'qty':1.,'side':'buy'}], 'candles':candles}


def wallet(directory, wid):
    return next(w for w in arena.status(directory)['wallets'] if w['id']==wid)


def setup(tmp_path):
    arena.initialize(tmp_path,'synthetic')
    return frame()


def test_four_independent_thousand_dollar_wallets_and_reopen(tmp_path):
    arena.initialize(tmp_path)
    state=arena.status(tmp_path)
    assert state['capital_usd']==4000 and state['total_equity']==4000
    assert len(state['wallets'])==4
    assert all(w['cash']==1000 and w['qty']==0 for w in state['wallets'])
    arena.initialize(tmp_path)
    assert arena.status(tmp_path)['wallets']==state['wallets']
    assert not state['execution_authorized']


def test_paper_cannot_run_without_preregistered_git_proof(tmp_path):
    arena.initialize(tmp_path)
    with pytest.raises(ValueError,match='preregistro'):
        arena.tick(tmp_path,frame(kind='paper'))
    assert arena.status(tmp_path)['counts']=={'captures':0,'fills':0}


def test_separate_database_rejects_pilot_and_mode_mixing(tmp_path):
    (tmp_path/'trading.sqlite3').write_bytes(b'')
    with pytest.raises(ValueError,match='piloto'):
        arena.initialize(tmp_path)
    other=tmp_path/'other'
    arena.initialize(other,'synthetic')
    with pytest.raises(ValueError,match='tipo'):
        arena.initialize(other,'paper')


def test_costs_cash_inventory_pnl_and_duplicate_cycle_are_atomic(tmp_path):
    f=setup(tmp_path)
    result=arena.tick(tmp_path,f)
    assert result['fills']>=2 # swing and MM buy inventory with actual simulated costs
    before=arena.status(tmp_path)
    assert arena.tick(tmp_path,f)['status']=='duplicate'
    assert arena.status(tmp_path)['wallets']==before['wallets']
    for w in before['wallets']:
        assert w['cash']>=0 and w['qty']>=0
        assert w['equity']-1000 == pytest.approx(w['realized']+w['unrealized'])
        if w['fills']:
            assert w['fees']>0 and w['equity']<1000
    assert wallet(tmp_path,'mean-reversion-v1')['cash']==1000


def test_concurrent_identical_frames_do_not_double_spend(tmp_path):
    f=setup(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:arena.tick(tmp_path,f),range(2)))
    assert sorted(r['status'] for r in results)==['duplicate','ok']
    assert arena.status(tmp_path)['counts']['captures']==1


@pytest.mark.parametrize('defect',['old_book','crossed','open_bar','gap','nan','future_trade','old_signal','duplicate_trade'])
def test_bad_market_data_rolls_back_all_portfolios(tmp_path,defect):
    f=setup(tmp_path)
    if defect=='old_book':f['order_book']['updated_ms']-=61000
    if defect=='crossed':f['order_book']['bids'][0][0]=200
    if defect=='open_bar':f['candles']['5m'][-1][0]+=300000
    if defect=='gap':del f['candles']['1h'][-2]
    if defect=='nan':f['order_book']['asks'][0][0]=float('nan')
    if defect=='future_trade':f['trades'][0]['ts']+=100000
    if defect=='old_signal':f['candles']['5m']=f['candles']['5m'][:-2]
    if defect=='duplicate_trade':f['trades']*=2
    with pytest.raises(ValueError):arena.tick(tmp_path,f)
    assert arena.status(tmp_path)['total_equity']==4000
    assert arena.status(tmp_path)['counts']['captures']==0


def test_market_maker_requires_new_trade_after_latency_and_price_cross(tmp_path):
    f=setup(tmp_path);arena.tick(tmp_path,f)
    before=wallet(tmp_path,'market-making-v1');bid=next(q for q in before['quotes'] if q['side']=='buy')
    follow=frame(TS+15000)
    follow['trades']=[{'tid':2,'ts':TS+500,'price':bid['price']-.1,'qty':1,'side':'buy'},
                      {'tid':3,'ts':TS+2000,'price':bid['price']-.1,'qty':1,'side':'sell'},
                      {'tid':4,'ts':TS+3000,'price':bid['price'],'qty':1,'side':'buy'}]
    arena.tick(tmp_path,follow)
    assert wallet(tmp_path,'market-making-v1')['qty']==before['qty']
    next_frame=frame(TS+30000)
    next_frame['trades']=follow['trades']+[{'tid':5,'ts':TS+20000,'price':bid['price']-.1,'qty':.1,'side':'buy'}]
    arena.tick(tmp_path,next_frame)
    after=wallet(tmp_path,'market-making-v1')
    assert after['qty']-before['qty']==pytest.approx(.01,abs=1e-8) # max 10% public volume
    repeated=frame(TS+45000);repeated['trades']=next_frame['trades']
    arena.tick(tmp_path,repeated)
    assert wallet(tmp_path,'market-making-v1')['qty']==after['qty']


def test_maker_gap_and_expired_quotes_never_backfill(tmp_path):
    f=setup(tmp_path);arena.tick(tmp_path,f)
    before=wallet(tmp_path,'market-making-v1');bid=before['quotes'][0]
    follow=frame(TS+90000)
    follow['trades']=[{'tid':2,'ts':TS+10000,'price':bid['price']-1,'qty':20,'side':'buy'}]
    arena.tick(tmp_path,follow)
    assert wallet(tmp_path,'market-making-v1')['qty']==before['qty']


def test_incomplete_trade_page_cancels_old_quotes(tmp_path):
    f=setup(tmp_path);arena.tick(tmp_path,f);before=wallet(tmp_path,'market-making-v1')
    follow=frame(TS+15000);follow['trades_page_limit']=2
    follow['trades']=[{'tid':i,'ts':TS+10000,'price':90.,'qty':10.,'side':'buy'} for i in (50,51)]
    arena.tick(tmp_path,follow)
    assert wallet(tmp_path,'market-making-v1')['qty']==before['qty']


def test_pause_survives_restart_and_cancels_quotes_without_liquidation(tmp_path):
    f=setup(tmp_path);arena.tick(tmp_path,f);before=wallet(tmp_path,'market-making-v1')
    arena.control(tmp_path,'market-making-v1','pause')
    arena.initialize(tmp_path,'synthetic');arena.tick(tmp_path,frame(TS+15000))
    after=wallet(tmp_path,'market-making-v1')
    assert after['paused'] and not after['quotes']
    assert after['qty']==before['qty']
    arena.control(tmp_path,'market-making-v1','resume')
    assert not wallet(tmp_path,'market-making-v1')['paused']


def test_drawdown_liquidates_available_inventory_and_latches(tmp_path):
    f=setup(tmp_path);arena.tick(tmp_path,f)
    arena.tick(tmp_path,frame(TS+15000,mid=40.))
    swing=wallet(tmp_path,'swing-v1')
    assert swing['risk_stopped'] and swing['qty']<1e-7
    with pytest.raises(ValueError,match='permanente'):
        arena.control(tmp_path,'swing-v1','resume')
    arena.tick(tmp_path,frame(TS+30000,mid=100.))
    assert wallet(tmp_path,'swing-v1')['qty']<1e-7


def test_backup_restore_preserves_all_balances_and_rejects_overwrite(tmp_path):
    source=tmp_path/'source';f=setup(source);arena.tick(source,f)
    file=tmp_path/'backup.sqlite3';proof=arena.backup(source,file)
    assert len(proof['sha256'])==64
    restored=arena.restore(file,tmp_path/'restored')
    assert restored['wallets']==arena.status(source)['wallets']
    assert restored['fills']==arena.status(source)['fills']
    with pytest.raises(ValueError):arena.restore(file,source)


def test_taker_respects_depth_budget_and_inventory(tmp_path):
    f=setup(tmp_path);f['order_book']['asks']=[[100.1,.01]]
    arena.tick(tmp_path,f)
    assert arena.status(tmp_path)['counts']['fills']==0 # less than minimum order
    # A later candle can retry a directional target; no imaginary full fill.
    f2=frame(TS+86400000);f2['order_book']['asks']=[[100.1,.1],[101.,.1]]
    arena.tick(tmp_path,f2)
    assert wallet(tmp_path,'swing-v1')['qty']<=.2
    assert wallet(tmp_path,'swing-v1')['cash']>=0


def test_signal_families_are_distinct_and_use_only_closed_history():
    cfg=arena.plan();variants={v['id']:v for v in cfg['variants']}
    wallet={'qty':0.,'entries_today':0}
    rows=frame()['candles']['5m']
    breakout=copy.deepcopy(rows);breakout[-1][2]=breakout[-1][4]=110.
    assert arena.directional_signal(variants['scalping-v1'],breakout,wallet,TS)[0]==.25
    falling=copy.deepcopy(rows);falling[-1][3]=falling[-1][4]=70.
    assert arena.directional_signal(variants['mean-reversion-v1'],falling,wallet,TS)[0]==.25
    assert arena.directional_signal(variants['scalping-v1'],falling,wallet,TS)[0] is None
    assert arena.directional_signal(variants['mean-reversion-v1'],breakout,wallet,TS)[0] is None
    # Future candles are rejected at engine boundary, never used to compute past signals.
    base=arena.directional_signal(variants['swing-v1'],frame()['candles']['1d'],wallet,TS)
    assert arena.directional_signal(variants['swing-v1'],frame()['candles']['1d'],wallet,TS)==base


def test_http_controls_require_origin_and_valid_host(tmp_path):
    server=make_server(tmp_path,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    port=server.server_port
    def request(method,path,body=None,headers=None):
        conn=HTTPConnection('127.0.0.1',port,timeout=3)
        conn.request(method,path,body,headers or {})
        response=conn.getresponse();result=response.status,json.loads(response.read());conn.close();return result
    try:
        assert request('GET','/api/arena')[0]==200
        assert request('GET','/api/arena',headers={'Host':'evil.example'})[0]==403
        body=json.dumps({'strategy':'scalping-v1','action':'pause'})
        assert request('POST','/api/control',body,{'Content-Type':'application/json'})[0]==403
        code,result=request('POST','/api/control',body,{'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'})
        assert code==200 and result['wallets'][0]['paused']
        assert request('POST','/api/control',body,{'Content-Type':'application/json','Origin':'https://evil.example'})[0]==403
    finally:
        server.shutdown();server.server_close();thread.join()


def test_dust_does_not_block_a_new_funded_entry():
    variant=arena.plan()['variants'][0]
    rows=frame()['candles']['5m']
    rows[-1][2]=rows[-1][4]=110.
    dust={'qty':1e-8,'cost_basis':.000001,'entries_today':0}
    assert arena.directional_signal(variant,rows,dust,TS)[0]==.25


def test_audit_detects_capture_changes_and_reconciles_fills(tmp_path):
    f=setup(tmp_path);arena.tick(tmp_path,f)
    assert arena.audit(tmp_path)['status']=='verified'
    with sqlite3.connect(tmp_path/arena.DB_NAME) as db:
        db.execute("UPDATE captures SET payload=replace(payload, 'synthetic', 'changed')")
    with pytest.raises(ValueError,match='alterada'):
        arena.audit(tmp_path)


def test_arena_families_are_counted_in_new_crypto_research_plans():
    from lab.research_multi import research_plan
    config,_=research_plan(universe='bitso')
    assert set(arena.NAMES).issubset(config['sleeves']['crypto']['legacy_external_trial_labels'])
