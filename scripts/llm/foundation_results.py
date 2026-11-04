"""Pinned historical earnings results in the existing immutable local library."""
from __future__ import annotations

import copy
import fcntl
from pathlib import Path
import sys

import foundation_materials as materials
import foundation_research as research
import workbench_backup as backup
import workbench_evidence as ev
from workbench_snapshot_brief import reject_credentials

LABELS = research.LABELS
PREFIX = 'research-result-'
RECORD = 'result-record.json'
KEYS = {'schema', 'library_id', 'material_id', 'version', 'expected_source_library_hash',
        'expected_pack_hash', 'expected_result_hash', 'expected_destination_library_hash', 'result'}
RECORD_KEYS = {'schema', 'material_id', 'version', 'source_library_hash', 'pack_hash', 'result_hash',
               'result_metadata', 'pack_files', 'artifact_files', 'imported_at', 'importer_execution_identity',
               'industry_key', 'industry_taxonomy', 'taxonomy_version', 'record_hash', *LABELS}


def _fail(code):
    raise ev.EvidenceError('RESEARCH_RESULT_' + code)


def _identity(value):
    materials._exact(value, {'code_sha', 'source_tree_hash'})
    materials._hash(value['code_sha'], 40); materials._hash(value['source_tree_hash'])


def _tree(root):
    root = materials._root(root)
    with materials._directory(root):
        pass
    files, size, directories = {}, 0, set()
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            _fail('ARTIFACT_PATH_INVALID')
        if path.is_file():
            if path.stat().st_nlink != 1 or path.stat().st_mode & 0o111:
                _fail('ARTIFACT_LINK_OR_MODE_INVALID')
            raw = ev.read_local(root, path.relative_to(root).as_posix())
            size += len(raw); files[path.relative_to(root).as_posix()] = raw
        else:
            directories.add(path.relative_to(root).as_posix())
        if len(files) > 256 or size > 128 * 1024 * 1024:
            _fail('ARTIFACT_LIMIT')
    expected_directories = {str(parent) for name in files for parent in Path(name).parents if str(parent) != '.'}
    if directories != expected_directories:
        _fail('ARTIFACT_DIRECTORY_INVENTORY_INVALID')
    return files


def _result(value, expected_hash, pack, artifact_files):
    materials._hash(expected_hash)
    reject_credentials(value)
    materials._exact(value, {'status', 'sample_purpose', 'as_of', 'coverage', 'human_review',
        'production_authority', 'u4_authority', 'paper_authority', 'trade_authority', 'reports',
        'material_pack', 'consumer_execution_identity'})
    if ev.sealed(value) != expected_hash:
        _fail('RESULT_PIN_MISMATCH')
    if (value['status'] != 'COMPLETED_HISTORICAL_EARNINGS' or value['coverage'] != 'FROZEN_REQUESTS_ONLY'
            or value['sample_purpose'] != 'WORKFLOW_DEBUG' or value['human_review'] != 'PENDING'
            or any(value[k] is not False for k in ('production_authority', 'u4_authority', 'paper_authority', 'trade_authority'))):
        _fail('RESULT_NOT_UNREVIEWED_HISTORICAL')
    _identity(value['consumer_execution_identity'])
    if ev.canonical(value['material_pack']) != ev.canonical(pack) or value['as_of'] != pack['as_of']:
        _fail('INPUT_BINDING_INVALID')
    if type(value['reports']) is not list or len(value['reports']) != 1:
        _fail('REPORT_SET_INVALID')
    row = value['reports'][0]
    materials._exact(row, {'company', 'as_of', 'data_status', 'registration_status', 'human_review',
                          'report', 'report_sha256', 'request_sha256', 'receipt_sha256'})
    artifact = ev.parse(artifact_files['artifact.json'])
    receipt = ev.parse(artifact_files['receipt.json'])
    if (row['company'] != pack['company'] or row['as_of'] != pack['as_of']
            or row['human_review'] != 'PENDING' or row['registration_status'] != 'NOT_PREREGISTERED'
            or type(row['report']) is not str
            or row['report'].encode() != artifact_files['report.md']
            or row['report_sha256'] != ev.sha(artifact_files['report.md'])
            or row['receipt_sha256'] != ev.sha(artifact_files['receipt.json'])
            or row['data_status'] != artifact['data_status'] or receipt['data_status'] != artifact['data_status']
            or row['data_status'] not in {'CITED_NOT_HUMAN_VERIFIED', 'PARTIAL'}
            or artifact['human_review'] != 'PENDING' or any(v is not False for v in artifact['authority'].values())
            or artifact['registration_status'] != 'NOT_PREREGISTERED'
            or any(r['draft_assessment'] != 'UNRESOLVED' for r in artifact['rows'])
            or receipt['human_review'] != 'PENDING' or receipt['execution_status'] != 'COMPLETED'
            or set(receipt['outputs']) != set(artifact_files) - {'receipt.json', 'SHA256SUMS'}
            or any(receipt['outputs'][name] != ev.sha(artifact_files[name]) for name in receipt['outputs'])):
        _fail('ARTIFACT_BINDING_INVALID')
    sums = ''.join(ev.sha(raw) + '  ' + name + '\n' for name, raw in sorted(artifact_files.items()) if name != 'SHA256SUMS')
    if artifact_files['SHA256SUMS'] != sums.encode():
        _fail('ARTIFACT_SUMS_INVALID')
    return artifact


