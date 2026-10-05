from contextlib import closing
from datetime import datetime
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import threading
from zoneinfo import ZoneInfo

import pytest
from lab import arena
from lab.arena_reporting import daily_report, report_csv, _quality
from lab.arena_reporting_upgrade import upgrade, SOURCE_COMMIT, PREREG, verify_frozen_engine
from lab.arena_service import make_server
from test_arena import frame


def local_ts(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=ZoneInfo('America/Mexico_City')).timestamp()*1000)


def seed(directory, ts, mid=100):
    arena.initialize(directory, 'synthetic')
    arena.tick(directory, frame(ts,mid))


def test_daily_pnl_uses_cdmx_and_fees_are_not_subtracted_twice(tmp_path):
    ts=local_ts('2026-10-04T23:59:30')
    seed(tmp_path,ts)
    first=arena.status(tmp_path)
    arena.tick(tmp_path,frame(ts+60000,102))
    last=arena.status(tmp_path)
    r=daily_report(tmp_path,at_ms=ts+75000)
    assert [d['date'] for d in r['days']]==['2026-10-05','2026-10-04']
    a,b=r['days'][1],r['days'][0]
    assert a['net_pnl']==pytest.approx(first['total_equity']-4000)
    assert a['fees']==pytest.approx(sum(w['fees'] for w in first['wallets']))
    assert b['net_pnl']==pytest.approx(last['total_equity']-first['total_equity'])
    assert a['net_pnl']+b['net_pnl']==pytest.approx(last['total_equity']-4000)
    assert a['partial_start'] and not a['in_progress'] and b['in_progress']
    for d in [a,b]:
        assert sum(w['net_pnl'] for w in d['strategies'])==pytest.approx(d['net_pnl'])
        for w in d['strategies']:
            assert w['realized_pnl']+w['unrealized_change']==pytest.approx(w['net_pnl'])
    assert r['ledger']['reconciled']


def test_no_data_day_is_unknown_and_next_day_does_not_claim_multiday_pnl(tmp_path):
    ts=local_ts('2026-10-04T22:00:00');seed(tmp_path,ts)
    arena.tick(tmp_path,frame(ts+2*86400000,105))
    r=daily_report(tmp_path,at_ms=ts+2*86400000+10000)
    current,missing,first=r['days']
    assert missing['no_data'] and missing['net_pnl'] is None and missing['closing_equity'] is None
    assert missing['quality']['coverage']==0
    assert current['opening_missing'] and current['net_pnl'] is None
    assert current['closing_equity']>0
    assert first['net_pnl'] is not None


def test_coverage_does_not_credit_unobserved_gap():
    q=_quality([1000,301000],1000,311000)
    assert q['coverage']==pytest.approx(100/310)
    assert q['missing_seconds']==210 and q['gaps']==1
    assert _quality([],0,1000)['coverage']==0
    assert _quality([0],0,0)['coverage'] is None


def test_full_ledger_includes_more_than_250_fills_and_csv_all_strategies(tmp_path):
    ts=local_ts('2026-10-04T20:00:00');seed(tmp_path,ts)
    with closing(arena.connect(tmp_path)) as db,db:
        w=json.loads(db.execute('SELECT payload FROM wallets WHERE id=?',('mean-reversion-v1',)).fetchone()[0])
        for i in range(300):arena._fill(db,w,'buy',.0001,100,.0036,ts+1,'taker','test','fixture')
        db.execute('UPDATE wallets SET payload=? WHERE id=?',(arena._json(w),w['id']))
    arena.tick(tmp_path,frame(ts+15000))
    r=daily_report(tmp_path,at_ms=ts+16000)
    day=r['days'][0];reversion=next(w for w in day['strategies'] if w['id']=='mean-reversion-v1')
    assert reversion['operations']==300 and reversion['fees']==pytest.approx(.0108)
    assert r['ledger']['fills_checked']>=300 and r['ledger']['reconciled']
    import csv,io
    rows=list(csv.DictReader(io.StringIO(report_csv(r).lstrip('\ufeff'))))
    assert len(rows)==4
    assert rows[2]['operaciones']=='300' and rows[2]['zona_horaria']=='America/Mexico_City'


