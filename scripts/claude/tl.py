#!/usr/bin/env python3
"""Herramienta de Claude para leer y operar Trading Lab en Railway (solo simulado).

Solo usa la biblioteca estándar, así que funciona con Python 3.10+ en la Mac,
en la VM del equipo o en la nube, sin instalar el proyecto.

Credenciales (nunca en Git). Se leen, en este orden, de:
  1. variables de entorno ya definidas;
  2. el archivo indicado en TL_ENV;
  3. <vault>/Projects/Trading Lab/.secretos/claude.env (junto al repo);
  4. ~/.config/trading-lab/claude.env.

Claves:
  TL_PANEL_USER, TL_PANEL_PASSWORD   usuario y contraseña del panel (mismos en piloto y arena)
  RAILWAY_API_TOKEN                  token de cuenta Railway (railway.com/account/tokens)

Comandos:
  tl.py setup                     configura credenciales (pide el token de Railway oculto y saca el
                                  usuario y la contraseña del panel de Railway, sin mostrarlos)
  tl.py check                     qué credenciales hay y si los servicios responden
  tl.py snapshot [--out DIR]      guarda JSON crudo del piloto (incluye atribución, investigación y carriles)
  tl.py services                  servicios del proyecto Railway y su último deployment
  tl.py stop SERVICE              detiene el deployment activo del servicio (el volumen se conserva)
                                  (la arena se detuvo así el 25-oct-2026; ver DEC-031 y DEC-032)
  tl.py redeploy SERVICE          vuelve a desplegar la última imagen del servicio
  tl.py up SERVICE BUNDLE         sube un paquete (lo mismo que `railway up --path-as-root`, sin CLI):
                                  trading-lab solo acepta perfil operational-paper y trading-arena
                                  solo el mantenimiento de solo lectura
  tl.py deployment ID [--logs N]  estado de un deployment y sus últimas líneas de log
  tl.py domains                   dominios del piloto y los registros DNS que pide Railway
  tl.py domain-add DOMINIO        agrega un dominio propio al piloto y muestra el CNAME y el TXT
  tl.py gql 'query { me { email } }'   consulta GraphQL libre (solo para diagnóstico)

Nada aquí cambia `mode`, secretos ni variables: el dinero real sigue siendo manual de Brandon.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import getpass
import pathlib
import ssl
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
# Panel único (DEC-032): primero el dominio propio; mientras su DNS no exista (o si falla), el de Railway.
# Cuando el dominio de Railway se quite, basta con borrar la segunda línea.
PILOT_URLS = ("https://tradinglab.inovaris.online",
              "https://trading-lab-production-a56b.up.railway.app")
RAILWAY_GQL = "https://backboard.railway.com/graphql/v2"
RAILWAY_PROJECT = "24021d85-bbad-4f2c-850c-e1230822e7b0"
RAILWAY_ENV = "4774e5bf-c72b-402d-ac72-f88e815e5976"
PILOT_ENDPOINTS = ("status", "performance", "execution-quality", "trades?limit=500",
                   "equity?limit=500", "events?limit=100", "attribution", "research", "candidates",
                   "backups/latest")
_PILOT_URL: str | None = None


def load_env() -> dict:
    env: dict[str, str] = {}
    candidates = [os.environ.get("TL_ENV"), REPO.parent / ".secretos" / "claude.env",
                  pathlib.Path.home() / ".config" / "trading-lab" / "claude.env"]
    for c in candidates:
        if c and pathlib.Path(c).is_file():
            for line in pathlib.Path(c).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
    for k in ("TL_PANEL_USER", "TL_PANEL_PASSWORD", "RAILWAY_API_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _ssl_context():
    # En la Mac, el Python de python.org no trae certificados del sistema: usa certifi si existe.
    # En la nube o la VM se respeta SSL_CERT_FILE (proxy con su propia CA).
    if sys.platform == "darwin" and not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
    return ssl.create_default_context()


def _request(url: str, *, headers: dict | None = None, data: bytes | None = None, timeout: int = 60):
    headers = {"User-Agent": "trading-lab-claude/1.0", **(headers or {})}  # Cloudflare bloquea Python-urllib
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""  # servicio apagado o sin red


def pilot_url() -> str:
    """El primer dominio del panel que responde /healthz 200 (TL_PILOT_URL lo fija a mano)."""
    global _PILOT_URL
    if os.environ.get("TL_PILOT_URL"):
        return os.environ["TL_PILOT_URL"].rstrip("/")
    if _PILOT_URL is None:
        for base in PILOT_URLS:
            if _request(f"{base}/healthz", timeout=15)[0] == 200:
                _PILOT_URL = base
                break
        else:
            _PILOT_URL = PILOT_URLS[-1]
    return _PILOT_URL


def server_time() -> dt.datetime:
    """Hora del servidor del piloto (cabecera Date): el reloj de la VM puede estar desfasado."""
    req = urllib.request.Request(f"{pilot_url()}/healthz", headers={"User-Agent": "trading-lab-claude/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as r:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(r.headers["Date"]).astimezone(dt.timezone.utc)
    except Exception:
        return dt.datetime.now(dt.timezone.utc)


def _panel_headers(env: dict) -> dict:
    user, pw = env.get("TL_PANEL_USER"), env.get("TL_PANEL_PASSWORD")
    if not (user and pw):
        sys.exit("Faltan TL_PANEL_USER / TL_PANEL_PASSWORD (ver docstring).")
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def get_json(base: str, path: str, env: dict):
    code, body = _request(f"{base}/api/{path}", headers=_panel_headers(env))
    try:
        payload = json.loads(body or b"null")
    except json.JSONDecodeError:
        payload = {"raw": body[:500].decode(errors="replace")}
    return code, payload


def gql(query: str, variables: dict | None, env: dict) -> dict:
    token = env.get("RAILWAY_API_TOKEN")
    if not token:
        sys.exit("Falta RAILWAY_API_TOKEN (ver docstring).")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    code, raw = _request(RAILWAY_GQL, data=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    out = json.loads(raw or b"{}")
    if code != 200 or out.get("errors"):
        sys.exit(f"Railway respondió {code}: {json.dumps(out.get('errors') or out)[:800]}")
    return out["data"]


def _gql_try(query: str, variables: dict | None, token: str):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    try:
        code, raw = _request(RAILWAY_GQL, data=body, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        out = json.loads(raw or b"{}")
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        return None, f"sin conexión con Railway ({type(e).__name__})"
    if code != 200 or out.get("errors"):
        msg = "; ".join(str(e.get("message", e)) for e in out.get("errors") or []) or f"HTTP {code}"
        return None, msg[:300]
    return out.get("data"), None


PILOT_SERVICE_ID = "769ae901-e962-45e4-8666-11c3351f7249"
ENV_FILE = REPO.parent / ".secretos" / "claude.env"


def cmd_setup() -> None:
    print("Configuración de credenciales de Claude para Trading Lab.")
    print("1) Abre https://railway.com/account/tokens, crea un token (nombre: claude-trading-lab;")
    print("   en «Workspace» deja tu cuenta personal / sin equipo) y cópialo.")
    if sys.platform == "darwin":
        os.system("open https://railway.com/account/tokens >/dev/null 2>&1")
    token = getpass.getpass("2) Pega el token aquí (no se verá) y presiona Enter: ").strip()
    if not token:
        sys.exit("No se pegó ningún token. Vuelve a correr el comando.")
    data, err = _gql_try("query { me { email } }", None, token)
    if err:
        data, err2 = _gql_try("query($id: String!) { project(id: $id) { name } }", {"id": RAILWAY_PROJECT}, token)
        if err2:
            sys.exit(f"Railway rechazó el token: {err} / {err2}. Crea uno nuevo y repite.")
        print("   Token válido para el proyecto", data["project"]["name"])
    else:
        print("   Token válido para la cuenta", data["me"]["email"])
    user = pw = None
    data, err = _gql_try("query($p: String!, $e: String!, $s: String!) { variables(projectId: $p, "
                         "environmentId: $e, serviceId: $s) }",
                         {"p": RAILWAY_PROJECT, "e": RAILWAY_ENV, "s": PILOT_SERVICE_ID}, token)
    if data and isinstance(data.get("variables"), dict):
        user = data["variables"].get("TRADING_DASHBOARD_USER")
        pw = data["variables"].get("TRADING_DASHBOARD_PASSWORD")
    if user and pw:
        print("3) Usuario y contraseña del panel obtenidos de Railway (no se muestran).")
    else:
        print(f"3) No pude leerlos de Railway ({err or 'variables ausentes'}). Escríbelos:")
        user = input("   Usuario del panel [brandon]: ").strip() or "brandon"
        pw = getpass.getpass("   Contraseña del panel (no se verá): ").strip()
    code, _ = _request(f"{pilot_url()}/api/status", headers=_panel_headers(
        {"TL_PANEL_USER": user, "TL_PANEL_PASSWORD": pw}))
    if code != 200:
        sys.exit(f"El panel respondió {code} con ese usuario y contraseña; no guardé nada. Repite.")
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    old = os.umask(0o077)
    try:
        ENV_FILE.write_text("# Credenciales de Claude para Trading Lab. No va a Git ni al chat.\n"
                            f"TL_PANEL_USER={user}\nTL_PANEL_PASSWORD={pw}\nRAILWAY_API_TOKEN={token}\n",
                            encoding="utf-8")
    finally:
        os.umask(old)
    os.chmod(ENV_FILE, 0o600)
    print(f"4) Guardado en {ENV_FILE} (solo tú puedes leerlo). Verificación:")
    cmd_check(load_env())
    print("Listo. Dile a Claude: «ya quedó el archivo».")


def services(env: dict) -> list[dict]:
    q = """query($id: String!) { project(id: $id) { name services { edges { node { id name
      serviceInstances { edges { node { environmentId numReplicas
        latestDeployment { id status createdAt } } } } } } } } }"""
    data = gql(q, {"id": RAILWAY_PROJECT}, env)
    rows = []
    for edge in data["project"]["services"]["edges"]:
        node = edge["node"]
        for inst in node["serviceInstances"]["edges"]:
            i = inst["node"]
            if i["environmentId"] != RAILWAY_ENV:
                continue
            dep = i.get("latestDeployment") or {}
            rows.append({"service": node["name"], "service_id": node["id"], "replicas": i.get("numReplicas"),
                         "deployment_id": dep.get("id"), "status": dep.get("status"),
                         "created_at": dep.get("createdAt")})
    return rows


def find_service(name: str, env: dict) -> dict:
    for row in services(env):
        if row["service"] == name:
            return row
    sys.exit(f"No existe el servicio {name!r} en production.")


def cmd_check(env: dict) -> None:
    print("panel:", "sí" if env.get("TL_PANEL_USER") and env.get("TL_PANEL_PASSWORD") else "NO")
    print("railway token:", "sí" if env.get("RAILWAY_API_TOKEN") else "NO")
    for base in PILOT_URLS:
        code, _ = _request(f"{base}/healthz", timeout=20)
        print(f"{base.split('//')[1]} /healthz -> {code or 'sin respuesta'}")
    print("panel en uso:", pilot_url())
    if env.get("TL_PANEL_USER"):
        code, payload = get_json(pilot_url(), "status", env)
        if isinstance(payload, dict):
            print(f"piloto /api/status -> {code} ready={payload.get('ready')} mode={payload.get('mode')} "
                  f"motivo={payload.get('reason')!r}")
    if env.get("RAILWAY_API_TOKEN"):
        data, err = _gql_try("query($id: String!) { project(id: $id) { name } }",
                             {"id": RAILWAY_PROJECT}, env["RAILWAY_API_TOKEN"])
        print("railway proyecto:", data["project"]["name"] if data else f"ERROR {err}")


def cmd_snapshot(env: dict, out: pathlib.Path | None) -> None:
    stamp = server_time().strftime("%Y%m%dT%H%M%SZ")
    out = out or REPO / "runtime-data" / "claude" / "snapshots"
    out.mkdir(parents=True, exist_ok=True)
    snap: dict = {"taken_at_utc": stamp, "panel": pilot_url(), "pilot": {}}
    for ep in PILOT_ENDPOINTS:
        code, payload = get_json(pilot_url(), ep, env)
        snap["pilot"][ep.split("?")[0]] = {"http": code, "data": payload}
    path = out / f"{stamp}.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [f"pilot/{k}" for k, v in snap["pilot"].items() if v["http"] != 200]
    print(path)
    print("endpoints con error:", ", ".join(bad) if bad else "ninguno")


BUNDLE_PROFILES = {"trading-lab": "operational-paper", "trading-arena": "arena-maintenance-read-only"}


def _tarball(bundle: pathlib.Path) -> bytes:
    """Mismo formato que `railway up --path-as-root`: entradas `./ruta`, sin .git ni node_modules."""
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(bundle.rglob("*")):
            rel = path.relative_to(bundle)
            if path.is_symlink() or any(part in (".git", "node_modules", "__pycache__") for part in rel.parts):
                continue
            tar.add(path, arcname=f"./{rel.as_posix()}", recursive=False)
    return buf.getvalue()


def cmd_up(env: dict, service: str, bundle: pathlib.Path) -> None:
    if service not in BUNDLE_PROFILES:
        sys.exit(f"Servicio sin perfil permitido: {service!r}")
    release = json.loads((bundle / "release.json").read_text(encoding="utf-8"))
    if release.get("profile") != BUNDLE_PROFILES[service]:
        sys.exit(f"{service} solo acepta paquetes {BUNDLE_PROFILES[service]!r}; este es {release.get('profile')!r}.")
    if release.get("source_has_uncommitted_changes") or release.get("dirty"):
        sys.exit("El paquete salió de un checkout con cambios sin commit; no se sube.")
    if not (bundle / "Dockerfile").is_file():
        sys.exit("El paquete no trae Dockerfile en la raíz.")
    row = find_service(service, env)
    body = _tarball(bundle)
    url = (f"https://backboard.railway.com/project/{RAILWAY_PROJECT}/environment/{RAILWAY_ENV}/up"
           f"?serviceId={row['service_id']}")
    code, raw = _request(url, data=body, timeout=150, headers={
        "Authorization": f"Bearer {env['RAILWAY_API_TOKEN']}", "Content-Type": "application/gzip"})
    if code != 200:
        sys.exit(f"Railway rechazó la subida ({code}): {raw[:300].decode(errors='replace')}")
    out = json.loads(raw)
    print(json.dumps({"service": service, "build_id": release.get("build_id"),
                      "source": release.get("source_commit") or release.get("source_head"),
                      "deployment": out.get("deploymentId"), "bytes": len(body)}))


def cmd_deployment(env: dict, deployment_id: str, lines: int) -> None:
    data = gql("query($id: String!) { deployment(id: $id) { id status createdAt staticUrl } }",
               {"id": deployment_id}, env)
    print(json.dumps(data["deployment"]))
    if lines:
        for kind in ("buildLogs", "deploymentLogs"):
            logs = gql(f"query($id: String!, $n: Int) {{ {kind}(deploymentId: $id, limit: $n) {{ timestamp message }} }}",
                       {"id": deployment_id, "n": lines}, env)[kind]
            print(f"--- {kind}")
            for row in logs[-lines:]:
                print(row["timestamp"][11:19], row["message"][:300])


DOMAIN_FIELDS = """domain status { verified certificateStatus
  dnsRecords { hostlabel fqdn recordType requiredValue currentValue status zone purpose } }"""


def cmd_domains(env: dict) -> None:
    q = f"""query($p: String!, $e: String!, $s: String!) {{ domains(projectId: $p, environmentId: $e, serviceId: $s) {{
      serviceDomains {{ domain }} customDomains {{ id {DOMAIN_FIELDS} }} }} }}"""
    data = gql(q, {"p": RAILWAY_PROJECT, "e": RAILWAY_ENV, "s": PILOT_SERVICE_ID}, env)
    print(json.dumps(data["domains"], indent=1, ensure_ascii=False))


def cmd_domain_add(env: dict, domain: str) -> None:
    if domain != "tradinglab.inovaris.online":
        sys.exit("Solo está aprobado tradinglab.inovaris.online (plan del 25-oct, F6).")
    q = f"""mutation($i: CustomDomainCreateInput!) {{ customDomainCreate(input: $i) {{ id {DOMAIN_FIELDS} }} }}"""
    data = gql(q, {"i": {"domain": domain, "projectId": RAILWAY_PROJECT, "environmentId": RAILWAY_ENV,
                         "serviceId": PILOT_SERVICE_ID}}, env)
    print(json.dumps(data["customDomainCreate"], indent=1, ensure_ascii=False))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("check")
    s = sub.add_parser("snapshot")
    s.add_argument("--out", type=pathlib.Path)
    sub.add_parser("services")
    for name in ("stop", "redeploy"):
        sub.add_parser(name).add_argument("service")
    sub.add_parser("gql").add_argument("query")
    u = sub.add_parser("up")
    u.add_argument("service")
    u.add_argument("bundle", type=pathlib.Path)
    sub.add_parser("domains")
    sub.add_parser("domain-add").add_argument("domain")
    d = sub.add_parser("deployment")
    d.add_argument("id")
    d.add_argument("--logs", type=int, default=0)
    a = p.parse_args()
    if a.cmd == "setup":
        cmd_setup()
        return
    env = load_env()
    if a.cmd == "check":
        cmd_check(env)
    elif a.cmd == "snapshot":
        cmd_snapshot(env, a.out)
    elif a.cmd == "services":
        print(json.dumps(services(env), indent=1))
    elif a.cmd == "stop":
        row = find_service(a.service, env)
        if row["service"] == "trading-lab":
            sys.exit("El piloto no se detiene desde aquí: pausa con TRADING_WORKER_ALLOWED (ver RAILWAY_RUNBOOK).")
        ok = gql("mutation($id: String!) { deploymentStop(id: $id) }", {"id": row["deployment_id"]}, env)
        print(json.dumps({"service": row["service"], "deployment": row["deployment_id"], "stopped": ok}))
    elif a.cmd == "redeploy":
        row = find_service(a.service, env)
        ok = gql("mutation($e: String!, $s: String!) { serviceInstanceRedeploy(environmentId: $e, serviceId: $s) }",
                 {"e": RAILWAY_ENV, "s": row["service_id"]}, env)
        print(json.dumps({"service": row["service"], "redeploy": ok}))
    elif a.cmd == "up":
        cmd_up(env, a.service, a.bundle)
    elif a.cmd == "domains":
        cmd_domains(env)
    elif a.cmd == "domain-add":
        cmd_domain_add(env, a.domain)
    elif a.cmd == "deployment":
        cmd_deployment(env, a.id, a.logs)
    elif a.cmd == "gql":
        print(json.dumps(gql(a.query, None, env), indent=1))


if __name__ == "__main__":
    main()