def _index(verified):
    return {f['sha256']: 'registrations/' + row['registration_hash'] + '/files/' + materials._blob_name(f)
            for row in verified['materials'] for f in row['files']}


def _stored(root, verified):
    index, rows = _index(verified), []
    for material in verified['materials']:
        if not material['material_id'].startswith(PREFIX):
            continue
        proof = [f for f in material['files'] if f['source_path'] == RECORD]
        if material['kind'] != 'review' or len(proof) != 1:
            _fail('RESULT_RECORD_MISSING')
        raw = ev.read_local(root, index[proof[0]['sha256']]); record = ev.parse(raw)
        materials._exact(record, RECORD_KEYS)
        if (record['schema'] != 'ar.research-result-record.v1' or ev.canonical(record).encode() != raw
                or record['record_hash'] != ev.sealed({k: v for k, v in record.items() if k != 'record_hash'})
                or any(type(record[k]) is not type(v) or record[k] != v for k, v in LABELS.items())
                or record['material_id'] != material['material_id'] or record['version'] != material['version']):
            _fail('RESULT_RECORD_INVALID')
        _identity(record['importer_execution_identity']); materials._time(record['imported_at'])
        materials._hash(record['source_library_hash'])
        groups = []
        for key in ('pack_files', 'artifact_files'):
            mapping = record[key]
            if type(mapping) is not dict or not 1 <= len(mapping) <= 256:
                _fail('STORED_INVENTORY_INVALID')
            content = {}
            for name, checksum in mapping.items():
                materials._hash(checksum)
                if checksum not in index:
                    _fail('STORED_ARTIFACT_MISSING')
                content[name] = ev.read_local(root, index[checksum])
                if ev.sha(content[name]) != checksum:
                    _fail('STORED_ARTIFACT_HASH_INVALID')
            groups.append(content)
        pack_files, case = groups
        manifest = ev.parse(pack_files[research.MARKER])
        if (manifest['pack_hash'] != record['pack_hash']
                or ev.sealed({k: v for k, v in manifest.items() if k != 'pack_hash'}) != record['pack_hash']
                or set(manifest['files']) != set(pack_files) - {research.MARKER}
                or any(manifest['files'][name] != ev.sha(pack_files[name]) for name in manifest['files'])):
            _fail('STORED_PACK_BINDING_INVALID')
        request = research._request(ev.parse(pack_files['request.json']))
        pack = research._summary(request, manifest['files'], manifest['pack_hash'],
                                  manifest['preparation_execution_identity'], manifest['prepared_at'])
        result = copy.deepcopy(record['result_metadata'])
        result['reports'][0]['report'] = case['report.md'].decode()
        artifact = _result(result, record['result_hash'], pack, case)
        trial_name = 'requests/earnings-' + pack['company'] + '.json'
        if (request['expected_library_hash'] != record['source_library_hash'] or request['company'] != pack['company']
                or request['as_of'] != artifact['as_of'] or pack['pack_hash'] != record['pack_hash']
                or result['reports'][0]['request_sha256'] != ev.sha(pack_files[trial_name])
                or material['trade_date'] != request['as_of'] or material['ts_code'] != request['company']
                or material['code_sha'] != result['consumer_execution_identity']['code_sha']
                or material['cutoff_at'] != request['source_cutoff_at']
                or set(material['original_refs']) != {d['sha256'] for d in request['documents']}
                or any(material[k] != record[k] for k in ('industry_key', 'industry_taxonomy', 'taxonomy_version'))):
            _fail('STORED_RESULT_BINDING_INVALID')
        rows.append({'material_id': material['material_id'], 'version': material['version'],
            'result_hash': record['result_hash'], 'pack_hash': record['pack_hash'], 'research_date': request['as_of'],
            'source_cutoff_at': request['source_cutoff_at'], 'artifact_generated_at': artifact['generated_at'],
            'archived_at': record['imported_at'], 'company': request['company'],
            'source_documents': [{'material_id': item['selection']['material_id'], 'version': item['selection']['version'],
                'pdf_sha256': item['selection']['sha256'], 'published_at': item['material']['published_at'],
                'available_at': item['material']['available_at'], 'captured_at': item['material']['provenance']['captured_at'],
                'publication_precision': item['material']['provenance'].get('publication_precision'),
                'publisher_status': 'UNVERIFIED'} for item in ev.parse(pack_files['source-map.json'])['documents']],
            **{k: material[k] for k in ('industry_key', 'industry_taxonomy', 'taxonomy_version')},
            'consumer_execution_identity': result['consumer_execution_identity'],
            'importer_execution_identity': record['importer_execution_identity'],
            'execution_attestation': 'RECORDED_NOT_REMOTE_ATTESTED', 'report_sha256': result['reports'][0]['report_sha256'],
            'assessments': [r['draft_assessment'] for r in artifact['rows']], 'record_hash': record['record_hash'],
            'stored_verification': 'BYTE_BINDINGS_VERIFIED_NOT_RERUN', **LABELS})
    return rows


