"""Explicit storage-only migration, preserving the frozen trading engine."""
from contextlib import closing
import fcntl
import hashlib
import json
from pathlib import Path
from . import arena, arena_fees
from .improvement_sources import arena_input_audit
from .arena_reporting import daily_report

SOURCE_COMMIT = '1a1d3b9e25cf376d33f49571545616972eac67e4'
PREREG = '61c6ac319f9f5421a4c1b9ad80e5d5165b2fcc72'
FROZEN_SOURCES = {
    "src/lab/__init__.py": "566db2c86d31c4bfcbcbd5b1d16ac8940be744c3cfcd374bdc40b6d06432b1eb",
    "src/lab/account_readiness.py": "84e9c710f2a0cd6586b5096daee2307270b8ebe6b0bb792a5d493ff66902a29b",
    "src/lab/aggressive_plan.py": "6b6c7d1c928a17cf752d3090ab6b6ac159a54c7f5d6a3b6f993bb3bb2a63f7af",
    "src/lab/aggressive_research.py": "b5757441b7e987ca91bd655717475e57f03d0905fcc47ecb77528c1e88c04cab",
    "src/lab/analyze.py": "330a53c87b4f0b47d5f3282851809e8de95bdabb2cd09cdcafd879ce781965a8",
    "src/lab/arena.py": "024402a808b67dd6033b59bda04f471117fc63161e18fa0f764ba79a63cf9e0c",
    "src/lab/arena_fees.py": "e4ad73af3b7e9b448353fe10912f8c22fbef7efbb19d593796434222fbd7488e",
    "src/lab/arena_fees_upgrade.py": "de23ee42247293c5110028e5a9b4d8ac07704bcd1d4c3f3a058af69715a2f388",
    "src/lab/arena_market.py": "7fd0733d9f35f3deef6504f93681e59700a8224740c813d6bafabde3b7c76dff",
    "src/lab/arena_reporting.py": "4a179d75ac9ddf27d2397093b37499be34e95ce0920e995dd7b69317d6ddb64d",
    "src/lab/arena_reporting_upgrade.py": "271a7c7ad99a89f51bfe84d7c2579b6ca66f19615d433ece94dda4d3b7de75fa",
    "src/lab/arena_service.py": "9d4acaa84ce08978f6250b598afccccda91953ec8141e2c4f6501cf4b9f69ba5",
    "src/lab/backtest.py": "b301f07e587bf3dd2f336aeabf7f197f9d285a13f28a5ab9b05ecedb7fe5f76f",
    "src/lab/bot.py": "b4b66c284e63f8990e27cc40ffde026e7e00d12da63d608b4d57d940c4985129",
    "src/lab/broker_tape.py": "50d7e27b1fa14905b72d80d6a54b0c64048cf441644e7a24a98c532d0694e66a",
    "src/lab/brokers.py": "7b0bcde41b31127101f4b13f6177baf8eab6a08d41fe09ba71e02066a1644213",
    "src/lab/btc_bot.py": "4be7b8d1ae23226af55a346f755c54e95d17ea89f79d81ffac4e7e41ebe57370",
    "src/lab/dashboard.py": "15a954a72cdd07ea6b280a8e945e0e27a176aeb7d3ca28c15d2d6b5f79bd6e7c",
    "src/lab/data.py": "a89bb03f9e70060e3aacdc7c0129276476111d9f09378a0cc754c16ffa44b72d",
    "src/lab/data_evidence.py": "fbce50ce6c147e781777cd880d85e0264cd18e291e225b0acc4cb0e1c31ffb5c",
    "src/lab/deep_research.py": "c478fd8063a7187a38e6180629e65e5d55efbd0e8ec45058d66cca7b2733a563",
    "src/lab/evidence.py": "c0a34194811f60c521d33cf766d06b5121ff37384448a05de52b80361fb63832",
    "src/lab/execution_evidence.py": "99a32c290cf743a737dade61fb3536a2c41686a4fc7612fd7f6aebc59b795df0",
    "src/lab/execution_quality.py": "e2d8527234f535ac2f8326aa5d0a673341d09295b446e3a9c682810685b6ffdb",
    "src/lab/experiments.py": "7ab7e661c4ae6aef1fbdc44d3aafc432768cfa6be09d6a2e9f467ead6f82cf3f",
    "src/lab/hosted.py": "cf8f5f3fe3c27c1368cd3e7cb22e257cdf9b275d032dcc6c7b8cfd73033d0a94",
    "src/lab/journal.py": "8b2e9795ec34cd9b2d0f5f147c8012c9b8b508a276b779548c6e49b080cd1f30",
    "src/lab/ops.py": "ec781a54591cd1ae6c4c47412662cb6846ad5b81eb3a47c5e3a1be48b613b3fa",
    "src/lab/paper_comparison.py": "844911ad5f681726d7a9c823cca7d76aff6ec6e2e6ae5a70e011482263e53d8e",
    "src/lab/paper_ops.py": "f58853916aef0330fe8758d34769246562b9ed44f0c4003463340be40e0c5241",
    "src/lab/performance.py": "ad448b850258746ff349429bb01ebc6df0364cd080cc2c1554533bd865901010",
    "src/lab/portfolio.py": "bed18b16cb63a70375fd3438194e77ef240638581737377db904f8b9d291a2f3",
    "src/lab/railway_entrypoint.py": "053d5d9fe051ff68ff37a74c78dcacec553df5d6c22ad1f86e82dba6f1d4c99f",
    "src/lab/realtime.py": "9022c5de5f9328375c048c26934f8c40aae8a6e02ba374ce37aa419064238443",
    "src/lab/report.py": "e84b1d3c69560da458df6001e9f7ea3d73421a9d1e8fcbe1b6f9a87ed400bd9c",
    "src/lab/research.py": "dc8160dff3d37cd1141862e3e52dc4bbf31709dbd1d6b5feea1ee02c91ff7ab6",
    "src/lab/research_attestation.py": "bdf9faae0d1bf0756b7824075d31f95df35750c3ed50545ecac1531569d50c5a",
    "src/lab/research_data.py": "5a706e844ab8bb541163be632c4dd941072058c9cf8b80a584dacbe6d7c847ae",
    "src/lab/research_multi.py": "308ad8b629e13fd5adf89e745c7c24aa56192bbeb66bbab6ab6d2913d6fd9d8a",
    "src/lab/research_rt.py": "8e2624c67481b9b5eff68db26956c15af83fb2ee18e43a6caba4142f372f591e",
    "src/lab/research_short.py": "baebdd4e6a0dcd27972d8a78327443590dffb1d9d72430a8da1bc379a705cff4",
    "src/lab/research_statistics.py": "6c70fbfa08bcaf3cf6c180463c083946bdf26f2aab2612ba2f8825eafced41c8",
    "src/lab/risk.py": "e83337905859048da2c56da306cc0afaea16ce20c18aabd03c3cf9c66d8b1c4b",
    "src/lab/rotation_observer.py": "ff6b6582c2f151712a71cd4dfd0e5a5e7aa7109d3866df97a885a39264d5311b",
    "src/lab/rotation_plan.py": "f3197c92c0d44cecca644b9eeaf04ec6a0dd88fedf4f6c03b6d5c6a311463fd0",
    "src/lab/runtime.py": "66204645e8153ed4d64acca170054efe23f8349f2c44500d210d93b9e6d09cbd",
    "src/lab/service.py": "8095bbac035feaa437e40fe4dd029a80abd8d563ff6c1c797c2c220b660225ee",
    "src/lab/storage.py": "e723cbcaf7ea56f4f0cdf2947e3bf8a056a6f5693340dd02527d4caff938df32",
    "src/lab/strategies.py": "8d53e6c608060ebf08aecf7da7e749bac846529d6c77c98b3b9d1d957f6f625f",
    "src/lab/validation.py": "ad9feee608816d548924655a5fd98f3fbf14e8adaec3b79b54c3346eadbaa3c4"
}


