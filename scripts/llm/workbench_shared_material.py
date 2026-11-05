"""Registered earnings packs and immutable per-job archives; metadata sharing only."""
from __future__ import annotations

import uuid
import os
from pathlib import Path

import foundation_materials as materials
import foundation_research as research
import foundation_results as results
import workbench_earnings_trial as earnings
import workbench_evidence as ev
from workbench_backup import durable_directory, write_new
from foundation_local_store import _destination, _reserve, _copy, _inventory

SCHEMA = 'ar.shared-material-input.v1'
KIND = 'earnings-review'
SCOPE = 'REGISTERED_MATERIAL_NOT_MARKET_PUBLICATION'


def snapshot(library_root, pack_root, *, expected_library_hash, expected_pack_hash):
    library = materials.verify_library(library_root, expected_library_hash=expected_library_hash)
    pack = research.verify_research_pack(pack_root, expected_pack_hash)
    request = ev.parse(ev.read_local(pack_root, 'request.json'))
    if request['expected_library_hash'] != library['library_hash']:
        raise ValueError('SHARED_MATERIAL_LIBRARY_CONFLICT')
    source_map = ev.parse(ev.read_local(pack_root, 'source-map.json'))
    indexed = {(row['material_id'], row['version']): row for row in library['materials']}
    for document in source_map['documents']:
        selected = document['selection']
        if indexed.get((selected['material_id'], selected['version'])) != document['material']:
            raise ValueError('SHARED_MATERIAL_METADATA_CONFLICT')
    files = {**{'library/' + k: ev.sha(v) for k, v in results._tree(Path(library_root)).items()},
             **{'pack/' + k: ev.sha(v) for k, v in results._tree(Path(pack_root)).items()}}
    value = {'schema': 'ar.shared-material-snapshot.v1', 'company': pack['company'],
             'research_date': pack['as_of'], 'source_cutoff_at': pack['source_cutoff_at'],
             'library_hash': expected_library_hash, 'pack_hash': expected_pack_hash,
             'files': files, 'human_review': 'PENDING', 'sample_purpose': 'WORKFLOW_DEBUG',
             'production_authority': False, 'content_sharing_allowed': False}
    value['frozen_input_hash'] = ev.sealed(value)
    return value


def envelope(value):
    checksum = value['frozen_input_hash']
    if (value.get('schema') != 'ar.shared-material-snapshot.v1'
            or checksum != ev.sealed({k: v for k, v in value.items() if k != 'frozen_input_hash'})):
        raise ValueError('SHARED_MATERIAL_INPUT_HASH_CONFLICT')
    return {'schema': SCHEMA, 'snapshot_id': str(uuid.uuid5(uuid.NAMESPACE_URL, SCHEMA + ':' + checksum)),
            'input_hash': checksum, 'publication_fingerprint': value['pack_hash'],
            'attempt_fingerprint': value['library_hash'], 'source_run_id': None,
            'source_trade_date': None, 'validation_scope': SCOPE, 'snapshot': value}


def copy_input(library_root, pack_root, target, value):
    target = _destination(target, [library_root, pack_root])
    _reserve(target)
    _copy(library_root, target / 'library', _inventory(Path(library_root)))
    _copy(pack_root, target / 'pack', _inventory(Path(pack_root)))
    verify_input(target, value)
    if snapshot(library_root, pack_root, expected_library_hash=value['library_hash'],
                expected_pack_hash=value['pack_hash']) != value:
        raise ValueError('SHARED_MATERIAL_SOURCE_CHANGED')


def verify_input(root, value):
    envelope(value)
    actual_files = {name: ev.sha(raw) for name, raw in results._tree(Path(root)).items()}
    # governance-mutation: SHARED_MATERIAL_INVENTORY
    if actual_files != value['files']:
        raise ValueError('SHARED_MATERIAL_INVENTORY_CONFLICT')
    actual = snapshot(Path(root) / 'library', Path(root) / 'pack',
                      expected_library_hash=value['library_hash'], expected_pack_hash=value['pack_hash'])
    if actual != value:
        raise ValueError('SHARED_MATERIAL_BINDING_CONFLICT')
    return value


