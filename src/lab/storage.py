"""Durable runtime storage. JSON/CSV are exports; SQLite is authoritative.

An intent is committed *before* a network write. A remote timeout is not proof of
failure: unresolved orders remain blocked until reconciled. This does not claim
exactly-once execution at a remote exchange.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)


@contextmanager
def execution_lock(path):
    """Single local writer. Cloud runtime additionally needs one active instance."""
    import fcntl
    path = Path(str(path) + '.execution.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('otra ejecución mantiene el bloqueo de trading') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class SQLiteStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise RuntimeError(f'esquema SQLite {version} más nuevo que este ejecutor; no se modifica')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents(name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS equity(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS live_equity(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, namespace TEXT NOT NULL, status TEXT NOT NULL,
                    terminal INTEGER NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS orders_pending ON orders(namespace, terminal);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')
        os.chmod(self.path, 0o600)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=30000')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def connect(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        db = self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _read(db, name, default=None):
        row = db.execute('SELECT payload FROM documents WHERE name=?', (name,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def _write(db, name, value):
        db.execute('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at',
                   (name, dumps(value), utcnow()))

    def read_document(self, name, default=None):
        with self.connect() as db:
            return self._read(db, name, default)

    def write_document(self, name, value):
        with self.transaction() as db:
            self._write(db, name, value)

    @staticmethod
    def _row_id(table, row):
        if table == 'trades':
            return row.get('execution_id') or hashlib.sha256(dumps(row).encode()).hexdigest()
        keys = ('date', 'sleeve', 'mode') if table == 'equity' else ('time_utc', 'sleeve', 'mode')
        return '|'.join(str(row.get(k, '')) for k in keys)

    def _rows(self, db, table, rows):
        if table not in ('trades', 'equity', 'live_equity'):
            raise ValueError('tabla no permitida')
        for row in rows:
            conflict = 'DO NOTHING' if table == 'trades' else 'DO UPDATE SET payload=excluded.payload'
            db.execute(f'INSERT INTO {table} VALUES(?,?,?) ON CONFLICT(id) {conflict}',
                       (self._row_id(table, row), dumps(row), utcnow()))

    def rows(self, table):
        if table not in ('trades', 'equity', 'live_equity', 'events'):
            raise ValueError('tabla no permitida')
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(f'SELECT payload FROM {table} ORDER BY rowid')]

    def commit_run(self, state, trades, equity, snapshot):
        with self.transaction() as db:
            self._write(db, 'state', state)
            self._rows(db, 'trades', trades)
            self._rows(db, 'equity', equity)
            self._write(db, 'snapshot', snapshot)

    def commit_live(self, live, rows):
        with self.transaction() as db:
            self._write(db, 'live', live)
            self._rows(db, 'live_equity', rows)

    def record_event(self, kind, payload):
        with self.transaction() as db:
            db.execute('INSERT INTO events(kind,payload,created_at) VALUES(?,?,?)', (kind, dumps(payload), utcnow()))

    def events(self, limit=100):
        with self.connect() as db:
            return [{"id": row["id"], "kind": row["kind"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]}
                    for row in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?', (max(1, min(int(limit), 10000)),))]

    def orders(self, namespace=None, pending_only=False):
        query = 'SELECT payload FROM orders WHERE 1=1'
        args = []
        if namespace is not None:
            query += ' AND namespace=?'; args.append(namespace)
        if pending_only:
            query += ' AND terminal=0'
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(query+' ORDER BY rowid', args)]

    @staticmethod
    def put_order(db, order):
        previous = db.execute('SELECT payload FROM orders WHERE id=?', (order['id'],)).fetchone()
        previous = json.loads(previous[0]) if previous else {}
        if any(previous.get(k) != order.get(k) for k in ('status', 'filled_qty', 'terminal')):
            db.execute('INSERT INTO events(kind,payload,created_at) VALUES(?,?,?)',
                       ('order_transition', dumps({k: order.get(k) for k in ('id', 'namespace', 'status', 'filled_qty', 'terminal')}), utcnow()))
        db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, terminal=excluded.terminal, payload=excluded.payload, updated_at=excluded.updated_at',
                   (order['id'], order['namespace'], order['status'], int(order['terminal']), dumps(order), utcnow()))

    def health(self):
        with self.connect() as db:
            return {'database': str(self.path), 'integrity': db.execute('PRAGMA quick_check').fetchone()[0],
                    'pending_orders': db.execute('SELECT count(*) FROM orders WHERE terminal=0').fetchone()[0],
                    'unknown_orders': db.execute("SELECT count(*) FROM orders WHERE status IN ('unknown','intent')").fetchone()[0],
                    'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0], 'schema_version': db.execute('PRAGMA user_version').fetchone()[0]}

    def backup(self, path):
        target = Path(path)
        if target.resolve() == self.path.resolve():
            raise ValueError('el backup debe tener una ruta distinta')
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        os.chmod(target, 0o600)
        return target

    def import_legacy(self, source):
        """Explicit, one-time import of internally simulated paper state only."""
        import math
        source = Path(source)
        state_path = source / 'state.json'
        if not state_path.is_file():
            raise ValueError('falta state.json para importar')
        documents = {}
        hashes = {}
        for name in ('state', 'snapshot', 'live'):
            path = source / (name + '.json')
            if path.exists():
                documents[name] = json.loads(path.read_text())
                hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        state = documents['state']
        if not isinstance(state.get('sleeves'), dict):
            raise ValueError('estado sin sleeves válido')
        for sleeve in state['sleeves'].values():
            if sleeve.get('mode', 'paper') != 'paper':
                raise ValueError('solo se importa estado paper')
            if sleeve.get('sleeve_cash') is not None or sleeve.get('account_namespace') or (sleeve.get('last_candle') and 'ledger' not in sleeve):
                raise ValueError('estado externo sin propiedad verificable: migración manual requerida')
        numeric = {'qty', 'price', 'value', 'fee', 'ref_price', 'cost_bps', 'equity', 'cash', 'exposure',
                   'drawdown', 'brake', 'benchmark_price', 'n_positions', 'usd_mxn', 'flow', 'brake_now'}
        tables = {}
        for name in ('trades', 'equity', 'live_equity'):
            path = source / (name + '.csv')
            tables[name] = []
            if not path.exists():
                continue
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            with path.open(newline='') as handle:
                for raw in csv.DictReader(handle):
                    row = dict(raw)
                    for field in numeric.intersection(row):
                        value = row[field]
                        if value in ('', None):
                            row[field] = None
                        else:
                            n = float(value)
                            row[field] = (int(n) if field == 'n_positions' else n) if math.isfinite(n) else None
                    tables[name].append(row)
        def finite(value):
            if isinstance(value, dict):
                return {k: finite(v) for k, v in value.items()}
            if isinstance(value, list):
                return [finite(v) for v in value]
            if isinstance(value, float) and not math.isfinite(value):
                return None
            return value
        summary = {'imported_at': utcnow(), 'sleeves': len(state['sleeves']),
                   'counts': {k: len(v) for k, v in tables.items()}, 'sha256': hashes}
        with self.transaction() as db:
            populated = any(db.execute(f'SELECT 1 FROM {name} LIMIT 1').fetchone()
                            for name in ('documents', 'trades', 'equity', 'live_equity', 'orders'))
            if populated:
                raise ValueError('la importación requiere una base de datos vacía')
            for name, value in documents.items():
                self._write(db, name, finite(value))
            for name, rows in tables.items():
                self._rows(db, name, rows)
            self._write(db, 'legacy_import', summary)
        return summary

    def export(self, paths, trade_fields, equity_fields):
        """Replace derived exports atomically per file; DB remains authoritative on failure."""
        for name in ('state', 'snapshot'):
            value = self.read_document(name)
            if value is not None:
                path = Path(paths[name]); path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix('.tmp'); tmp.write_text(dumps(value)); tmp.replace(path)
        for name, fields in (('trades', trade_fields), ('equity', equity_fields)):
            path = Path(paths[name]); path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp')
            with tmp.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
                writer.writeheader(); writer.writerows(self.rows(name))
            tmp.replace(path)
