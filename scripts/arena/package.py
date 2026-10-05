#!/usr/bin/env python3
"""Package clean, preregistered arena code; exclude runtime data and credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from lab import arena
from lab.arena_hosted import PREREG
from lab.research_attestation import generate_attestation


def package(destination):
    cfg = arena.plan()
    attestation = generate_attestation(ROOT, arena.PLAN_PATH, arena.PREREG_PATH, PREREG, cfg, cfg['variants'])
    destination.mkdir(parents=True, exist_ok=False)
    files = {'Dockerfile': ROOT / 'infra/arena/Dockerfile',
             'requirements-runtime.txt': ROOT / 'requirements-runtime.txt',
             **{name: ROOT / name for name in attestation['artifacts']}}
    files.update({str(p.relative_to(ROOT)): p for p in (ROOT / 'dashboard/arena').iterdir() if p.is_file()})
    for name, source in files.items():
        if source.is_symlink():
            raise ValueError('No se empaquetan enlaces')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (destination / 'arena-attestation.json').write_text(json.dumps(attestation, sort_keys=True) + '\n')
    # Pin the source in the image itself; no runtime environment override is needed.
    docker = destination / 'Dockerfile'
    docker.write_text(docker.read_text().replace('ARG ARENA_SOURCE_COMMIT', 'ARG ARENA_SOURCE_COMMIT=' + attestation['code_commit']))
    hashes = {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(destination.rglob('*')) if p.is_file()}
    content = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    release = {'profile': 'four-strategy-arena-paper', 'build_id': 'arena-' + content[:16],
               'source_commit': attestation['code_commit'], 'files': hashes, 'payload_sha256': content}
    (destination / 'release.json').write_text(json.dumps(release, indent=2) + '\n')
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(json.dumps(package(parser.parse_args().destination), indent=2))
