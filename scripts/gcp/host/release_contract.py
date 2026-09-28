#!/usr/bin/env python3
"""Read-only contracts for the operational paper release; no cloud access."""
import argparse
import json
import math
from pathlib import Path
import re
import sys

PROFILE = "operational-paper"
IMAGE_PATTERN = r"[a-z0-9-]+-docker\.pkg\.dev/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9./_-]+@sha256:[a-f0-9]{64}"
WORKER_COMMAND = ["python", "-m", "lab.runtime", "--config", "/app/config.yaml", "--data-dir", "/var/lib/trading-lab", "--interval", "300"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_reference(image, sha):
    require(re.fullmatch(IMAGE_PATTERN, image), "Se requiere una imagen de Artifact Registry por digest")
    require(re.fullmatch(r"[a-f0-9]{40}", sha), "Se requiere SHA completo")


def _image_config(config, sha):
    require(isinstance(config, dict), "Config de imagen inválida")
    require(config.get("User") == "10001:10001", "UID/GID de imagen no aprobado")
    require(config.get("WorkingDir") == "/app", "WorkingDir de imagen no aprobado")
    require(config.get("Entrypoint") in (None, []), "La imagen no puede sustituir el comando mediante ENTRYPOINT")
    labels = config.get("Labels") or {}
    require(isinstance(labels, dict), "Labels de imagen inválidos")
    require(labels.get("org.opencontainers.image.revision") == sha, "SHA de imagen distinto")
    require(labels.get("org.tradinglab.profile") == PROFILE, "Se requiere perfil operational-paper")
    env = {}
    for value in config.get("Env") or []:
        require(isinstance(value, str) and "=" in value, "Entorno de imagen inválido")
        name, content = value.split("=", 1)
        require(name not in env, "Entorno de imagen ambiguo")
        require(not re.search(r"SECRET|TOKEN|PASSWORD|API_KEY|KEY_ID|CREDENTIAL", name, re.I), "La imagen contiene una variable de credenciales")
        require(name != "CONFIRMO_DINERO_REAL", "La imagen contiene autorización de dinero real")
        env[name] = content
    require(env.get("TRADING_LAB_BUILD_ID") == sha, "Build ID de imagen distinto")
    require(env.get("PYTHONDONTWRITEBYTECODE") == "1", "La imagen debe impedir bytecode mutable")


def validate_image(document, sha):
    require(isinstance(document, list) and len(document) == 1, "Inspección de imagen ambigua")
    image = document[0]
    require(isinstance(image, dict), "Inspección de imagen inválida")
    require(image.get("Os") == "linux" and image.get("Architecture") == "amd64", "Se requiere Linux AMD64")
    _image_config(image.get("Config"), sha)
    require(image["Config"].get("Cmd") == WORKER_COMMAND, "Comando base distinto al worker operativo")


def validate_api(document, image, sha):
    require(isinstance(document, list) and len(document) == 1, "Contenedor API ambiguo")
    container = document[0]
    require(isinstance(container, dict), "Inspección de contenedor inválida")
    require(container.get("State", {}).get("Running") is True, "API no está corriendo")
    _image_config(container.get("Config"), sha)
    require(container["Config"].get("Image") == image, "API está usando otro digest")
    require(container.get("HostConfig", {}).get("ReadonlyRootfs") is True, "Raíz API debe ser de solo lectura")
    bindings = container.get("HostConfig", {}).get("PortBindings", {})
    require(bindings.get("8080/tcp") == [{"HostIp": "127.0.0.1", "HostPort": "8080"}], "API debe escuchar sólo en localhost")


def validate_config(config):
    require(isinstance(config, dict) and config.get("mode") == "paper", "Se requiere configuración paper")
    sleeves = config.get("sleeves")
    require(isinstance(sleeves, dict), "Faltan bloques operativos")
    require(set(sleeves) <= {"crypto", "stocks", "multi"}, "Bloque fuera del perfil operativo")
    for name in ("crypto", "stocks"):
        block = sleeves.get(name)
        require(isinstance(block, dict) and block.get("enabled") is True, f"El bloque {name} debe estar habilitado")
        capital = block.get("capital")
        require(type(capital) in (int, float) and math.isfinite(capital) and capital > 0, f"Capital {name} inválido")
    crypto, stocks = sleeves["crypto"], sleeves["stocks"]
    require(crypto.get("strategy") == "tactical", "Estrategia crypto no aprobada")
    params = crypto.get("params", {})
    require(isinstance(params, dict), "Parámetros crypto inválidos")
    require(type(params.get("top_k")) is int and params["top_k"] == 5, "Se requiere top_k crypto 5")
    for name in ("vol_target", "max_weight"):
        value = params.get(name)
        require(type(value) in (int, float) and math.isfinite(value) and math.isclose(value, 0.4, rel_tol=0, abs_tol=1e-12), f"Parámetro crypto {name} distinto al perfil")
    require(stocks.get("strategy") == "passive" and stocks.get("mix") == {"SPY": 0.6, "IEF": 0.4}, "Se requiere mezcla pasiva SPY 60% / IEF 40%")
    multi = sleeves.get("multi", {})
    require(isinstance(multi, dict) and multi.get("enabled", False) is False, "El bloque multi debe permanecer apagado")
    realtime = config.get("realtime", {})
    require(isinstance(realtime, dict) and realtime.get("enabled") is True and realtime.get("action") == "observe", "Tiempo real debe limitarse a observar")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("image", "api", "config"))
    parser.add_argument("target")
    parser.add_argument("--image")
    parser.add_argument("--runtime-imports", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "config":
            import yaml
            try:
                config = yaml.safe_load(Path(args.target).read_text())
            except yaml.YAMLError:
                raise ValueError("YAML de configuración inválido") from None
            validate_config(config)
            if args.runtime_imports:
                for module in ("lab.runtime", "lab.service", "lab.ops"):
                    __import__(module)
                from lab.runtime import validate_config as validate_runtime_config
                validate_runtime_config(config)
        else:
            require(re.fullmatch(r"[a-f0-9]{40}", args.target), "SHA inválido")
            document = json.load(sys.stdin)
            if args.action == "image":
                validate_image(document, args.target)
            else:
                validate_reference(args.image or "", args.target)
                validate_api(document, args.image, args.target)
        print(json.dumps({"status": "passed", "profile": PROFILE, "check": args.action}))
        return 0
    except (ValueError, OSError, TypeError, KeyError, ImportError) as exc:
        print(f"Release bloqueada: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
