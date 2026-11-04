"""Local historical PDF evidence packs for the existing earnings-trial job."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
import foundation_materials as materials
import workbench_backup as backup
import workbench_evidence as ev
from workbench_snapshot_brief import reject_credentials

MARKER = 'material-pack.json'
INTENT = 'material-pack.intent.json'
EXTRACTOR_VERSION = '6.10.0'
MAX_DOCUMENTS, MAX_PAGES, MAX_QUESTIONS = 8, 32, 16
MAX_PACK_BYTES = 64 * 1024 * 1024
LABELS = {'sample_purpose': 'WORKFLOW_DEBUG', 'human_review': 'PENDING',
          'production_authority': False, 'trading_authority': False,
          'paper_authority': False, 'u4_authority': False,
          'prospective_sample_eligible': False, 'network_calls': 0, 'model_calls': 0}
REQUEST_KEYS = {'schema', 'company', 'as_of', 'source_cutoff_at', 'generated_at',
                'expected_library_hash', 'authoring', 'documents', 'questions'}
CRITERIA = {'metric', 'operator', 'threshold', 'unit', 'measurement', 'due_at', 'wrong_if'}


def _fail(reason):
    raise ev.EvidenceError('MATERIAL_RESEARCH_' + reason)


def _execution_identity():
    from workbench_shared_workspace import execution_identity
    return execution_identity(Path(__file__).resolve().parents[2])


def _observed_at():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def _string(value, limit=1000):
    if type(value) is not str or not value.strip() or len(value) > limit or '\x00' in value:
        _fail('TEXT_INVALID')


def _request(value):
    value = ev.parse(ev.canonical(value).encode())
    reject_credentials(value)
    materials._exact(value, REQUEST_KEYS)
    if value['schema'] != 'ar.material-research-request.v1':
        _fail('SCHEMA_INVALID')
    materials._ticker(value['company'])
    if value['company'] is None or value['company'].endswith('.HK'):
        _fail('COMPANY_INVALID')
    day = materials._date(value['as_of'])
    cutoff, generated = materials._time(value['source_cutoff_at']), materials._time(value['generated_at'])
    cn = timezone(timedelta(hours=8))
    if cutoff > generated or generated.astimezone(cn).date() != day or cutoff > datetime.combine(day, time.max, cn):
        _fail('CUTOFF_INVALID')
    materials._hash(value['expected_library_hash'])
    materials._exact(value['authoring'], {'kind', 'model', 'prompt_version'})
    if value['authoring']['kind'] not in {'AI_DRAFT', 'HUMAN_DRAFT'}:
        _fail('DRAFT_AUTHOR_REQUIRED')
    for key in ('model', 'prompt_version'):
        _string(value['authoring'][key], 200)
    documents = value['documents']
    if type(documents) is not list or not 1 <= len(documents) <= MAX_DOCUMENTS:
        _fail('DOCUMENT_LIMIT')
    hashes, pages = set(), 0
    for document in documents:
        materials._exact(document, {'material_id', 'version', 'sha256', 'pages'})
        materials._identifier(document['material_id']); materials._identifier(document['version'])
        materials._hash(document['sha256'])
        selected = document['pages']
        if (type(selected) is not list or not selected or any(type(p) is not int or not 1 <= p <= 2048 for p in selected)
                or selected != sorted(set(selected)) or document['sha256'] in hashes):
            _fail('PAGE_SELECTION_INVALID')
        hashes.add(document['sha256']); pages += len(selected)
    if pages > MAX_PAGES:
        _fail('PAGE_LIMIT')
    questions = value['questions']
    if type(questions) is not list or not 1 <= len(questions) <= MAX_QUESTIONS:
        _fail('QUESTION_LIMIT')
    ids = set()
    for question in questions:
        materials._exact(question, {'id', 'question', 'criteria', 'citations', 'missing_evidence'})
        materials._identifier(question['id']); _string(question['question'])
        if question['id'] in ids:
            _fail('QUESTION_DUPLICATE')
        ids.add(question['id'])
        materials._exact(question['criteria'], CRITERIA)
        if any(v is not None and type(v) not in {str, int, float} for v in question['criteria'].values()):
            _fail('CRITERIA_INVALID')
        if type(question['missing_evidence']) is not list or not 1 <= len(question['missing_evidence']) <= 8:
            _fail('GAPS_REQUIRED')
        for gap in question['missing_evidence']:
            _string(gap)
        if type(question['citations']) is not list or not 1 <= len(question['citations']) <= 8:
            _fail('CITATIONS_REQUIRED')
        for citation in question['citations']:
            materials._exact(citation, {'sha256', 'page', 'start', 'end', 'expected'})
            materials._hash(citation['sha256']); _string(citation['expected'], 4000)
            if any(type(citation[k]) is not int or citation[k] < 1 for k in ('page', 'start', 'end')):
                _fail('CITATION_RANGE_INVALID')
    return value


def _extract_child(raw, selected):
    import pypdf
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject
    if pypdf.__version__ != EXTRACTOR_VERSION:
        _fail('EXTRACTOR_VERSION_CHANGED')
    if len(raw) > ev.MAX_FILE or not raw.startswith(b'%PDF-') or materials.ACTIVE_PDF.search(raw):
        _fail('PDF_REFUSED')
    reader = pypdf.PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) > 2048 or max(selected) > len(reader.pages):
        _fail('PDF_PAGE_INVALID')
    # PDF names can escape bytes with #xx; inspect decoded objects, not only raw text.
    pending, seen, references = [reader.trailer], set(), set()
    for generation, objects in reader.xref.items():
        pending.extend(IndirectObject(number, generation, reader) for number in objects if number)
    pending.extend(IndirectObject(number, 0, reader) for number in reader.xref_objStm)
    active = {'/JavaScript', '/JS', '/Launch', '/EmbeddedFile', '/OpenAction', '/AA', '/Encrypt'}
    while pending:
        value = pending.pop()
        if isinstance(value, IndirectObject):
            key = (value.idnum, value.generation)
            if key in references:
                continue
            references.add(key); value = value.get_object()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if len(seen) > 100000:
            _fail('PDF_OBJECT_LIMIT')
        if isinstance(value, NameObject) and str(value) in active:
            _fail('PDF_ACTIVE_CONTENT')
        if isinstance(value, DictionaryObject):
            pending.extend(value.keys()); pending.extend(value.values())
        elif isinstance(value, ArrayObject):
            pending.extend(value)
    pages = {}
    for number in selected:
        text = reader.pages[number - 1].extract_text().replace('\r\n', '\n').replace('\r', '\n')
        if not text.strip() or len(text.encode()) > 256 * 1024:
            _fail('PDF_TEXT_UNAVAILABLE')
        pages[str(number)] = text
    return pages


def extract_pages(raw, selected):
    """No shells, network configuration, credentials or unbounded parser process."""
    if len(raw) > ev.MAX_FILE:
        _fail('PDF_SIZE_LIMIT')
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}
    env.update(AR_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
    process = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--extract', json.dumps(selected)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    try:
        try:
            output, _ = process.communicate(raw, timeout=10)
        except subprocess.TimeoutExpired:
            _fail('PDF_EXTRACTION_TIMEOUT')
        if process.returncode or len(output) > 9 * 1024 * 1024:
            _fail('PDF_EXTRACTION_REFUSED')
        pages = ev.parse(output)
        if set(pages) != {str(p) for p in selected} or any(type(x) is not str for x in pages.values()):
            _fail('PDF_EXTRACTION_REFUSED')
        return pages
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _source_name(sha256, page):
    return 'pdf-' + sha256 + '-p' + str(page)


def _compile(request, documents, prepared_at):
    observed = materials._time(prepared_at).astimezone(timezone(timedelta(hours=8)))
    if observed.strftime('%Y%m%d') != request['as_of']:
        _fail('DRAFT_DATE_NOT_OBSERVED')
    if materials._time(request['source_cutoff_at']) > observed:
        _fail('CUTOFF_AFTER_PREPARATION')
    prepared_at = observed.isoformat(timespec='seconds')
    files = {INTENT: ev.canonical({'schema': 'ar.material-research-intent.v1', 'prepared_at': prepared_at, **LABELS}).encode()}
    sources, page_map, provenance = {}, {}, []
    claims = [{'id': q['id'], 'question': q['question'], **q['criteria']} for q in request['questions']]
    files['inputs/questions.json'] = ev.canonical({'questions': claims}).encode()
    sources['questions'] = {'path': 'questions.json', 'sha256': ev.sha(files['inputs/questions.json']),
        'company': request['company'], 'tier': 'E3', 'published_on': request['as_of'], 'format': 'json',
        'origin': 'document:NEW_DRAFT_NOT_PRIOR_THESIS; observed preparation time, not caller-asserted history', 'observed_at': prepared_at}
    if len(documents) != len(request['documents']):
        _fail('DOCUMENT_SET_INVALID')
    for selection, document in zip(request['documents'], documents):
        row, raw = document['material'], document['raw']
        materials._exact(document, {'material', 'raw'})
        # governance-mutation: MATERIAL_RESEARCH_ORIGINAL_BINDING
        if (row['kind'] != 'original' or row['material_id'] != selection['material_id'] or row['version'] != selection['version']
                or row['ts_code'] != request['company'] or ev.sha(raw) != selection['sha256']
                or not any(f['sha256'] == selection['sha256'] and f['size_bytes'] == len(raw) for f in row['files'])):
            _fail('ORIGINAL_BINDING_INVALID')
        cutoff = materials._time(request['source_cutoff_at'])
        if (materials._time(row['published_at']) > cutoff or materials._time(row['available_at']) > cutoff
                or materials._time(row['provenance']['captured_at']) > observed):
            _fail('ORIGINAL_AFTER_CUTOFF')
        if row['rights'] != materials.RIGHTS:
            _fail('RIGHTS_CONFLICT')
        pdf_path = 'inputs/originals/' + selection['sha256'] + '.pdf'
        files[pdf_path] = raw
        extracted = extract_pages(raw, selection['pages'])
        provenance.append({'selection': selection, 'material': row, 'original_path': pdf_path})
        for page in selection['pages']:
            source = _source_name(selection['sha256'], page)
            text = extracted[str(page)]
            relative = 'pages/' + selection['sha256'] + '-p' + str(page) + '.txt'
            files['inputs/' + relative] = text.encode()
            page_map[source] = {'sha256': selection['sha256'], 'physical_page': page, 'text_sha256': ev.sha(text.encode()),
                                'original_path': pdf_path, 'text_path': 'inputs/' + relative}
            publication_day = materials._time(row['published_at']).astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')
            precision = row['provenance'].get('publication_precision', {'basis': 'TIMESTAMP_RECORDED'})
            sources[source] = {'path': relative, 'sha256': ev.sha(text.encode()), 'company': request['company'],
                'tier': 'E3', 'published_on': publication_day, 'format': 'text',
                'origin': row['provenance']['source_locator'] + ' ; PDF SHA256 ' + selection['sha256'] + ' ; physical page ' + str(page)
                    + ' ; publisher UNVERIFIED ; publication precision ' + precision['basis'] + ' ; extracted text is a derivative',
                'observed_at': row['provenance']['captured_at']}
    responses = []
    for question in request['questions']:
        citations = []
        for citation in question['citations']:
            source = _source_name(citation['sha256'], citation['page'])
            if source not in page_map:
                _fail('CITATION_PAGE_NOT_SELECTED')
            lines = files[page_map[source]['text_path']].decode().split('\n')
            # governance-mutation: MATERIAL_RESEARCH_QUOTE_BINDING
            if not 1 <= citation['start'] <= citation['end'] <= len(lines) or '\n'.join(lines[citation['start'] - 1:citation['end']]) != citation['expected']:
                _fail('QUOTE_MISMATCH')
            citations.append({'source': source, **{k: citation[k] for k in ('start', 'end', 'expected')}})
        responses.append({'claim_id': question['id'], 'evidence': citations, 'draft_assessment': 'UNRESOLVED',
            'draft_comment': 'Only quoted bytes were verified. Source cutoff ' + request['source_cutoff_at'] +
                '; historical materials are not a current completeness assertion. New question draft, not prior thesis registration.',
            'missing_evidence': question['missing_evidence']})
    trial = {'schema': 'ar.workflow-trial.v1', 'workflow': 'earnings', 'as_of': request['as_of'],
        'generated_at': prepared_at, 'mode': 'HISTORICAL_REPLAY', 'sources': sources,
        'authoring': request['authoring'], 'payload': {'company': request['company'],
            'claims': {'source': 'questions', 'pointer': '/questions', 'expected': claims}, 'registered_at': None, 'responses': responses}}
    files['requests/earnings-' + request['company'] + '.json'] = ev.canonical(trial).encode()
    from workbench_earnings_trial import MAX_REQUEST_BYTES
    if len(files['requests/earnings-' + request['company'] + '.json']) > MAX_REQUEST_BYTES:
        _fail('CONSUMER_REQUEST_LIMIT')
    files['request.json'] = ev.canonical(request).encode()
    files['source-map.json'] = ev.canonical({'schema': 'ar.material-research-provenance.v1', 'documents': provenance,
        'pages': page_map, 'extractor': {'name': 'pypdf', 'version': EXTRACTOR_VERSION},
        'prepared_at': prepared_at, 'asserted_draft_generated_at': request['generated_at'],
        'rights': materials.RIGHTS, **LABELS}).encode()
    if sum(map(len, files.values())) > MAX_PACK_BYTES or any(len(raw) > ev.MAX_FILE for raw in files.values()):
        _fail('PACK_SIZE_LIMIT')
    return files


def _preflight(root, files):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from experiments.research_workflows import trial
    from workbench_earnings_trial import MAX_REPORT_BYTES
    request = next(value for name, value in files.items() if name.startswith('requests/earnings-'))
    rendered = trial.build(ev.parse(request), root / 'inputs')
    if len(rendered['report'].encode()) > MAX_REPORT_BYTES:
        _fail('CONSUMER_REPORT_LIMIT')


def _summary(request, files, pack_hash, preparation_identity, prepared_at):
    return {'schema': 'ar.material-research-pack-receipt.v1', 'pack_hash': pack_hash, 'company': request['company'],
        'as_of': request['as_of'], 'source_cutoff_at': request['source_cutoff_at'], 'documents': len(request['documents']),
        'pages': sum(len(d['pages']) for d in request['documents']), 'questions': len(request['questions']),
        'files': files, 'mode': 'HISTORICAL_REPLAY', 'rights': dict(materials.RIGHTS),
        'preparation_execution_identity': preparation_identity, 'prepared_at': prepared_at, **LABELS}


def prepare_research_pack(library_root, request, output_root):
    request = _request(request)
    preparation_identity = _execution_identity()
    prepared_at = materials._time(_observed_at()).astimezone(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    library, output = materials._root(library_root), materials._root(output_root)
    if library == output or library in output.parents or output in library.parents:
        _fail('ROOT_OVERLAP')
    verified = materials.verify_library(library, expected_library_hash=request['expected_library_hash'])
    rows = {(r['material_id'], r['version']): r for r in verified['materials']}
    documents = []
    for selection in request['documents']:
        row = rows.get((selection['material_id'], selection['version']))
        if row is None or row['kind'] != 'original':
            _fail('MATERIAL_NOT_ADMITTED')
        item = next((f for f in row['files'] if f['sha256'] == selection['sha256']), None)
        if item is None or Path(item['source_path']).suffix.lower() != '.pdf':
            _fail('ORIGINAL_BINDING_INVALID')
        relative = 'registrations/' + row['registration_hash'] + '/files/' + materials._blob_name(item)
        documents.append({'material': row, 'raw': ev.read_local(library, relative)})
    files = _compile(request, documents, prepared_at)
    if _execution_identity() != preparation_identity:
        _fail('CODE_CHANGED')
    manifest = {'schema': 'ar.material-research-pack.v1', 'files': {name: ev.sha(raw) for name, raw in sorted(files.items())},
                'preparation_execution_identity': preparation_identity, 'prepared_at': prepared_at, **LABELS}
    manifest['pack_hash'] = ev.sealed(manifest)
    # Final marker is written last. An interrupted root is retained, never reusable.
    materials._create_private_root(output, ('inputs', 'requests'))
    materials._create_private_root(output / 'inputs/originals')
    materials._create_private_root(output / 'inputs/pages')
    for name, raw in files.items():
        backup.write_new(output / name, raw)
    _preflight(output, files)
    backup.write_new(output / MARKER, ev.canonical(manifest).encode())
    result = verify_research_pack(output, manifest['pack_hash'])
    if _execution_identity() != preparation_identity:
        _fail('CODE_CHANGED')
    return result


def verify_research_pack(pack_root, expected_pack_hash):
    materials._hash(expected_pack_hash)
    root = materials._root(pack_root)
    with materials._directory(root) as directory:
        materials._owned(directory)
    marker_raw = ev.read_local(root, MARKER)
    manifest = ev.parse(marker_raw)
    materials._exact(manifest, {'schema', 'files', 'pack_hash', 'preparation_execution_identity', 'prepared_at', *LABELS})
    identity = manifest['preparation_execution_identity']
    materials._exact(identity, {'code_sha', 'source_tree_hash'})
    materials._hash(identity['code_sha'], 40); materials._hash(identity['source_tree_hash'])
    body = {k: v for k, v in manifest.items() if k != 'pack_hash'}
    # governance-mutation: MATERIAL_RESEARCH_EXTERNAL_PIN
    if (manifest['schema'] != 'ar.material-research-pack.v1' or ev.canonical(manifest).encode() != marker_raw
            or manifest['pack_hash'] != expected_pack_hash or ev.sealed(body) != expected_pack_hash
            or any(type(manifest[k]) is not type(v) or manifest[k] != v for k, v in LABELS.items())):
        _fail('PACK_PIN_MISMATCH')
    if type(manifest['files']) is not dict or not 1 <= len(manifest['files']) <= 128:
        _fail('PACK_INVENTORY_INVALID')
    expected = set(manifest['files']) | {MARKER}
    actual, total = set(), 0
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            _fail('PACK_PATH_INVALID')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix()); total += path.stat().st_size
        if len(actual) > 129 or total > MAX_PACK_BYTES + ev.MAX_FILE:
            _fail('PACK_SIZE_LIMIT')
    # governance-mutation: MATERIAL_RESEARCH_EXACT_INVENTORY
    if actual != expected:
        _fail('PACK_INVENTORY_INVALID')
    raw = {name: ev.read_local(root, name) for name in manifest['files']}
    if any(ev.sha(value) != manifest['files'][name] for name, value in raw.items()):
        _fail('PACK_FILE_HASH_MISMATCH')
    request = _request(ev.parse(raw['request.json']))
    provenance = ev.parse(raw['source-map.json'])
    documents = [{'material': d['material'], 'raw': raw[d['original_path']]} for d in provenance['documents']]
    compiled = _compile(request, documents, manifest['prepared_at'])
    # Re-extract PDFs, re-derive source metadata and re-check every quotation.
    if raw != compiled:
        _fail('PACK_DERIVATION_MISMATCH')
    _preflight(root, raw)
    return _summary(request, manifest['files'], expected_pack_hash, identity, manifest['prepared_at'])


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3 or sys.argv[1] != '--extract':
            raise ValueError()
        print(json.dumps(_extract_child(sys.stdin.buffer.read(ev.MAX_FILE + 1), json.loads(sys.argv[2])), ensure_ascii=False))
    except Exception:
        raise SystemExit(2)
