"""Arena UI: loopback locally, authenticated HTTPS behind Railway."""
import argparse
import base64
import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .arena import ROOT, control, initialize, status

ASSETS = ROOT / 'dashboard/arena'


def make_server(directory, port=8874, *, public_domain=None, username=None, password=None):
    hosted = public_domain is not None
    if hosted:
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.[a-z]{2,}', public_domain) or not username or not password:
            raise ValueError('Dominio y credenciales del panel obligatorios')
        authorization = 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()
    else:
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
            if code == 401:
                self.send_header('WWW-Authenticate', 'Basic realm="Trading Lab Arena", charset="UTF-8"')
            if hosted:
                self.send_header('Strict-Transport-Security', 'max-age=31536000')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def valid_host(self):
            if hosted:
                return self.headers.get('Host') == public_domain
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def authenticated(self):
            if hosted and not hmac.compare_digest(self.headers.get('Authorization', '').encode(), authorization.encode()):
                self.send(401, {'error': 'Acceso protegido'})
                return False
            return True

        def do_GET(self):
            path = urlparse(self.path).path
            # Railway's deployment probe does not carry credentials or public Host.
            if path == '/healthz':
                self.send(200, {'status': 'ok', 'mode': 'paper'})
                return
            if not self.valid_host():
                self.send(403, {'error': 'Host no permitido'})
                return
            if not self.authenticated():
                return
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
                elif path == '/readyz':
                    data = status(directory)
                    ready = not data['stale'] and data['health']['status'] == 'ok'
                    self.send(200 if ready else 503, {'ready': ready, 'mode': 'paper'})
                else:
                    self.send(404, {'error': 'No encontrado'})
            except Exception:
                self.send(503, {'error': 'No se pudo leer la arena; conserva la última valoración'})

        def do_POST(self):
            origin = self.headers.get('Origin', '')
            origins = (f'https://{public_domain}',) if hosted else (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
            if (not self.valid_host() or origin not in origins
                    or self.headers.get('Content-Type') != 'application/json'):
                self.send(403, {'error': 'Origen no permitido'})
                return
            if not self.authenticated():
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
    return ThreadingHTTPServer(('0.0.0.0' if hosted else '127.0.0.1', port), Handler)


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
