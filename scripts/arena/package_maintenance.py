#!/usr/bin/env python3
"""Empaqueta la imagen de mantenimiento de la arena desde un checkout limpio.

Solo biblioteca estándar (sirve con Python 3.10 en la VM del equipo). Incluye código,
configuración de la arena y requisitos; excluye datos, `.git`, credenciales e informes.

    python3 scripts/arena/package_maintenance.py runtime-data/railway/arena-mant-<fecha>/bundle
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def _git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def package(destination: Path, *, allow_dirty: bool = False) -> dict:
    commit = _git('rev-parse', 'HEAD')
    dirty = _git('status', '--porcelain', '--untracked-files=all', '--', 'src', 'configs/arena', 'infra/arena',
                 'requirements-runtime.txt')
    if dirty and not allow_dirty:
        raise SystemExit('El checkout tiene cambios o archivos sin commit; no se empaqueta.')
    hosted = (ROOT / 'src/lab/arena_hosted.py').read_text()
    if 'arena_maintenance.enabled()' not in hosted:
        raise SystemExit('arena_hosted.run no despacha al modo mantenimiento; no se empaqueta.')
    destination.mkdir(parents=True, exist_ok=False)
    files = {'Dockerfile': ROOT / 'infra/arena/maintenance.Dockerfile',
             'requirements-runtime.txt': ROOT / 'requirements-runtime.txt'}
    for base in ('src/lab', 'configs/arena'):
        for path in sorted((ROOT / base).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                files[str(path.relative_to(ROOT))] = path
    for name, source in files.items():
        if source.is_symlink():
            raise ValueError('No se empaquetan enlaces')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    docker = destination / 'Dockerfile'
    docker.write_text(docker.read_text().replace('ARG ARENA_SOURCE_COMMIT', 'ARG ARENA_SOURCE_COMMIT=' + commit))
    hashes = {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(destination.rglob('*')) if p.is_file()}
    content = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    release = {'profile': 'arena-maintenance-read-only', 'build_id': 'arena-mant-' + content[:16],
               'source_commit': commit, 'dirty': bool(dirty), 'files': hashes, 'payload_sha256': content}
    (destination / 'release.json').write_text(json.dumps(release, indent=2) + '\n')
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--allow-dirty', action='store_true', help='solo para pruebas locales')
    args = parser.parse_args()
    release = package(args.destination, allow_dirty=args.allow_dirty)
    print(json.dumps({k: v for k, v in release.items() if k != 'files'}, indent=2))
    sys.exit(0)
