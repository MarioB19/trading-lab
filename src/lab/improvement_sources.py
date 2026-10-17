"""Sanitized read-only Railway collection; credentials never leave the server."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import inspect
import os
import shlex
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

PROJECT = "24021d85-bbad-4f2c-850c-e1230822e7b0"
ENVIRONMENT = "4774e5bf-c72b-402d-ac72-f88e815e5976"
SERVICES = {"pilot": "769ae901-e962-45e4-8666-11c3351f7249",
            "arena": "dfbea0de-ecdd-455c-bfb3-27d840d6f6b1"}

ERROR_MARKER = "IMPROVEMENT_SOURCE_ERROR="
ERROR_TYPES = ("KeyError", "ValueError", "TypeError", "RuntimeError", "HTTPError",
               "URLError", "TimeoutError", "ConnectionError", "OSError", "OperationalError")
ENDPOINTS = ("/api/status", "/api/performance", "/api/execution-quality", "/api/evidence",
             "/api/events?limit=500", "/api/trades?limit=500")
TRANSPORT_MARKERS = {"npm_enotempty": "ENOTEMPTY", "npm_enoent": "ENOENT",
                     "websocket": "websocket", "permission_denied": "permission denied",
                     "unauthorized": "unauthorized", "connection_reset": "connection reset",
                     "connection_failed": "connection failed", "timed_out": "timed out",
                     "python_traceback": "Traceback (most recent call last)"}


def safe_diagnostic(value):
    """Only fixed labels and bounded numbers may enter the immutable evidence."""
    if not isinstance(value, dict):
        return {}
    out = {}
    choices = {"stage": ("process_start", "transport", "remote_python", "response", "cli_resolution"),
               "reason": ("timeout", "nonzero_exit", "missing_marker", "invalid_json", "invalid_cli_path"),
               "exception_type": ERROR_TYPES + ("other",), "endpoint": ENDPOINTS}
    for key, allowed in choices.items():
        if isinstance(value.get(key), str) and value[key] in allowed:
            out[key] = value[key]
    for key, low, high in (("returncode", -255, 255), ("errno", 0, 4096),
                           ("http_status", 100, 599), ("timeout_seconds", 1, 3600)):
        item = value.get(key)
        if type(item) is int and low <= item <= high:
            out[key] = item
    lines = value.get("source_lines")
    if isinstance(lines, list):
        out["source_lines"] = [n for n in lines if type(n) is int and 0 < n <= 10000][:8]
    markers = value.get("observed_markers")
    if isinstance(markers, list):
        out["observed_markers"] = sorted({s for s in markers
                                          if isinstance(s, str) and s in TRANSPORT_MARKERS})
    return out


class SourceReadError(RuntimeError):
    def __init__(self, diagnostic):
        super().__init__("Fuente no disponible; no se alteró la operación")
        self.diagnostic = safe_diagnostic(diagnostic)


def diagnostic_script(script):
    """Run the exact reader; errors expose no values, paths or exception text."""
    return f'''import json,sys,traceback
from urllib.error import HTTPError
try:
 exec(compile({script!r}, '<trading_source>', 'exec'), {{}})
except Exception as error:
 kind=type(error).__name__
 detail={{'stage':'remote_python','exception_type':kind if kind in {ERROR_TYPES!r} else 'other'}}
 lines=[]
 for frame,line in traceback.walk_tb(error.__traceback__):
  if frame.f_code.co_filename=='<trading_source>':
   lines.append(line)
   path=frame.f_locals.get('path')
   if isinstance(path,str) and path in {ENDPOINTS!r}: detail['endpoint']=path
 detail['source_lines']=lines[-8:]
 if isinstance(error,HTTPError): detail['http_status']=error.code
 if isinstance(error,OSError) and type(error.errno) is int: detail['errno']=error.errno
 print({ERROR_MARKER!r}+json.dumps(detail,allow_nan=False))
 sys.exit(1)
'''


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

def compact_capture_hash(compact, serialized_inputs):
    """Hash the exact expanded frame without serializing shared candles again."""
    import hashlib
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False)
    candles = "{" + ",".join(encode(interval) + ":" + serialized_inputs[checksum]
                             for interval, checksum in sorted(compact["candles"].items())) + "}"
    expanded = "{" + ",".join(encode(key) + ":" + (candles if key == "candles" else encode(value))
                              for key, value in sorted(compact.items())) + "}"
    return hashlib.sha256(expanded.encode()).hexdigest()


def arena_input_audit(path):
    """Verify every archived byte in one read transaction, reusing candle JSON.

    Funding, wallet reconciliation and tiered fees remain checked by the existing
    daily_report and fees_report; this result only attests SQLite/market inputs.
    """
    import hashlib
    import zlib
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite no conserva integridad")
        serialized = {}
        for checksum, raw in db.execute("SELECT sha,payload FROM inputs"):
            rows = json.loads(zlib.decompress(raw))
            canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False)
            if hashlib.sha256(canonical.encode()).hexdigest() != checksum:
                raise ValueError("Las velas archivadas fueron alteradas")
            serialized[checksum] = canonical
        captures = 0
        for checksum, raw in db.execute("SELECT id,payload FROM captures"):
            if compact_capture_hash(json.loads(raw), serialized) != checksum:
                raise ValueError("La captura de mercado fue alterada")
            captures += 1
    return {"status": "verified", "captures": captures, "candle_inputs": len(serialized),
            "scope": "sqlite_integrity_inputs_and_captures", "wallets_verified": False,
            "profitability_verified": False, "live_authorized": False}


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
''' + inspect.getsource(arena_fills_at_count) + inspect.getsource(compact_capture_hash) + inspect.getsource(arena_input_audit) + '''
from time import monotonic
started=monotonic()
s=arena.status(Path('/data/arena'));d=daily_report(Path('/data/arena'))
audit_started=monotonic();a=arena_input_audit(Path('/data/arena')/arena.DB_NAME)
audit_seconds=monotonic()-audit_started
f=fees_report(Path('/data/arena'))
fills=arena_fills_at_count(Path('/data/arena')/arena.DB_NAME,s['counts']['fills'])
equity=sum(w['equity'] for w in s['wallets'])
out={'mode':s['mode'],'as_of_utc':datetime.fromtimestamp(s['last_observed_ms']/1000,timezone.utc).isoformat(),
 'build_id':release['build_id'],'files_match':files_match,
 'healthy':s['health']['status']=='ok' and not s['stale'],
 'reconciled':d['ledger']['reconciled'] is True and a['status']=='verified' and f['fee_ledger_verified'] is True,
 'started_at_utc':s['manifest']['started_at'],'current':{'equity_usd':equity,'pnl_usd':equity-s['capital_usd']},
 'wallets':s['wallets'],'fills':fills,'daily_report':d,'audit':a,'fees':f,
 'reader_timing':{'input_audit_seconds':audit_seconds,'total_seconds':monotonic()-started}}
print('IMPROVEMENT_SOURCE='+json.dumps(out,allow_nan=False))
'''


def railway_cli():
    """Resolve npm's executable once before concurrent SSH reads can update it."""
    try:
        installed = shutil.which("railway")
        if installed:
            return [installed]
        result = subprocess.run(
            ["npx", "--yes", "--package=@railway/cli", "--call", "command -v railway"],
            capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise SourceReadError({"stage": "cli_resolution", "reason": "timeout", "timeout_seconds": 30}) from None
    except OSError as exc:
        raise SourceReadError({"stage": "cli_resolution", "errno": exc.errno}) from None
    if result.returncode:
        combined = result.stdout.lower() + result.stderr.lower()
        raise SourceReadError({"stage": "cli_resolution", "reason": "nonzero_exit",
            "returncode": result.returncode,
            "observed_markers": [key for key, text in TRANSPORT_MARKERS.items() if text.lower() in combined]})
    candidate = result.stdout.strip()
    try:
        path = Path(candidate)
        valid = ("\n" not in candidate and "\r" not in candidate and path.is_absolute()
                 and path.is_file() and os.access(path, os.X_OK))
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise SourceReadError({"stage": "cli_resolution", "reason": "invalid_cli_path"})
    return [str(path)]


def _read(name, *, cli=None):
    script = PILOT if name == "pilot" else ARENA
    command = [*(railway_cli() if cli is None else cli), "ssh", "--project", PROJECT,
               "--service", SERVICES[name], "--environment", ENVIRONMENT,
               "python -c " + shlex.quote(diagnostic_script(script))]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        raise SourceReadError({"stage": "transport", "reason": "timeout", "timeout_seconds": 90}) from None
    except OSError as exc:
        raise SourceReadError({"stage": "process_start", "errno": exc.errno}) from None
    failure = next((line.split(ERROR_MARKER, 1)[1] for line in result.stdout.splitlines()
                    if ERROR_MARKER in line and len(line) < 4096), None)
    if failure is not None:
        try:
            detail = safe_diagnostic(json.loads(failure))
        except (TypeError, ValueError):
            detail = {}
        # A failure marker must never be accepted as a successful snapshot.
        raise SourceReadError({**detail, "stage": "remote_python", "returncode": result.returncode})
    if result.returncode:
        combined = result.stdout.lower() + result.stderr.lower()
        raise SourceReadError({"stage": "transport", "reason": "nonzero_exit",
                               "returncode": result.returncode,
                               "observed_markers": [key for key, text in TRANSPORT_MARKERS.items()
                                                    if text.lower() in combined]})
    raw = next((line.split("IMPROVEMENT_SOURCE=", 1)[1] for line in result.stdout.splitlines()
                if "IMPROVEMENT_SOURCE=" in line), None)
    if raw is None:
        raise SourceReadError({"stage": "response", "reason": "missing_marker"})
    try:
        return json.loads(raw)
    except ValueError:
        raise SourceReadError({"stage": "response", "reason": "invalid_json"}) from None


def collect(reader=None):
    results, errors = {}, {}
    if reader is None:
        try:
            cli = railway_cli()
        except SourceReadError as exc:
            return {"schema_version": 1, "collected_at_utc": datetime.now(timezone.utc).isoformat(),
                "collection_errors": {name: {"type": "SourceReadError",
                    "message": "Fuente no disponible; reintentar sin inventar datos",
                    "diagnostic": safe_diagnostic(exc.diagnostic)} for name in SERVICES}}
        def reader(name):
            return _read(name, cli=cli)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(reader, name) for name in SERVICES}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as exc:
                errors[name] = {"type": type(exc).__name__, "message": "Fuente no disponible; reintentar sin inventar datos"}
                if isinstance(exc, SourceReadError):
                    errors[name]["diagnostic"] = safe_diagnostic(exc.diagnostic)
    return {"schema_version": 1, "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            **results, "collection_errors": errors}
