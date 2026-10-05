"""Loopback-only arena UI and narrow pause/resume API, separate from Railway."""
import argparse
import csv
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .arena import ROOT, control, initialize, status

ASSETS = ROOT / 'dashboard/arena'


def make_server(directory, port=8874):
    initialize(directory)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, code, body, content_type='application/json; charset=utf-8'):
            raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if isinstance(body, (dict, list)) else body
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def valid_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.valid_host():
                self.send(403, {'error': 'Host no permitido'})
                return
            path = urlparse(self.path).path
            try:
                if path == '/api/arena':
                    self.send(200, status(directory))
                elif path == '/api/export':
                    data = status(directory)
                    self.send(200, data)
                elif path in ('/', '/arena.css', '/arena.js'):
                    filename = 'index.html' if path == '/' else path[1:]
                    mime = 'text/html' if path == '/' else 'text/css' if path.endswith('.css') else 'text/javascript'
                    self.send(200, (ASSETS / filename).read_bytes(), mime + '; charset=utf-8')
                elif path == '/healthz':
                    self.send(200, {'status': 'ok', 'mode': 'paper'})
                else:
                    self.send(404, {'error': 'No encontrado'})
            except Exception:
                self.send(503, {'error': 'No se pudo leer la arena; conserva la última valoración'})

        def do_POST(self):
            origin = self.headers.get('Origin', '')
            if (not self.valid_host() or origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
                    or self.headers.get('Content-Type') != 'application/json'):
                self.send(403, {'error': 'Solo solicitudes del panel local'})
                return
            if self.path != '/api/control':
                self.send(404, {'error': 'No encontrado'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024:
                    raise ValueError('Solicitud inválida')
                payload = json.loads(self.rfile.read(size))
                control(directory, payload['strategy'], payload['action'])
                self.send(200, status(directory))
            except (ValueError, KeyError, TypeError):
                self.send(400, {'error': 'Acción inválida o cartera detenida por riesgo'})
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'runtime-data/arena-paper')
    parser.add_argument('--port', type=int, default=8874)
    args = parser.parse_args()
    server = make_server(args.directory, args.port)
    print(f'Arena local: http://127.0.0.1:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