def query_results(result_library_root, *, expected_library_hash, industry_key=None, industry_taxonomy=None,
                  taxonomy_version=None, research_date=None, ts_code=None):
    materials._hash(expected_library_hash)
    for value in (industry_key, industry_taxonomy, taxonomy_version):
        if value is not None: materials._identifier(value)
    if research_date is not None: materials._date(research_date)
    if ts_code is not None: materials._ticker(ts_code)
    root = materials._root(result_library_root)
    with materials._directory(root) as fd:
        fcntl.flock(fd, fcntl.LOCK_SH)
        verified = materials._verify_open(fd, expected_library_hash=expected_library_hash)
        rows = _stored(root, verified)
    filters = {'industry_key': industry_key, 'industry_taxonomy': industry_taxonomy,
               'taxonomy_version': taxonomy_version, 'research_date': research_date, 'company': ts_code}
    rows = [row for row in rows if all(value is None or row[key] == value for key, value in filters.items())]
    return {'schema': 'ar.research-result-query.v1', 'library_hash': verified['library_hash'],
            'results': rows, 'query': filters, 'status': 'RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED' if rows else 'EMPTY', **LABELS}


def ingest_result(source_library_root, pack_root, artifact_root, result_library_root, staging_root, request):
    request = ev.parse(ev.canonical(request).encode()); reject_credentials(request)
    materials._exact(request, KEYS)
    for key in ('library_id', 'material_id', 'version'): materials._identifier(request[key])
    if request['schema'] != 'ar.research-result-intake.v1' or not request['material_id'].startswith(PREFIX):
        _fail('INTAKE_SCHEMA_INVALID')
    for key in ('expected_source_library_hash', 'expected_pack_hash', 'expected_result_hash'):
        materials._hash(request[key])
    roots = [materials._root(p) for p in (source_library_root, pack_root, artifact_root, result_library_root, staging_root)]
    source, pack_root, case_root, destination, stage = roots
    code_root = Path(__file__).resolve().parents[2]
    for target in (destination, stage):
        if target == code_root or code_root in target.parents or target in code_root.parents:
            _fail('CODE_ROOT_WRITE_REFUSED')
        for other in roots:
            if other == target: continue
            if target in other.parents or other in target.parents: _fail('ROOT_OVERLAP')
    if len(set(roots)) != len(roots): _fail('ROOT_OVERLAP')
    importer = research._execution_identity()
    verified_source = materials.verify_library(source, expected_library_hash=request['expected_source_library_hash'])
    pack = research.verify_research_pack(pack_root, request['expected_pack_hash'])
    pack_files, case = _tree(pack_root), _tree(case_root)
    frozen = research._request(ev.parse(pack_files['request.json']))
    if frozen['expected_library_hash'] != verified_source['library_hash']:
        _fail('SOURCE_LIBRARY_BINDING_INVALID')
    source_map = ev.parse(pack_files['source-map.json'])
    indexed = {(r['material_id'], r['version']): r for r in verified_source['materials']}
    for item in source_map['documents']:
        selected = item['selection']; original = indexed.get((selected['material_id'], selected['version']))
        if ev.canonical(original) != ev.canonical(item['material']): _fail('SOURCE_METADATA_CHANGED')
    sys.path.insert(0, str(code_root))
    from experiments.research_workflows import trial
    trial_request = ev.parse(pack_files['requests/earnings-' + pack['company'] + '.json'])
    built = trial.build(trial_request, pack_root / 'inputs')
    if case != built['files']: _fail('CASE_INVENTORY_OR_BYTES_INVALID')
    _result(request['result'], request['expected_result_hash'], pack, case)
    if request['result']['reports'][0]['request_sha256'] != ev.sha(pack_files['requests/earnings-' + pack['company'] + '.json']):
        _fail('REQUEST_BINDING_INVALID')
    pin = request['expected_destination_library_hash']
    existing = None
    if pin is not None:
        existing = materials.verify_library(destination, expected_library_hash=pin)
        if existing['library_id'] != request['library_id']: _fail('LIBRARY_IDENTITY_CONFLICT')
        for row in _stored(destination, existing):
            if row['material_id'] == request['material_id'] and row['version'] == request['version']:
                if row['result_hash'] != request['expected_result_hash']: _fail('RESULT_IDENTITY_CONFLICT')
                return {'schema': 'ar.research-result-intake-result.v1', 'disposition': 'ALREADY_IMPORTED',
                        'library_hash': existing['library_hash'], **LABELS}
            if row['result_hash'] == request['expected_result_hash']: _fail('RESULT_DUPLICATE_CONTENT')
    elif destination.exists() or destination.is_symlink():
        _fail('DESTINATION_ALREADY_EXISTS')
    taxonomy = {tuple(d['material'][k] for k in ('industry_key', 'industry_taxonomy', 'taxonomy_version')) for d in source_map['documents']}
    if len(taxonomy) != 1: _fail('SOURCE_TAXONOMY_CONFLICT')
    industry = dict(zip(('industry_key', 'industry_taxonomy', 'taxonomy_version'), next(iter(taxonomy))))
    observed = research._observed_at()
    if materials._time(observed) < materials._time(pack['prepared_at']): _fail('IMPORT_BEFORE_PREPARATION')
    metadata = copy.deepcopy(request['result']); metadata['reports'][0].pop('report')
    record = {'schema': 'ar.research-result-record.v1', 'material_id': request['material_id'], 'version': request['version'],
        'source_library_hash': verified_source['library_hash'], 'pack_hash': pack['pack_hash'],
        'result_hash': request['expected_result_hash'], 'result_metadata': metadata,
        'pack_files': {name: ev.sha(raw) for name, raw in pack_files.items()},
        'artifact_files': {name: ev.sha(raw) for name, raw in case.items()},
        'imported_at': observed, 'importer_execution_identity': importer, **industry, **LABELS}
    record['record_hash'] = ev.sealed(record)
    known = _index(existing) if existing else {}
    raw_by_hash = {ev.sha(raw): (raw, Path(name).suffix.lower() or '.txt') for name, raw in {**pack_files, **case}.items()}
    for name, raw in pack_files.items():
        if name.startswith('inputs/originals/'): raw_by_hash[ev.sha(raw)] = (raw, '.pdf')
    rows, original_hashes = [], set()
    for document in source_map['documents']:
        checksum = document['selection']['sha256']; original_hashes.add(checksum)
        if checksum in known:
            matched = next(r for r in existing['materials'] if any(f['sha256'] == checksum for f in r['files']))
            if matched['kind'] != 'original' or matched['ts_code'] != pack['company'] or any(matched[k] != industry[k] for k in industry):
                _fail('DESTINATION_ORIGINAL_CONFLICT')
            continue
        row = {k: copy.deepcopy(v) for k, v in document['material'].items() if k in materials.ROW_KEYS}
        row.update(material_id='selected-pdf-' + checksum[:32], version='sha256-' + checksum[:24],
            files=[{'source_path': 'blobs/' + checksum + '.pdf', 'sha256': checksum, 'size_bytes': len(raw_by_hash[checksum][0])}])
        rows.append(row)
    files = []
    for checksum, (raw, suffix) in sorted(raw_by_hash.items()):
        if checksum not in known and checksum not in original_hashes:
            files.append({'source_path': 'blobs/' + checksum + suffix, 'sha256': checksum, 'size_bytes': len(raw)})
    base_row = {'kind': 'review',
        'title': 'Frozen earnings response, human review pending: ' + pack['company'], **industry,
        'ts_code': pack['company'], 'trade_date': pack['as_of'], 'run_id': 'research-' + request['expected_result_hash'][:32],
        'code_sha': request['result']['consumer_execution_identity']['code_sha'],
        'published_at': observed, 'available_at': observed, 'cutoff_at': pack['source_cutoff_at'],
        'provenance': None, 'original_refs': sorted(original_hashes), 'rights': dict(materials.RIGHTS)}
    rows.append({**base_row, 'material_id': request['material_id'], 'version': request['version'],
        'files': [{'source_path': RECORD, 'sha256': ev.sha(ev.canonical(record).encode()), 'size_bytes': len(ev.canonical(record).encode())}]})
    # Keep the existing16-files/material limit; auxiliary rows own deduplicated blobs.
    for offset in range(0, len(files), 16):
        rows.append({**base_row, 'material_id': 'research-blobs-' + request['expected_result_hash'][:32] + '-' + str(offset // 16),
                     'version': 'v1', 'files': files[offset:offset + 16]})
    manifest = {'schema': 'ar.material-intake.v1', 'library_id': request['library_id'], 'created_at': observed, 'materials': rows}
    materials._manifest(manifest)
    if research._execution_identity() != importer: _fail('IMPORT_CODE_CHANGED')
    materials._create_private_root(stage, ('blobs',))
    backup.write_new(stage / RECORD, ev.canonical(record).encode())
    for checksum, (raw, suffix) in sorted(raw_by_hash.items()):
        if checksum not in known: backup.write_new(stage / ('blobs/' + checksum + suffix), raw)
    materials.inspect_material_source(stage, manifest)
    if research._execution_identity() != importer: _fail('IMPORT_CODE_CHANGED')
    registered = materials.ingest_material(stage, destination, manifest, expected_library_hash=pin, require_new=pin is None)
    view = query_results(destination, expected_library_hash=registered['library_hash'])
    if not any(row['record_hash'] == record['record_hash'] for row in view['results']): _fail('PUBLISHED_RECORD_MISSING')
    if research._execution_identity() != importer: _fail('IMPORT_CODE_CHANGED')
    return {'schema': 'ar.research-result-intake-result.v1', 'disposition': 'IMPORTED',
            'library_hash': registered['library_hash'], 'registration_hash': registered['registration_hash'],
            'record_hash': record['record_hash'], **LABELS}