def test_ledger_detects_tampered_balance_without_modifying_database(tmp_path):
    ts=local_ts('2026-10-04T20:00:00');seed(tmp_path,ts)
    with closing(arena.connect(tmp_path)) as db,db:
        w=json.loads(db.execute('SELECT payload FROM wallets LIMIT 1').fetchone()[0]);w['cash']+=10
        db.execute('UPDATE wallets SET payload=? WHERE id=?',(arena._json(w),w['id']))
    path=tmp_path/arena.DB_NAME
    before=path.read_bytes()
    r=daily_report(tmp_path,at_ms=ts+1000)
    assert not r['ledger']['reconciled']
    assert path.read_bytes()==before


def test_empty_arena_has_no_fabricated_daily_rows(tmp_path):
    arena.initialize(tmp_path)
    r=daily_report(tmp_path)
    assert r['days']==[] and r['as_of_ms'] is None and r['stale']
    assert r['ledger']['reconciled']


def test_drawdown_uses_every_valuation_not_chart_samples(tmp_path):
    ts=local_ts('2026-10-04T19:00:00');seed(tmp_path,ts)
    # A read-only report must see even a brief valuation trough not in a sampled chart.
    with closing(arena.connect(tmp_path)) as db,db:
        for i in range(1,405):
            t=ts+i*1000;db.execute('INSERT INTO captures VALUES (?,?,?)',(str(i),t,'{}'))
            for wid in arena.NAMES:
                p={'ts':t,'equity':800 if i==201 else 1000,'fees':0,'pnl':0,'drawdown':0}
                db.execute('INSERT INTO equity(strategy,ts,payload) VALUES (?,?,?)',(wid,t,arena._json(p)))
    d=daily_report(tmp_path,at_ms=ts+405000)['days'][0]
    assert all(w['max_drawdown']==pytest.approx(-.2) for w in d['strategies'])
    assert all(w['observations']==405 for w in d['strategies'])


def test_reporting_upgrade_requires_stopped_writer_preserves_balances(tmp_path,monkeypatch):
    # Legacy migration tested with its frozen engine; v2 must use upgrade-fees.
    from lab import arena_reporting_upgrade as mod
    monkeypatch.setattr(mod, 'verify_frozen_engine', lambda: None)
    arena.initialize(tmp_path)
    old={'code_commit':SOURCE_COMMIT,'commit':PREREG}
    new={**old,'code_commit':'b'*40}
    with closing(arena.connect(tmp_path)) as db,db:
        manifest=json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0]);manifest['proof']=old
        db.execute("UPDATE meta SET value=? WHERE key='manifest'",(arena._json(manifest),))
    monkeypatch.setattr(arena,'execution_proof',lambda _:new)
    before=arena.status(tmp_path)
    with pytest.raises(ValueError):upgrade(tmp_path)
    (tmp_path/'arena.enabled').write_text('on')
    with pytest.raises(ValueError):upgrade(tmp_path,cutover_confirmed=True)
    (tmp_path/'arena.enabled').unlink()
    assert upgrade(tmp_path,cutover_confirmed=True)['status']=='upgraded'
    after=arena.status(tmp_path)
    for k in ['wallets','history','fills','counts']:assert after[k]==before[k]
    assert after['events'][0]['previous_proof']==old
    assert upgrade(tmp_path,cutover_confirmed=True)['status']=='already_upgraded'


def test_reporting_upgrade_protects_trading_source(tmp_path,monkeypatch):
    monkeypatch.setattr(arena,'ROOT',tmp_path)
    from lab import arena_reporting_upgrade as mod
    monkeypatch.setattr(mod,'FROZEN_FILES',{'portfolio.py':'0'*64})
    (tmp_path/'portfolio.py').write_text('changed')
    with pytest.raises(ValueError,match='ejecución'):verify_frozen_engine()


def test_legacy_reporting_migration_rejects_the_new_cost_engine():
    with pytest.raises(ValueError, match='ejecución'):
        verify_frozen_engine()
