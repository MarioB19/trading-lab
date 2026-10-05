#!/usr/bin/env python3
"""Start/stop the two dedicated local processes; never modifies the existing pilot."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'runtime-data/arena-paper'
PIDFILE = DIRECTORY / 'local-processes.json'


def running(record):
    result = subprocess.run(['ps', '-p', str(record['pid']), '-o', 'command='], capture_output=True, text=True)
    return result.returncode == 0 and record['module'] in result.stdout and str(DIRECTORY) in result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    previous = json.loads(PIDFILE.read_text()) if PIDFILE.exists() else []
    if args.action == 'status':
        print(json.dumps([{**r, 'running': running(r)} for r in previous]))
        return
    if args.action == 'stop':
        for record in previous:
            if running(record):
                os.kill(record['pid'], signal.SIGTERM)
        print('Detenidos los procesos locales de esta arena; saldos conservados.')
        return
    sys.path.insert(0, str(ROOT / 'src'))
    from lab.arena import NAMES, PREREG_PATH, initialize, plan
    from lab.experiments import verify_preregistration
    cfg = plan()
    commit = subprocess.check_output(['git', '-C', str(ROOT), 'log', '-1', '--format=%H', '--', str(PREREG_PATH)], text=True).strip()
    verify_preregistration(ROOT, PREREG_PATH, commit, cfg['experiment_id'], cfg, list(NAMES))
    initialize(DIRECTORY)
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    records = []
    for module, extra in [('lab.arena_service', ['--port', '8874']),
                          ('lab.arena', ['run', '--preregistration-commit', commit])]:
        found = next((r for r in previous if r['module'] == module and running(r)), None)
        if found:
            records.append(found)
            continue
        if module == 'lab.arena_service':
            import socket
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1', 8874)) == 0:
                    raise RuntimeError('Puerto 8874 ocupado. No se detiene un proceso ajeno.')
        with (DIRECTORY / (module.split('.')[-1] + '.log')).open('ab') as log:
            proc = subprocess.Popen([sys.executable, '-m', module, *extra, '--directory', str(DIRECTORY)],
                                    cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        records.append({'module': module, 'pid': proc.pid})
        PIDFILE.write_text(json.dumps(records, indent=2) + '\n')
    time.sleep(1)
    if not all(running(r) for r in records):
        raise RuntimeError('Un proceso no arrancó; consultar logs en runtime-data/arena-paper')
    with urlopen('http://127.0.0.1:8874/healthz', timeout=3) as response:
        assert response.status == 200
    print('Arena local disponible en http://127.0.0.1:8874/; proceso paper iniciado. Consultar estado para verificar el primer ciclo.')


if __name__ == '__main__':
    main()
