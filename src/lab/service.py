"""Read-only operational API. Bind locally or expose only through an IAP tunnel."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlparse

from .runtime import DATABASE_NAME, readiness

ASSET_DIR = Path(__file__).resolve().parents[2] / "dashboard"
ASSETS = {"/": ("operations.html", "text/html; charset=utf-8"),
          "/operations.js": ("operations.js", "text/javascript; charset=utf-8"),
          "/operations.css": ("operations.css", "text/css; charset=utf-8")}


def safe_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    return value


class Reader:
    def __init__(self, data_dir: Path):
        self.directory = data_dir.resolve()
        self.path = self.directory / DATABASE_NAME

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
                    "snapshot": {}, "live": {}, "runtime": {}, "storage": {}, "last_backup": {}}
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            runtime = self.document(db, "runtime_health", {})
            pending = db.execute("SELECT count(*) FROM orders WHERE terminal=0").fetchone()[0]
            unknown = db.execute("SELECT count(*) FROM orders WHERE status IN ('unknown','intent')").fetchone()[0]
            deployment = self.document(db, "deployment", {}) or {}
            state = self.document(db, "state", {}) or {}
            snapshot = self.document(db, "snapshot", {}) or {}
            live = self.document(db, "live", {}) or {}
            schema_version = db.execute("PRAGMA user_version").fetchone()[0]
            paper = (deployment.get("mode") == "paper" and bool(deployment.get("imported_at_utc"))
                     and bool(state.get("sleeves"))
                     and all(s.get("mode") == "paper" for s in state["sleeves"].values())
                     and all(doc.get("mode") == "paper" and all(
                         s.get("mode", "paper") == "paper" for s in doc.get("sleeves", {}).values())
                         for doc in (snapshot, live)))
            okay, reason = readiness(runtime, (self.directory / "worker.enabled").is_file())
            if pending:
                okay, reason = False, "Órdenes pendientes de conciliación"
            if unknown:
                okay, reason = False, "Órdenes con resultado desconocido; conciliación requerida"
            if not paper or schema_version != 1:
                okay, reason = False, "Modo paper o versión de datos no verificados; ejecución bloqueada"
            return {"ready": okay, "reason": reason, "mode": "paper" if paper else "unverified", "runtime": runtime,
                    "snapshot": snapshot, "live": live,
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


def make_server(data_dir: Path, host="127.0.0.1", port=8080, *, comparison_dir: Path | None = None,
                research_dir: Path | None = None):
    reader = Reader(data_dir)

    class Handler(BaseHTTPRequestHandler):
        server_version = "TradingLab"

        def log_message(self, *_):
            pass

        def send(self, status, payload, content_type="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(safe_json(payload), ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
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
                if url.path == "/api/comparison":
                    try:
                        return self.send(200, comparison_status(comparison_dir, research_dir))
                    except (ValueError, OSError, sqlite3.Error):
                        return self.send(503, {"error": "Comparación no disponible o integridad no verificada"})
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

        def do_POST(self):
            self.send(405, {"error": "Este panel es exclusivamente de lectura"})

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--comparison-dir", type=Path, help="SQLite paper experimental, lectura exclusiva")
    parser.add_argument("--research-dir", type=Path, help="corrida histórica congelada para mostrar sus resultados")
    args = parser.parse_args(argv)
    with make_server(args.data_dir, args.host, args.port, comparison_dir=args.comparison_dir,
                     research_dir=args.research_dir) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
