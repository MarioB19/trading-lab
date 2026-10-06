"""Sanitized read-only Railway collection; credentials never leave the server."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import inspect
import shlex
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

PROJECT = "24021d85-bbad-4f2c-850c-e1230822e7b0"
ENVIRONMENT = "4774e5bf-c72b-402d-ac72-f88e815e5976"
SERVICES = {"pilot": "769ae901-e962-45e4-8666-11c3351f7249",
            "arena": "dfbea0de-ecdd-455c-bfb3-27d840d6f6b1"}


def pilot_is_healthy(status):
    runtime = status.get("runtime", {})
    state = runtime.get("status")
    if status.get("ready") is not True or state not in {"ok", "running"}:
        return False
    # run_cycle writes no errors field until completion. Only a running cycle
    # with verified readiness may omit it; null/malformed fields still fail.
    return runtime.get("errors", [] if state == "running" else None) == []


def arena_fills_at_count(path, count):
    """Read the complete immutable prefix belonging to the status snapshot."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("SELECT payload FROM fills ORDER BY id LIMIT ?", (count,)).fetchall()
    if len(rows) != count:
        raise ValueError("Historial de fills incompleto")
    return [json.loads(row[0]) for row in rows]

COMMON = '''
import base64,hashlib,json,os
from pathlib import Path
from urllib.request import Request,urlopen
from datetime import datetime,timezone
release=json.loads(Path('/app/release.json').read_text())
auth='Basic '+base64.b64encode((os.environ['TRADING_DASHBOARD_USER']+':'+os.environ['TRADING_DASHBOARD_PASSWORD']).encode()).decode()
def get(path):
 with urlopen(Request('http://127.0.0.1:'+os.environ.get('PORT','8080')+path,headers={'Authorization':auth}),timeout=30) as r:
  return json.load(r)
files_match=all(hashlib.sha256((Path('/app')/p).read_bytes()).hexdigest()==h for p,h in release['files'].items() if p!='Dockerfile')
'''
PILOT = COMMON + inspect.getsource(pilot_is_healthy) + '''
s=get('/api/status');p=get('/api/performance');q=get('/api/execution-quality');e=get('/api/evidence')
out={'mode':s['mode'],'as_of_utc':s['runtime']['last_success_utc'],'build_id':release['build_id'],
 'files_match':files_match,'healthy':pilot_is_healthy(s),
 'health_evidence':{'ready':s['ready'],'reason':s.get('reason'),'runtime_status':s['runtime'].get('status'),
                    'errors_present':'errors' in s['runtime'],'runtime_errors':s['runtime'].get('errors')},
 'reconciled':s['analysis']['valid'] is True and not s['analysis']['issues'] and s['storage']['pending_orders']==0 and s['storage']['unknown_orders']==0,
 'current':p['current'],'daily':p['daily'],'execution_quality':q,'evidence':e,
 'drawdowns':{k:v['drawdown'] for k,v in s['live']['sleeves'].items()},
 'kill_switches':{k:v['kill_switch'] for k,v in s['live']['sleeves'].items()},
 'storage':s['storage'],'analysis':s['analysis']['summary'],
 'events':get('/api/events?limit=500')['items'],'trades':get('/api/trades?limit=500')['items']}
print('IMPROVEMENT_SOURCE='+json.dumps(out,allow_nan=False))
'''
ARENA = COMMON + '''
import sqlite3
from contextlib import closing
from lab import arena
from lab.arena_reporting import daily_report
from lab.arena_fees import report as fees_report
''' + inspect.getsource(arena_fills_at_count) + '''
s=arena.status(Path('/data/arena'));d=daily_report(Path('/data/arena'));a=arena.audit(Path('/data/arena'));f=fees_report(Path('/data/arena'))
fills=arena_fills_at_count(Path('/data/arena')/arena.DB_NAME,s['counts']['fills'])
equity=sum(w['equity'] for w in s['wallets'])
out={'mode':s['mode'],'as_of_utc':datetime.fromtimestamp(s['last_observed_ms']/1000,timezone.utc).isoformat(),
 'build_id':release['build_id'],'files_match':files_match,
 'healthy':s['health']['status']=='ok' and not s['stale'],
 'reconciled':d['ledger']['reconciled'] is True and a['status']=='verified' and f['fee_ledger_verified'] is True,
 'started_at_utc':s['manifest']['started_at'],'current':{'equity_usd':equity,'pnl_usd':equity-s['capital_usd']},
 'wallets':s['wallets'],'fills':fills,'daily_report':d,'audit':a,'fees':f}
print('IMPROVEMENT_SOURCE='+json.dumps(out,allow_nan=False))
'''


def _read(name):
    script = PILOT if name == "pilot" else ARENA
    command = ["npx", "--yes", "@railway/cli", "ssh", "--project", PROJECT,
               "--service", SERVICES[name], "--environment", ENVIRONMENT,
               "python -c " + shlex.quote(script)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError("Railway no pudo leer " + name + "; no se alteró la operación")
    raw = next((line.split("IMPROVEMENT_SOURCE=", 1)[1] for line in result.stdout.splitlines()
                if "IMPROVEMENT_SOURCE=" in line), None)
    if raw is None:
        raise RuntimeError("La fuente no devolvió evidencia estructurada: " + name)
    return json.loads(raw)


def collect(reader=_read):
    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(reader, name) for name in SERVICES}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as exc:
                errors[name] = {"type": type(exc).__name__, "message": "Fuente no disponible; reintentar sin inventar datos"}
    return {"schema_version": 1, "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            **results, "collection_errors": errors}
