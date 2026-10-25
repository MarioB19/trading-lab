"""Read-only operational API; hosted use requires authentication and HTTPS termination."""
from __future__ import annotations

import argparse
import base64
import binascii
from contextlib import closing
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlparse

import yaml

from .analyze import build_analysis
from .performance import build_performance
from .execution_quality import build_execution_quality
from .runtime import DATABASE_NAME, readiness

ASSET_DIR = Path(__file__).resolve().parents[2] / "dashboard"
ROOT_DIR = ASSET_DIR.parent
ASSETS = {"/": ("operations.html", "text/html; charset=utf-8"),
          "/operations.js": ("operations.js", "text/javascript; charset=utf-8"),
          "/tabs.js": ("tabs.js", "text/javascript; charset=utf-8"),
          "/operations.css": ("operations.css", "text/css; charset=utf-8")}
BACKUP_NAME = re.compile(r"hosted-\d{8}T\d{12}Z-[0-9a-f]{12}\.sqlite3")
MAX_PART = 16 * 1024 * 1024


class AuthThrottle:
    """Límite de intentos fallidos de contraseña por cliente (F6: el dominio propio es fácil de adivinar).

    Tras `max_failures` fallos en `window` segundos, el cliente recibe 429 durante `lockout` segundos,
    aunque luego mande la contraseña correcta. Memoria acotada: se descartan claves viejas.
    """

    def __init__(self, max_failures=10, window=900.0, lockout=900.0, clock=time.monotonic, max_keys=10_000):
        self.max_failures, self.window, self.lockout, self.clock, self.max_keys = max_failures, window, lockout, clock, max_keys
        self.failures: dict[str, list[float]] = {}
        self.locked: dict[str, float] = {}
        self.lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        with self.lock:
            until = self.locked.get(key)
            now = self.clock()
            if until is None:
                return 0
            if until <= now:
                del self.locked[key]
                return 0
            return max(1, math.ceil(until - now))

    def failure(self, key: str) -> None:
        with self.lock:
            now = self.clock()
            recent = [t for t in self.failures.get(key, []) if now - t < self.window] + [now]
            self.failures[key] = recent
            if len(recent) >= self.max_failures:
                self.locked[key] = now + self.lockout
                self.failures.pop(key, None)
                print(json.dumps({"auth_lockout": True, "seconds": self.lockout}), flush=True)
            if len(self.failures) > self.max_keys:
                for old in sorted(self.failures, key=lambda k: self.failures[k][-1])[: len(self.failures) - self.max_keys]:
                    self.failures.pop(old, None)

    def success(self, key: str) -> None:
        with self.lock:
            self.failures.pop(key, None)


def safe_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    return value