def verify_frozen_engine():
    for name, checksum in FROZEN_SOURCES.items():
        if hashlib.sha256((arena.ROOT / name).read_bytes()).hexdigest() != checksum:
            raise ValueError('Cambió código congelado: ' + name)


def audit_recovery(directory):
    inputs = arena_input_audit(Path(directory) / arena.DB_NAME)
    daily = daily_report(directory)
    if not daily['ledger']['reconciled']:
        raise ValueError('La contabilidad no concilia')
    fees = arena_fees.report(directory)
    if fees['fee_ledger_verified'] is not True:
        raise ValueError('El ledger de tarifas no está verificado')
    return {'inputs': inputs, 'ledger': daily['ledger'],
            'fees_verified': True, 'fills': fees['totals']['maker_fills'] + fees['totals']['taker_fills'],
            'profitability_verified': False}


def upgrade(directory, *, cutover_confirmed=False):
    directory = Path(directory)
    if not cutover_confirmed or (directory / 'arena.enabled').exists():
        raise ValueError('Detener worker y confirmar corte antes de recuperar almacenamiento')
    verify_frozen_engine()
    proof, fee_proof = arena.execution_proof(PREREG), arena_fees.proof()
    with (directory / 'arena-worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        audit = audit_recovery(directory)
        with closing(arena.connect(directory)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            manifest = json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
            old = manifest.get('proof', {})
            policy = manifest.get('fee_policy', {})
            if (old == proof and policy.get('proof') == fee_proof
                    and manifest.get('storage_recovery')):
                return {'status': 'already_upgraded', 'audit': audit}
            if (old.get('code_commit') != SOURCE_COMMIT or old.get('commit') != PREREG
                    or policy.get('proof', {}).get('code_commit') != SOURCE_COMMIT
                    or policy.get('proof', {}).get('commit') != arena_fees.PREREG
                    or manifest.get('kind') != 'paper' or manifest.get('mode') != 'paper'
                    or manifest.get('live_authorized') is not False
                    or manifest.get('plan') != arena.plan()
                    or manifest.get('plan_sha256') != arena.canonical_hash(arena.plan())
                    or policy.get('schedule_sha256') != arena.canonical_hash(arena_fees.plan())):
                raise ValueError('Origen o reglas distintos del corte autorizado')
            at = arena.now_ms()
            event = {'action': 'storage_recovery_upgrade', 'at_ms': at,
                     'previous_proof': old, 'new_proof': proof,
                     'previous_fee_proof': policy['proof'], 'new_fee_proof': fee_proof,
                     'rule_change': False, 'balances_reset': False,
                     'history_removed': False, 'frozen_sources_verified': len(FROZEN_SOURCES),
                     'gap_is_not_continuous_paper': True}
            manifest['proof'] = proof
            policy['proof'] = fee_proof
            manifest['storage_recovery'] = {'at': arena.iso(at), 'from_code': SOURCE_COMMIT,
                                             'to_code': proof['code_commit'],
                                             'balances_reset': False, 'rule_change': False}
            db.execute("UPDATE meta SET value=? WHERE key='manifest'", (arena._json(manifest),))
            for wid, raw in db.execute('SELECT id,payload FROM wallets').fetchall():
                wallet = json.loads(raw)
                wallet['quotes'] = []
                db.execute('UPDATE wallets SET payload=? WHERE id=?', (arena._json(wallet), wid))
            db.execute('INSERT INTO events(ts,payload) VALUES (?,?)', (at, arena._json(event)))
    return {'status': 'upgraded', 'audit': audit, 'trading_sources_unchanged': len(FROZEN_SOURCES)}
