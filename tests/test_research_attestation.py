"""Offline Git fixtures only; no market data or performance calculations."""
import base64
import copy
import json
import shutil
import subprocess

import pytest
import yaml

from lab.experiments import ResearchGateError, canonical_hash
from lab.research_attestation import generate_attestation, verify_attestation


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True).stdout.decode().strip()


@pytest.fixture
def package(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    git(root, 'init')
    git(root, 'config', 'user.name', 'Synthetic test')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    plan = {'experiment_id': 'synthetic-v2', 'setting': 1}
    variants = [{'id': 'a'}, {'id': 'b'}]
    (root / 'configs').mkdir()
    (root / 'reports').mkdir()
    plan_path = root / 'configs/plan.yaml'
    plan_path.write_text(yaml.safe_dump(plan))
    (root / 'config.yaml').write_text('mode: paper\n')
    prereg = root / 'reports/prereg.md'
    meta = {'status': 'approved', 'protocol_version': 1, 'experiment_id': plan['experiment_id'],
            'config_sha256': canonical_hash(plan), 'variant_ids': ['a', 'b'],
            'hypothesis': 'synthetic integrity', 'evaluation_window': 'no market',
            'criteria': dict.fromkeys(('walk_forward', 'placebo', 'bootstrap', 'cost_stress', 'drawdown'), 'declared')}
    prereg.write_text('---\n' + yaml.safe_dump(meta) + '---\nSynthetic only.\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'preregistration')
    commit = git(root, 'rev-parse', 'HEAD')
    (root / 'src/lab').mkdir(parents=True)
    (root / 'src/lab/code.py').write_text('value = 1\n')
    (root / 'src/lab/__init__.py').write_text('')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'code after preregistration')
    head = git(root, 'rev-parse', 'HEAD')
    document = generate_attestation(root, plan_path, prereg, commit, plan, variants)
    image = tmp_path / 'image'
    shutil.copytree(root, image, ignore=shutil.ignore_patterns('.git'))
    def verify(doc=None, **kwargs):
        return verify_attestation(image, doc or document, image / 'configs/plan.yaml',
                                  image / 'reports/prereg.md', commit, plan, ['a', 'b'],
                                  kwargs.pop('expected_code_commit', head), **kwargs)
    return {'root': root, 'image': image, 'plan': plan, 'variants': variants, 'commit': commit,
            'head': head, 'document': document, 'verify': verify, 'plan_path': plan_path, 'prereg': prereg}


def test_runtime_verifies_without_git_or_network(package, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('runtime called subprocess'))
    proof = package['verify']()
    assert proof['code_commit'] == package['head']
    assert proof['commit'] == package['commit']
    assert proof['attestation_sha256'] == canonical_hash(package['document'])
    assert proof['proof_kind'] == 'git-content-ancestry-v1'
    assert not (package['image'] / '.git').exists()


@pytest.mark.parametrize('path', ['src/lab/code.py', 'config.yaml', 'configs/plan.yaml', 'reports/prereg.md'])
def test_modified_packaged_artifact_rejected_even_if_sha256_is_rewritten(package, path):
    target = package['image'] / path
    target.write_text(target.read_text() + '\n# tampered\n')
    doc = copy.deepcopy(package['document'])
    import hashlib
    doc['artifacts'][path] = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ResearchGateError, match='contenido modificado'):
        package['verify'](doc)


def test_injected_source_rejected(package):
    (package['image'] / 'src/lab/injected.py').write_text('malicious = True\n')
    with pytest.raises(ResearchGateError, match='conjunto de archivos'):
        package['verify']()


def test_deleted_source_rejected(package):
    (package['image'] / 'src/lab/code.py').unlink()
    with pytest.raises(ResearchGateError, match='conjunto de archivos'):
        package['verify']()


def test_build_sha_is_external_anchor(package):
    with pytest.raises(ResearchGateError, match='identidad'):
        package['verify'](expected_code_commit='f' * 40)
    with pytest.raises(ResearchGateError, match='BUILD_ID'):
        package['verify'](expected_code_commit='uncommitted')


def test_changed_commit_parent_cannot_forge_ancestry(package):
    doc = copy.deepcopy(package['document'])
    obj = doc['objects'][package['head']]
    raw = base64.b64decode(obj['data']).replace(package['commit'].encode(), b'0' * 40)
    obj['data'] = base64.b64encode(raw).decode()
    with pytest.raises(ResearchGateError, match='hash de objeto'):
        package['verify'](doc)


def test_missing_ancestry_object_rejected(package):
    doc = copy.deepcopy(package['document'])
    del doc['objects'][package['commit']]
    with pytest.raises(ResearchGateError, match='ascendencia'):
        package['verify'](doc)


def test_incomplete_inventory_rejected(package):
    doc = copy.deepcopy(package['document'])
    del doc['artifacts']['src/lab/code.py']
    with pytest.raises(ResearchGateError, match='inventario'):
        package['verify'](doc)


@pytest.mark.parametrize('tracked', [True, False])
def test_generation_requires_clean_checkout(package, tracked):
    target = 'src/lab/code.py' if tracked else 'untracked.txt'
    (package['root'] / target).write_text('dirty\n')
    with pytest.raises(ResearchGateError, match='git limpio'):
        generate_attestation(package['root'], package['plan_path'], package['prereg'], package['commit'],
                             package['plan'], package['variants'])


def test_preregistration_cannot_be_same_commit(package):
    with pytest.raises(ResearchGateError, match='anterior'):
        generate_attestation(package['root'], package['plan_path'], package['prereg'], package['head'],
                             package['plan'], package['variants'])


def test_symlink_source_rejected(package):
    target = package['image'] / 'src/lab/code.py'
    external = package['image'].parent / 'external.py'
    external.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(external)
    with pytest.raises(ResearchGateError, match='enlace simbólico'):
        package['verify']()


def test_orphan_bytecode_is_not_allowed_in_packaged_image(package):
    (package['image'] / 'src/lab/injected.pyc').write_bytes(b'not a trusted Git artifact')
    with pytest.raises(ResearchGateError, match='bytecode'):
        package['verify']()