def register(inputs, library_root, pack_root, *, expected_library_hash, expected_pack_hash):
    """Operator-only registration, never accepts a browser path or grants rights."""
    inputs.check_source_root(library_root); inputs.check_source_root(pack_root)
    value = snapshot(library_root, pack_root, expected_library_hash=expected_library_hash,
                     expected_pack_hash=expected_pack_hash)
    entry = envelope(value); sid = entry['snapshot_id']
    with inputs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT input_hash, body FROM shared_inputs WHERE snapshot_id=?', (sid,)).fetchone()
        if prior:
            return inputs._descriptor(inputs.verify_registered(inputs.base, sid, prior))
        inputs._capacity(db, entry['input_hash'], entry['publication_fingerprint'], entry['attempt_fingerprint'])
        target = inputs.base / 'material-packs' / entry['input_hash']
        durable_directory(target.parent)
        work = inputs.store.path.parent / 'input-write-evidence' / entry['input_hash']
        durable_directory(work)
        from workbench_shared_inputs import _new_or_identical
        _new_or_identical(work / 'material-intent.json', ev.canonical(entry).encode(), evidence_root=work / 'writes')
        # governance-mutation: SHARED_MATERIAL_REGISTRATION_RESUME
        if target.exists():
            verify_input(target, value)
        else:
            attempts = list(work.glob('material-attempt-*'))
            if len(attempts) >= 3: raise ValueError('SHARED_MATERIAL_REGISTRATION_RECOVERY_REQUIRED')
            staging = work / ('material-attempt-' + uuid.uuid4().hex)
            copy_input(library_root, pack_root, staging, value)
            os.rename(staging, target)
            from workbench_backup import fsync_directory
            fsync_directory(target.parent); fsync_directory(work)
        _new_or_identical(inputs.base / 'envelopes' / (sid + '.json'), ev.canonical(entry).encode(), evidence_root=work / 'writes')
        db.execute('INSERT INTO shared_inputs VALUES (?, ?, ?)', (sid, entry['input_hash'], ev.canonical(entry)))
    return inputs._descriptor(inputs.verify(sid))


def render(root, output, value):
    root, output = Path(root), Path(output)
    verify_input(root, value)
    result = earnings.run(root / 'pack', output / 'case', expected_pack_hash=value['pack_hash'])
    intake = {'schema': 'ar.research-result-intake.v1', 'library_id': 'shared-earnings-result',
              'material_id': 'research-result-' + value['frozen_input_hash'][:32], 'version': 'v1',
              'expected_source_library_hash': value['library_hash'], 'expected_pack_hash': value['pack_hash'],
              'expected_result_hash': ev.sealed(result), 'expected_destination_library_hash': None, 'result': result}
    archived = results.ingest_result(root / 'library', root / 'pack', output / 'case' / value['company'],
                                    output / 'archive', output / 'intake', intake)
    write_new(output / 'result.json', ev.canonical(result).encode())
    write_new(output / 'archive.json', ev.canonical({'library_hash': archived['library_hash']}).encode())
    verify_input(root, value)
    verify_output(output, value)


def verify_output(output, value):
    output = Path(output)
    result = ev.parse(ev.read_local(output, 'result.json'))
    pin = ev.parse(ev.read_local(output, 'archive.json'))['library_hash']
    rows = results.query_results(output / 'archive', expected_library_hash=pin)['results']
    # governance-mutation: SHARED_MATERIAL_ARCHIVE_PIN
    if len(rows) != 1 or rows[0]['result_hash'] != ev.sealed(result) or rows[0]['pack_hash'] != value['pack_hash']:
        raise ValueError('SHARED_MATERIAL_ARCHIVE_CONFLICT')
    case = results._tree(output / 'case' / value['company'])
    results._result(result, rows[0]['result_hash'], result['material_pack'], case)
    row = rows[0]
    if (ev.sha(case['report.md']) != result['reports'][0]['report_sha256']
            or result['reports'][0]['report'].encode() != case['report.md']
            or result.get('human_review') != 'PENDING' or row['human_review'] != 'PENDING'
            or result.get('production_authority') is not False):
        raise ValueError('SHARED_MATERIAL_OUTPUT_CONFLICT')
    return {'status': 'SUCCEEDED', 'output_hash': ev.sealed(result),
            'report_sha256': ev.sha(case['report.md']), 'archive_library_hash': pin,
            'archive_status': 'ARCHIVED', 'human_review': 'PENDING', 'content_sharing_allowed': False}


def detail(output, value, frozen_root):
    checked = verify_output(output, value)
    verify_input(frozen_root, value)
    raw = ev.read_local(Path(frozen_root) / 'pack', 'request.json')
    if ev.sha(raw) != value['files']['pack/request.json']:
        raise ValueError('SHARED_MATERIAL_REQUEST_CHANGED')
    request = ev.parse(raw)
    citations = [{'question_id': row['id'], **{key: citation[key] for key in ('sha256', 'page', 'start', 'end')}}
                 for row in request['questions'] for citation in row['citations']]
    return {**checked, 'citation_locations': citations, 'research_date': value['research_date'],
            'source_cutoff_at': value['source_cutoff_at'], 'company': value['company'],
            'steps': ['REGISTERED_INPUT_VERIFIED', 'EARNINGS_RENDERED', 'ARCHIVED', 'OUTPUT_SEALED'],
            'content_status': 'RIGHTS_UNVERIFIED_CONTENT_DENIED'}
