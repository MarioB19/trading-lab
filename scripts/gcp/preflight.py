"""Check local release prerequisites; optional image inspection uses local Docker only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent / "host"))
from release_contract import PROFILE, validate_config, validate_image, validate_reference


def run(command):
    return subprocess.check_output(command, cwd=ROOT, text=True, stderr=subprocess.PIPE, timeout=15).strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", help="Full reviewed Git SHA")
    parser.add_argument("--image", help="Optional local Artifact Registry image URI pinned by digest")
    parser.add_argument("--require-tools", action="store_true", help="Also fail if docker, terraform or gcloud are absent")
    args = parser.parse_args(argv)
    result = {"profile": PROFILE, "cloud_accessed": False, "image_verified": False,
              "connection_attempted": False, "errors": []}
    errors = result["errors"]
    if args.expected_sha and not re.fullmatch(r"[a-f0-9]{40}", args.expected_sha):
        errors.append("expected-sha requiere 40 caracteres hexadecimales")
    if args.image and not args.expected_sha:
        errors.append("Inspeccionar imagen requiere expected-sha revisado")
    try:
        result["source_sha"] = run(["git", "rev-parse", "HEAD"])
        result["working_tree_clean"] = not run(["git", "status", "--porcelain", "--untracked-files=all"])
        if not result["working_tree_clean"]:
            errors.append("El checkout debe estar limpio antes de entregar")
        if args.expected_sha and args.expected_sha != result["source_sha"]:
            errors.append("HEAD difiere del SHA revisado")
    except (OSError, subprocess.SubprocessError):
        errors.append("No se pudo comprobar Git localmente")
    try:
        import yaml
        config = ROOT / "config.yaml"
        validate_config(yaml.safe_load(config.read_text()))
        result["config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
        result["operational_config_valid"] = True
    except ImportError:
        errors.append("Falta PyYAML; usar el entorno Python del proyecto")
    except Exception:
        # Do not echo YAML lines or arbitrary configuration values.
        errors.append("Configuración fuera del perfil: paper, crypto top5/0.40/0.40, SPY60/IEF40, multi apagado, realtime observe")
    result["tools"] = {name: shutil.which(os.environ.get("TERRAFORM_BIN", name) if name == "terraform" else name) is not None
                       for name in ("docker", "terraform", "gcloud", "gh")}
    if args.require_tools:
        missing = [name for name in ("docker", "terraform", "gcloud") if not result["tools"][name]]
        if missing:
            errors.append("Faltan herramientas locales: " + ", ".join(missing))
    if args.image and args.expected_sha and not errors:
        try:
            validate_reference(args.image, args.expected_sha)
            endpoint = run(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
            endpoints = [endpoint] + ([os.environ["DOCKER_HOST"]] if os.environ.get("DOCKER_HOST") else [])
            if not all(value.startswith(("unix://", "npipe://")) for value in endpoints):
                raise ValueError("La inspección requiere Docker local")
            document = json.loads(run(["docker", "image", "inspect", args.image]))
            validate_image(document, args.expected_sha)
            result["image_verified"] = True
        except (ValueError, OSError, TypeError, KeyError, subprocess.SubprocessError) as exc:
            errors.append(str(exc) if isinstance(exc, ValueError) else "No se pudo verificar la imagen local; revisar daemon e imagen")
    result["status"] = "blocked" if errors else "local_checks_passed"
    result["connection_requires"] = ["cuenta y project ID elegidos por Brandon", "billing y créditos vigentes verificados por el operador",
                                       "plan Terraform revisado", "SHA/digest probados", "corte del escritor legacy antes de activar"]
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