class Reader:
    def __init__(self, data_dir: Path, config_path: Path | None = None):
        self.directory = data_dir.resolve()
        self.path = self.directory / DATABASE_NAME
        self.config_path = (config_path or ASSET_DIR.parent / "config.yaml").resolve()

    def connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=3)
        db.execute("PRAGMA query_only=ON")
        return db

    @staticmethod
    def document(db, name, default=None):
        row = db.execute("SELECT payload FROM documents WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else default

    def status(self):
        if not self.path.exists():
            return {"ready": False, "reason": "Pendiente de importar el estado", "mode": "unverified",
                    "snapshot": {}, "live": {}, "runtime": {}, "storage": {}, "last_backup": {}, "hosted": {},
                    "analysis": build_analysis([], {}, {})}
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            runtime = self.document(db, "runtime_health", {})
            no_hosted = object()
            hosted = self.document(db, "hosted_health", no_hosted)
            has_hosted = hosted is not no_hosted
            pending = db.execute("SELECT count(*) FROM orders WHERE terminal=0").fetchone()[0]
            unknown = db.execute("SELECT count(*) FROM orders WHERE status IN ('unknown','intent')").fetchone()[0]
            deployment = self.document(db, "deployment", {}) or {}
            state = self.document(db, "state", {}) or {}
            snapshot = self.document(db, "snapshot", {}) or {}
            live = self.document(db, "live", {}) or {}
            # All documents and fills share this read transaction. The imported
            # snapshot.analysis is historical; replace it in the response only.
            trades = [json.loads(row[0]) for row in db.execute("SELECT payload FROM trades ORDER BY rowid")]
            analysis = build_analysis(trades, snapshot, state)
            snapshot["analysis"] = analysis["summary"]
            schema_version = db.execute("PRAGMA user_version").fetchone()[0]
            paper = (deployment.get("mode") == "paper" and bool(deployment.get("imported_at_utc"))
                     and bool(state.get("sleeves"))
                     and all(s.get("mode") == "paper" for s in state["sleeves"].values())
                     and all(doc.get("mode") == "paper" and all(
                         s.get("mode", "paper") == "paper" for s in doc.get("sleeves", {}).values())
                         for doc in (snapshot, live)))
            okay, reason = readiness(runtime, (self.directory / "worker.enabled").is_file())
            if has_hosted:
                hosted = hosted if isinstance(hosted, dict) else {}
                supervisor, worker = hosted.get("status"), hosted.get("worker_status")
                if supervisor != "running" or worker != "running":
                    okay = False
                    if "error" in (supervisor, worker):
                        reason = "Supervisor o ejecutor alojado con error; ejecución bloqueada"
                    elif "stopped" in (supervisor, worker):
                        reason = "Supervisor o ejecutor alojado detenido; ejecución bloqueada"
                    elif "paused" in (supervisor, worker):
                        reason = "Ejecutor alojado pausado"
                    else:
                        reason = "Estado del ejecutor alojado no verificado; ejecución bloqueada"
                if hosted.get("backup_status") == "error":
                    okay, reason = False, "Error de backup alojado; respaldo no verificado"
            if pending:
                okay, reason = False, "Órdenes pendientes de conciliación"
            if unknown:
                okay, reason = False, "Órdenes con resultado desconocido; conciliación requerida"
            if not paper or schema_version != 1:
                okay, reason = False, "Modo paper o versión de datos no verificados; ejecución bloqueada"
            return {"ready": okay, "reason": reason, "mode": "paper" if paper else "unverified", "runtime": runtime,
                    "snapshot": snapshot, "live": live, "hosted": hosted if has_hosted else {}, "analysis": analysis,
                    "storage": {"pending_orders": pending, "unknown_orders": unknown,
                                "schema_version": schema_version},
                    "last_backup": self.document(db, "last_backup", {}),
                    "deployment": deployment}

    def rows(self, table: str, limit: int):
        if table not in {"orders", "trades", "equity", "live_equity", "events"}:
            raise ValueError("Recurso desconocido")
        if not self.path.exists():
            return []
        with closing(self.connect()) as db:
            if table == "events":
                return [{"kind": row[0], "created_at": row[1], "payload": json.loads(row[2])}
                        for row in db.execute("SELECT kind,created_at,payload FROM events ORDER BY id DESC LIMIT ?", (limit,))]
            return [json.loads(row[0]) for row in db.execute(
                f"SELECT payload FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,))]

    def performance(self):
        # Read configuration directly: importing bot.load_config would load .env.
        config = yaml.safe_load(self.config_path.read_text())
        if not isinstance(config, dict) or not isinstance(config.get("sleeves"), dict):
            raise ValueError("Configuración de capital no disponible")
        if not self.path.exists():
            return build_performance({}, {}, {}, [], config)
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            state = self.document(db, "state", {})
            snapshot = self.document(db, "snapshot", {})
            live = self.document(db, "live", {})
            rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM equity ORDER BY rowid")]
        return build_performance(state, snapshot, live, rows, config)

    def execution_quality(self):
        if not self.path.exists():
            return build_execution_quality([])
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            trades = [json.loads(row[0]) for row in db.execute("SELECT payload FROM trades ORDER BY rowid")]
        return build_execution_quality(trades)

    def evidence(self):
        from .evidence import build_summary
        if not self.path.exists():
            return build_summary()
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            return build_summary(db)

    def attribution(self, end: str | None = None):
        """Mercado, estrategia y costos (semana, 28 días, desde el primer cierre): misma fórmula que la revisión."""
        from .attribution import windows
        if not self.path.exists():
            return {"error": "Sin datos operativos"}
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            equity = [json.loads(row[0]) for row in db.execute("SELECT payload FROM equity ORDER BY rowid")]
            trades = [json.loads(row[0]) for row in db.execute("SELECT payload FROM trades ORDER BY rowid")]
        try:
            fx = (self.performance().get("fx") or {}).get("rate")
        except (ValueError, yaml.YAMLError):
            fx = None
        return windows(equity, trades, end=end, fx=fx)

    def latest_backup(self, backup_dir: Path | None) -> dict:
        """Solo el último respaldo verificado que registró el supervisor; nunca rutas arbitrarias."""
        if backup_dir is None or not self.path.exists():
            raise FileNotFoundError("Respaldo no configurado")
        with closing(self.connect()) as db:
            last = self.document(db, "last_backup", {}) or {}
        name = str(last.get("file", ""))
        if not BACKUP_NAME.fullmatch(name):
            raise FileNotFoundError("Sin respaldo verificado")
        directory = Path(backup_dir).resolve()
        data, manifest = directory / name, directory / (name + ".manifest.json")
        if data.is_symlink() or manifest.is_symlink() or not data.is_file() or not manifest.is_file():
            raise FileNotFoundError("Respaldo ausente")
        raw = manifest.read_bytes()
        meta = json.loads(raw)
        if meta.get("file") != name or meta.get("bytes") != data.stat().st_size:
            raise FileNotFoundError("El respaldo no coincide con su manifiesto")
        return {"file": name, "bytes": meta["bytes"], "sha256": meta.get("sha256"),
                "created_at_utc": meta.get("created_at_utc"), "schema_version": meta.get("schema_version"),
                "manifest_file": manifest.name, "manifest_bytes": len(raw),
                "manifest_sha256": hashlib.sha256(raw).hexdigest(), "path": {"db": data, "manifest": manifest}}


def research_status(root: Path) -> dict:
    """Backlog (fuente única: research/backlog.yaml) y semáforo de «ganadora» para la pestaña Investigación."""
    out = {"backlog": None, "semaforo": None, "errors": []}
    try:
        from .backlog import load, summary
        out["backlog"] = summary(load(Path(root) / "backlog.yaml"))
    except (OSError, ValueError, KeyError, yaml.YAMLError, ImportError) as exc:
        out["errors"].append(f"backlog: {type(exc).__name__}")
    try:
        out["semaforo"] = _yaml_file(Path(root) / "semaforo.yaml")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        out["errors"].append(f"semaforo: {type(exc).__name__}")
    return out


def comparison_status(paper_dir: Path | None, research_dir: Path | None) -> dict:
    """Read dedicated evidence; never choose a winner or run a strategy."""
    result = {"paper": {"status": "not_configured"}, "research": {"status": "not_configured"},
              "live_authorized": False}
    if paper_dir is not None:
        from .paper_comparison import status
        result["paper"] = status(paper_dir)
    if research_dir is not None:
        directory = Path(research_dir).resolve()
        manifest_path, report_path = directory / "manifest.json", directory / "comparison.json"
        if manifest_path.is_symlink() or report_path.is_symlink():
            raise ValueError("Los resultados no pueden ser enlaces simbólicos")
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("status") != "completed":
            result["research"] = {"status": manifest.get("status", "unverified"),
                                  "run_id": manifest.get("run_id")}
        else:
            raw = report_path.read_bytes()
            expected = next((item["sha256"] for item in manifest.get("artifacts", [])
                             if item["file"] == "comparison.json"), None)
            report = json.loads(raw)
            if (hashlib.sha256(raw).hexdigest() != expected
                    or report.get("run_id") != manifest.get("run_id")
                    or report.get("experiment_id") != manifest.get("experiment_id")
                    or report.get("experiment_id") not in {"aggressive-v1", "aggressive-v2"}
                    or report.get("mode") != "paper"
                    or report.get("live_authorized") is not False):
                raise ValueError("La comparación no conserva su identidad e integridad")
            result["research"] = {"status": "completed", "report": report}
    return result


def _yaml_file(path: Path):
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path.name)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def make_server(data_dir: Path, host="127.0.0.1", port=8080, *, comparison_dir: Path | None = None,
                research_dir: Path | None = None, config_path: Path | None = None,
                require_auth: bool = False, backup_dir: Path | None = None,
                archive_dir: Path | None = None, research_root: Path | None = None,
                throttle: AuthThrottle | None = None):
    reader = Reader(data_dir, config_path)
    archive_dir = Path(archive_dir or ROOT_DIR / "archive" / "arena-v1")
    research_root = Path(research_root or ROOT_DIR / "research")
    throttle = throttle or AuthThrottle()
    auth_digest = None
    if require_auth:
        user = os.environ.get("TRADING_DASHBOARD_USER", "")
        password = os.environ.get("TRADING_DASHBOARD_PASSWORD", "")
        if user and password and ":" not in user:
            try:
                auth_digest = hashlib.sha256(f"{user}:{password}".encode("utf-8")).digest()
            except UnicodeError:
                pass  # Invalid environment encoding must fail closed without logging it.

    class Handler(BaseHTTPRequestHandler):
        server_version = "TradingLab"

        def log_message(self, *_):
            pass

        def parse_request(self):
            if not super().parse_request():
                return False
            # Enforce this before dispatch, including unknown paths and HTTP methods.
            public_health = self.command in {"GET", "HEAD"} and self.path.split("?", 1)[0] == "/healthz"
            if not require_auth or public_health:
                return True
            if auth_digest is None:
                self.send(503, {"error": "Servicio temporalmente no disponible"})
                return False
            client = self.client_key()
            wait = throttle.retry_after(client)
            if wait:
                self.send(429, {"error": "Demasiados intentos fallidos; espera e intenta de nuevo"},
                          headers={"Retry-After": str(wait)})
                return False
            headers = self.headers.get_all("Authorization", [])
            supplied = None
            if len(headers) == 1:
                parts = headers[0].split()
                if len(parts) == 2 and parts[0].lower() == "basic":
                    try:
                        supplied = base64.b64decode(parts[1], validate=True)
                    except (binascii.Error, ValueError):
                        pass
            # Fixed-size byte digests support Unicode without disclosing which field failed.
            candidate = hashlib.sha256(supplied if supplied is not None else b"").digest()
            if hmac.compare_digest(candidate, auth_digest) and supplied is not None:
                throttle.success(client)
                return True
            if headers:  # un navegador sin credenciales todavía no es un intento fallido
                throttle.failure(client)
            self.send(401, {"error": "Autenticación requerida"})
            return False

        def client_key(self):
            # Railway agrega la IP real del cliente al final de X-Forwarded-For; lo que manda el cliente queda antes.
            forwarded = [part.strip() for part in self.headers.get("X-Forwarded-For", "").split(",") if part.strip()]
            return forwarded[-1] if forwarded else self.client_address[0]

        def send(self, status, payload, content_type="application/json; charset=utf-8", headers=None):
            body = payload if isinstance(payload, bytes) else json.dumps(safe_json(payload), ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if status == 401:
                self.send_header("WWW-Authenticate", 'Basic realm="Trading Lab", charset="UTF-8"')
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            try:
                if url.path in ASSETS:
                    filename, mime = ASSETS[url.path]
                    return self.send(200, (ASSET_DIR / filename).read_bytes(), mime)
                if url.path == "/healthz":
                    return self.send(200, {"status": "alive", "read_only": True})
                if url.path in {"/readyz", "/api/status"}:
                    status = reader.status()
                    return self.send(200 if url.path == "/api/status" or status["ready"] else 503, status)
                if url.path == "/api/performance":
                    try:
                        return self.send(200, reader.performance())
                    except (ValueError, yaml.YAMLError):
                        return self.send(503, {"error": "Ganancias no disponibles: configuración o datos no válidos"})
                if url.path == "/api/execution-quality":
                    return self.send(200, reader.execution_quality())
                if url.path == "/api/evidence":
                    return self.send(200, reader.evidence())
                if url.path == "/api/comparison":
                    try:
                        return self.send(200, comparison_status(comparison_dir, research_dir))
                    except (ValueError, OSError, sqlite3.Error):
                        return self.send(503, {"error": "Comparación no disponible o integridad no verificada"})
                if url.path == "/api/attribution":
                    end = parse_qs(url.query).get("end", [None])[0]
                    if end is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
                        return self.send(400, {"error": "end debe ser AAAA-MM-DD"})
                    return self.send(200, reader.attribution(end))
                if url.path == "/api/research":
                    return self.send(200, research_status(research_root))
                if url.path == "/api/candidates":
                    try:
                        from .lanes import status as lanes_status
                        return self.send(200, lanes_status(reader.directory.parent / "lanes",
                                                           registry_path=research_root / "carriles.yaml"))
                    except (OSError, ValueError, yaml.YAMLError):
                        return self.send(503, {"error": "Registro de carriles no disponible"})
                if url.path in {"/api/arena-archive", "/api/arena-archive/fills"}:
                    try:
                        from .arena_archive import fills, load
                        return self.send(200, load(archive_dir) if url.path == "/api/arena-archive"
                                         else {"items": fills(archive_dir)})
                    except (OSError, ValueError, KeyError):
                        return self.send(503, {"error": "Archivo de la arena no disponible"})
                if url.path in {"/api/backups/latest", "/api/backups/part"}:
                    return self.backup(url)
                if url.path.startswith("/api/"):
                    try:
                        limit = int(parse_qs(url.query).get("limit", ["100"])[0])
                        if not 1 <= limit <= 500:
                            raise ValueError
                    except (ValueError, IndexError):
                        return self.send(400, {"error": "limit debe estar entre 1 y 500"})
                    return self.send(200, {"items": reader.rows(url.path.removeprefix("/api/"), limit)})
                self.send(404, {"error": "No encontrado"})
            except ValueError:
                self.send(404, {"error": "Recurso desconocido"})
            except (sqlite3.Error, OSError):
                self.send(503, {"error": "Datos operativos temporalmente no disponibles"})

        def backup(self, url):
            try:
                latest = reader.latest_backup(backup_dir)
            except (FileNotFoundError, ValueError, OSError, sqlite3.Error):
                return self.send(404, {"error": "Sin respaldo verificado disponible"})
            paths = latest.pop("path")
            if url.path == "/api/backups/latest":
                return self.send(200, latest)
            query = parse_qs(url.query)
            try:
                name, kind = query["file"][0], query.get("kind", ["db"])[0]
                offset, length = int(query["offset"][0]), int(query["length"][0])
            except (KeyError, IndexError, ValueError):
                return self.send(400, {"error": "file, offset y length obligatorios"})
            if name != latest["file"] or kind not in paths:
                return self.send(409, {"error": "Ese ya no es el último respaldo; vuelve a pedir /api/backups/latest"})
            size = latest["bytes"] if kind == "db" else latest["manifest_bytes"]
            if offset < 0 or not 0 < length <= MAX_PART or offset + length > size:
                return self.send(416, {"error": "Tramo inválido"})
            with paths[kind].open("rb") as stream:
                stream.seek(offset)
                data = stream.read(length)
            if len(data) != length:
                return self.send(416, {"error": "Lectura incompleta"})
            return self.send(200, data, "application/octet-stream", headers={
                "X-Part-Sha256": hashlib.sha256(data).hexdigest(), "X-Part-Offset": str(offset),
                "X-Part-Length": str(length)})

        def do_POST(self):
            self.send(405, {"error": "Este panel es exclusivamente de lectura"})

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST
        do_HEAD = do_GET

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--config", type=Path, help="YAML de capital objetivo; por defecto config.yaml del proyecto")
    parser.add_argument("--require-auth", action="store_true", help="Requerir HTTP Basic; credenciales TRADING_DASHBOARD_USER/PASSWORD")
    parser.add_argument("--comparison-dir", type=Path, help="SQLite paper experimental, lectura exclusiva")
    parser.add_argument("--research-dir", type=Path, help="corrida histórica congelada para mostrar sus resultados")
    args = parser.parse_args(argv)
    with make_server(args.data_dir, args.host, args.port, comparison_dir=args.comparison_dir,
                     research_dir=args.research_dir, config_path=args.config, require_auth=args.require_auth) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
