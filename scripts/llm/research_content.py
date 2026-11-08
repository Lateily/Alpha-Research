"""Evidence-bound research drafts; no providers, approval inference or state writes."""
from __future__ import annotations

import argparse
from datetime import timedelta
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import foundation_materials as materials
import foundation_research as material
import workbench_backup as backup
import workbench_evidence as ev
from workbench_snapshot_brief import reject_credentials
from experiments.research_workflows.evidence import text

SCHEMA = 'ar.research-content-request.v1'
SCHEMA_V2 = 'ar.research-content-request.v2'
KEYS = {'schema', 'company', 'as_of', 'generated_at', 'pack_hash', 'authoring',
        'facts', 'calculations', 'responses', 'valuation', 'technical', 'feedback'}
LABELS = {**material.LABELS, 'claim_allowed': False, 'no_trade_flag': True}
NUMBER = re.compile(r'(?<![\w.,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w.,])')
OPERATORS = {'DIFFERENCE', 'RATIO', 'GROWTH_PCT', 'ANNUALIZED_HALF_YEAR_SENSITIVITY'}
VALUATION_INPUTS = {'normalized_eps', 'fair_multiple_low', 'fair_multiple_high', 'net_cash_per_share'}


def _fail(reason):
    raise ev.EvidenceError('RESEARCH_CONTENT_' + reason)


def _observed_at():
    return material._observed_at()


def _execution_identity():
    root = Path(__file__).resolve().parents[2]
    identity = material._execution_identity()
    names = ('scripts/llm/research_content.py', 'scripts/llm/research_daily.py', 'scripts/llm/research_valuation.py',
             'experiments/research_workflows/smc_ict_engine.py',
             'experiments/research_workflows/smc_ict_input.py', 'experiments/research_workflows/smc_ict_concepts.py',
             'experiments/research_funnel/research_cycle.py', 'experiments/research_funnel/research_method.py')
    hashes = {name: ev.sha(ev.read_local(root, name)) for name in names}
    return {**identity, 'source_tree_hash': ev.sealed({'base': identity['source_tree_hash'], 'content': hashes})}


def _number(value):
    if type(value) is not str or not re.fullmatch(r'-?\d{1,18}(?:\.\d{1,12})?', value):
        _fail('NUMBER_INVALID')
    try:
        number = Decimal(value)
    except InvalidOperation:
        _fail('NUMBER_INVALID')
    if not number.is_finite():
        _fail('NUMBER_INVALID')
    return number


def _decimal(value):
    if value == 0:
        return '0'
    rendered = format(value, 'f')
    return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered


def calculate(operator, values):
    """Decimal-only arithmetic; null is an undefined ratio, never zero."""
    if operator not in OPERATORS or len(values) != (1 if operator == 'ANNUALIZED_HALF_YEAR_SENSITIVITY' else 2):
        _fail('CALCULATION_SHAPE')
    numbers = [_number(value) for value in values]
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        first = numbers[0]
        if operator == 'ANNUALIZED_HALF_YEAR_SENSITIVITY':
            return _decimal(first * 2)
        second = numbers[1]
        if operator == 'DIFFERENCE':
            return _decimal(first - second)
        if second == 0:
            return None
        value = first / second if operator == 'RATIO' else (first / second - 1) * 100
        return _decimal(value.quantize(Decimal('0.00000001')))


def _rows(value, key, maximum=64, empty=False):
    if type(value) is not list or not (0 if empty else 1) <= len(value) <= maximum:
        _fail('ROW_LIMIT')
    identifiers = []
    for row in value:
        if type(row) is not dict or key not in row:
            _fail('ROW_INVALID')
        materials._identifier(row[key]); identifiers.append(row[key])
    if len(identifiers) != len(set(identifiers)):
        _fail('DUPLICATE_ID')
    return identifiers


def _refs(value, allowed, empty=False):
    if (type(value) is not list or len(value) > 64 or (not value and not empty)
            or any(type(item) is not str or item not in allowed for item in value)
            or len(value) != len(set(value))):
        _fail('REFERENCE_INVALID')


def _notes(value):
    if type(value) is not list or not 1 <= len(value) <= 12:
        _fail('OPEN_QUESTIONS_REQUIRED')
    for item in value:
        material._string(item, 2000)


def _pack(root, pin):
    material.verify_research_pack(root, pin)
    manifest = ev.parse(ev.read_local(root, material.MARKER))
    # Retain a manifest snapshot which independently matches the caller's pin.
    # governance-mutation: CONTENT_MANIFEST_SNAPSHOT_PIN
    if manifest.get('pack_hash') != pin or ev.sealed({k: v for k, v in manifest.items() if k != 'pack_hash'}) != pin:
        _fail('SOURCE_MANIFEST_PIN')
    def read(name):
        raw = ev.read_local(root, name)
        # governance-mutation: CONTENT_USED_BYTES_PIN
        if ev.sha(raw) != manifest['files'].get(name):
            _fail('SOURCE_CHANGED')
        return raw
    return ev.parse(read('request.json')), read


def _facts(rows, read, *, maximum=64):
    _rows(rows, 'id', maximum=maximum)
    result = {}
    for row in rows:
        materials._exact(row, {'id', 'metric', 'period', 'unit', 'citation', 'token_index', 'value'})
        for key in ('metric', 'period'):
            material._string(row[key], 200)
        if row['unit'] not in {'CNY', 'CNY_PER_SHARE', 'COUNT', 'PCT'}:
            _fail('UNIT_INVALID')
        citation = row['citation']
        materials._exact(citation, {'sha256', 'page', 'start', 'end', 'expected'})
        materials._hash(citation['sha256'])
        if any(type(citation[k]) is not int or citation[k] < 1 for k in ('page', 'start', 'end')):
            _fail('QUOTE_RANGE')
        name = 'inputs/pages/' + citation['sha256'] + '-p' + str(citation['page']) + '.txt'
        lines = read(name).decode('utf-8').splitlines()
        if citation['end'] < citation['start'] or citation['end'] > len(lines):
            _fail('QUOTE_RANGE')
        quote = '\n'.join(lines[citation['start'] - 1:citation['end']])
        # governance-mutation: CONTENT_QUOTE_BINDING
        if quote != citation['expected']:
            _fail('QUOTE_MISMATCH')
        tokens = NUMBER.findall(quote)
        index = row['token_index']
        number = _number(row['value'])
        # governance-mutation: CONTENT_NUMERIC_BINDING
        if type(index) is not int or not 0 <= index < len(tokens) or Decimal(tokens[index].replace(',', '')) != number:
            _fail('NUMERIC_QUOTE_MISMATCH')
        result[row['id']] = {**row, 'value': _decimal(number), 'quoted_token': tokens[index],
            'status': 'SOURCE_BYTES_VERIFIED_SEMANTICS_UNVERIFIED', 'evidence_tier': 'E3'}
    return result


def _calculations(rows, facts):
    _rows(rows, 'id', empty=True)
    result = {}
    for row in rows:
        materials._exact(row, {'id', 'operator', 'operands'})
        _refs(row['operands'], facts)
        operands = [facts[key] for key in row['operands']]
        same_period = len({item['period'] for item in operands}) == 1
        if row['operator'] == 'GROWTH_PCT' and len(operands) == 2:
            current, previous = [re.fullmatch(r'(\d{4})(FY|H1|Q[1-4])', item['period']) for item in operands]
            same_period = bool(current and previous and current[2] == previous[2] and int(current[1]) == int(previous[1]) + 1)
        # governance-mutation: CONTENT_PERIOD_UNIT_BINDING
        if len({item['unit'] for item in operands}) != 1 or not same_period:
            _fail('PERIOD_OR_UNIT_MISMATCH')
        value = calculate(row['operator'], [item['value'] for item in operands])
        annual = row['operator'] == 'ANNUALIZED_HALF_YEAR_SENSITIVITY'
        if annual and (operands[0]['unit'] != 'CNY_PER_SHARE' or not re.fullmatch(r'\d{4}H1', operands[0]['period'])):
            _fail('HALF_YEAR_EPS_REQUIRED')
        result[row['id']] = {**row, 'value': value,
            'unit': 'RATIO' if row['operator'] == 'RATIO' else 'PCT' if row['operator'] == 'GROWTH_PCT' else operands[0]['unit'],
            'period': operands[0]['period'],
            'status': 'DATA_BLOCKED_ZERO_DENOMINATOR' if value is None else 'ARITHMETIC_ONLY',
            'warning': 'SENSITIVITY_NOT_NORMALIZED_EPS_OR_FORECAST' if annual else 'SOURCE_INTERPRETATION_UNVERIFIED'}
    return result


def _responses(rows, questions, facts, calculations):
    ids = _rows(rows, 'claim_id', maximum=16)
    # governance-mutation: CONTENT_QUESTION_COVERAGE
    if set(ids) != {question['id'] for question in questions}:
        _fail('QUESTION_COVERAGE')
    result = []
    for row in rows:
        materials._exact(row, {'claim_id', 'assessment', 'fact_ids', 'calculation_ids',
                              'reasoning', 'counterevidence', 'missing_evidence'})
        if row['assessment'] not in {'SUPPORTS', 'CHALLENGES', 'MIXED', 'UNRESOLVED'}:
            _fail('ASSESSMENT_INVALID')
        _refs(row['fact_ids'], facts)
        _refs(row['calculation_ids'], calculations, empty=True)
        if any(not set(calculations[key]['operands']) <= set(row['fact_ids']) for key in row['calculation_ids']):
            _fail('RESPONSE_OPERANDS_MISSING')
        material._string(row['reasoning'], 4000)
        _notes(row['counterevidence']); _notes(row['missing_evidence'])
        question = next(question for question in questions if question['id'] == row['claim_id'])
        result.append({**row, 'question': question['question'], 'original_criteria': question['criteria'],
                       'original_citations': question['citations'],
                       'status': 'AI_ASSERTION_NOT_THESIS_SCORE', 'human_review': 'PENDING'})
    return result


def _valuation(value, facts):
    common = {'adapter': 'SEMICONDUCTOR_NORMALIZED_EARNINGS', 'formula': 'normalized_eps * fair_multiple + net_cash_per_share',
              'target_price': False, 'calibrated': False, 'human_review': 'PENDING'}
    if value is None:
        return {**common, 'status': 'DATA_BLOCKED', 'value_band': None,
                'missing_inputs': sorted(VALUATION_INPUTS),
                'warning': 'Reported half-year EPS, nonrecurring exclusions and cash conversion do not establish normalized EPS.'}
    materials._exact(value, {'adapter', 'currency', 'assumptions'})
    if value['adapter'] != common['adapter'] or value['currency'] != 'CNY':
        _fail('VALUATION_ADAPTER')
    materials._exact(value['assumptions'], VALUATION_INPUTS)
    numbers = {}
    for key, item in value['assumptions'].items():
        materials._exact(item, {'value', 'basis', 'fact_ids'})
        material._string(item['basis'], 2000)
        _refs(item['fact_ids'], facts)
        numbers[key] = _number(item['value'])
    if (numbers['normalized_eps'] <= 0 or numbers['fair_multiple_low'] <= 0
            or numbers['fair_multiple_low'] >= numbers['fair_multiple_high']):
        _fail('VALUATION_RANGE')
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        band = {side: _decimal(numbers['normalized_eps'] * numbers['fair_multiple_' + side] + numbers['net_cash_per_share'])
                for side in ('low', 'high')}
    if Decimal(band['low']) <= 0:
        _fail('VALUATION_RANGE')
    return {**common, 'status': 'SCENARIO_ONLY_UNCALIBRATED', 'assumptions': value['assumptions'],
            'assumptions_kind': 'ANALYST_ASSUMPTIONS_NOT_ISSUER_FACTS', 'currency': 'CNY',
            'value_band': {**band, 'unit': 'CNY_PER_SHARE'}}


def _technical(value, request):
    common = {'daily_workflow': 'MANUAL_EVIDENCE_REQUIRED', 'human_review': 'PENDING',
              'entry_stop_target': None, 'paper_registration_allowed': False}
    if value is None:
        return {**common, 'status': 'DATA_BLOCKED', 'rule': 'manual-smc-v1', 'timeframe': 'DAILY_CLOSED_RAW',
                'missing_inputs': ['Frozen daily OHLCV/calendar/actions', 'Bound daily SMC/timing evidence',
                                   'Settled flow, volume and sector confirmation', 'Structure entry/stop/target and after-cost R/R >= 2'],
                'warning': 'No minute inference from daily bars; no automatic daily strategy is claimed.'}
    materials._exact(value, {'input', 'input_hash'})
    from experiments.research_workflows import smc_ict_engine as engine
    payload = value['input']
    if type(payload) is not dict or payload.get('ticker') != request['company']:
        _fail('TECHNICAL_COMPANY')
    if materials._time(payload.get('as_of')) > materials._time(request['generated_at']):
        _fail('TECHNICAL_FUTURE')
    # governance-mutation: CONTENT_TECHNICAL_INPUT_PIN
    if engine.digest(payload) != value['input_hash']:
        _fail('TECHNICAL_PIN')
    receipt = engine.evaluate(payload)
    return {**common, 'status': receipt['status'], 'timeframe': 'EXISTING_INTRADAY_ENGINE_NOT_DAILY',
            'daily_workflow': 'NOT_EVALUATED', 'engine_receipt': receipt,
            'warning': 'Engine gates are supplied assertions, not authenticated observations. No manual timing PASS or paper authority follows.'}


def _bundle_snapshot(root, pin):
    materials._hash(pin)
    raw = ev.read_local(root, 'manifest.json')
    if ev.sha(raw) != pin:
        _fail('FEEDBACK_PIN')
    manifest = ev.parse(raw)
    artifacts = manifest.get('artifacts')
    if type(artifacts) is not dict or not 1 <= len(artifacts) <= 64:
        _fail('FEEDBACK_INVENTORY')
    actual = set()
    for count, path in enumerate(root.rglob('*')):
        if count >= 192 or path.is_symlink() or not (path.is_file() or path.is_dir()):
            _fail('FEEDBACK_INVENTORY')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(artifacts) | {'manifest.json'}:
        _fail('FEEDBACK_INVENTORY')
    files, total = {'manifest.json': raw}, len(raw)
    for name, expected in artifacts.items():
        materials._relative(name); materials._hash(expected)
        item = ev.read_local(root, name)
        # governance-mutation: CONTENT_FEEDBACK_SNAPSHOT_BYTES
        if name == 'manifest.json' or ev.sha(item) != expected:
            _fail('FEEDBACK_CHANGED')
        total += len(item)
        if total > 64 * 1024 * 1024:
            _fail('FEEDBACK_SIZE_LIMIT')
        files[name] = item
    return files


def _feedback(value, request, cycle_root, closure_root):
    if value is None:
        if cycle_root is not None or closure_root is not None:
            _fail('UNREQUESTED_FEEDBACK')
        return {'status': 'NOT_SUPPLIED', 'registration_status': 'NOT_ATTESTED', 'pnl': None,
                'axes': {axis: {'status': 'NOT_EVALUATED'} for axis in ('thesis', 'valuation', 'timing', 'execution', 'portfolio')},
                'missing_inputs': ['Pinned registered cycle and closure bundle', 'Later period-bound outcomes and settled execution evidence'],
                'warning': 'Missing evidence is not zero P&L, no orders, or a completed paper cycle.'}
    materials._exact(value, {'cycle_manifest_sha256', 'closure_manifest_sha256'})
    if cycle_root is None or closure_root is None:
        _fail('FEEDBACK_ROOTS_REQUIRED')
    roots = [materials._root(cycle_root), materials._root(closure_root)]
    pins = [value['cycle_manifest_sha256'], value['closure_manifest_sha256']]
    snapshots = [_bundle_snapshot(root, pin) for root, pin in zip(roots, pins)]
    from experiments.research_funnel import research_cycle
    # Existing validators replay only immutable private copies, never mutable source roots.
    with tempfile.TemporaryDirectory(prefix='ar-content-feedback-') as temporary:
        copies = [Path(temporary).resolve() / str(index) for index in range(2)]
        for snapshot, target in zip(snapshots, copies):
            for name, raw in snapshot.items():
                backup.write_new(target / name, raw)
        try:
            verified = research_cycle.verify_cycle_bundle(*copies)
        except research_cycle.CycleError as exc:
            raise ev.EvidenceError('RESEARCH_CONTENT_FEEDBACK_INVALID') from exc
    case, score, outcomes = [ev.parse(snapshots[0][name]) for name in ('prospective_case.json', 'method_scorecard.json', 'method_outcomes.json')]
    if case['ticker'] != request['company'] or score['ticker'] != request['company']:
        _fail('FEEDBACK_COMPANY')
    if materials._time(score['generated_at']) > materials._time(request['generated_at']):
        _fail('FEEDBACK_FUTURE')
    if research_cycle.method_contract._date8(outcomes['scoring_as_of'], 'scoring_as_of') > request['as_of']:
        _fail('FEEDBACK_FUTURE')
    return {'status': verified['status'], 'scope': 'EXISTING_OFFLINE_CYCLE_NOT_LIVE_EXECUTION_ATTESTATION',
            'pins': value, 'cycle': verified, 'registration_status': 'OFFLINE_REPLAY_ONLY',
            'draft_linkage': 'SAME_TICKER_HISTORY_NOT_CURRENT_DRAFT_REGISTRATION',
            'axes': {axis: score[axis] for axis in ('thesis', 'valuation', 'timing', 'execution', 'portfolio')},
            'pnl': score['pnl'], 'claim_allowed': False}


def build(request, pack_root, pack_hash, *, cycle_root=None, closure_root=None):
    if type(request) is dict and request.get('schema') == SCHEMA_V2 and type(request.get('technical')) is dict:
        import research_daily
        research_daily.bounded_bytes(request['technical'].get('observation'))
    request = ev.parse(ev.canonical(request).encode())
    reject_credentials(request)
    materials._exact(request, KEYS)
    if request['schema'] not in (SCHEMA, SCHEMA_V2) or request['pack_hash'] != pack_hash:
        _fail('SCHEMA_OR_PIN')
    source, read = _pack(materials._root(pack_root), pack_hash)
    if request['company'] != source['company']:
        _fail('COMPANY')
    day = materials._date(request['as_of'])
    stamp = materials._time(request['generated_at'])
    if (stamp.astimezone(material.timezone(timedelta(hours=8))).date() != day
            or stamp < materials._time(source['generated_at'])):
        _fail('DRAFT_DATE')
    materials._exact(request['authoring'], {'kind', 'model', 'prompt_version'})
    if request['authoring']['kind'] != 'AI_DRAFT':
        _fail('AI_DRAFT_REQUIRED')
    for key in ('model', 'prompt_version'):
        material._string(request['authoring'][key], 200)
    # governance-mutation: CONTENT_V2_FACT_CAPACITY
    facts = _facts(request['facts'], read, maximum=96 if request['schema'] == SCHEMA_V2 else 64)
    calculations = _calculations(request['calculations'], facts)
    responses = _responses(request['responses'], source['questions'], facts, calculations)
    valuation = _valuation(None, facts) if request['schema'] == SCHEMA_V2 else _valuation(request['valuation'], facts)
    technical = _technical(None, request) if request['schema'] == SCHEMA_V2 else _technical(request['technical'], request)
    if request['schema'] == SCHEMA_V2:
        if request['valuation'] is not None:
            import research_valuation
            valuation = research_valuation.evaluate(request['valuation'], facts, read=read,
                company=request['company'], generated_at=request['generated_at'],
                financial_cutoff_at=source['source_cutoff_at'])
        if request['technical'] is not None:
            import research_daily
            value = request['technical']
            materials._exact(value, {'adapter', 'observation', 'observation_hash'})
            if value['adapter'] != 'LEGACY_FEATURE_STORE_DAILY_V1':
                _fail('DAILY_ADAPTER')
            technical = research_daily.adapt(value['observation'], value['observation_hash'], request['company'], request['generated_at'])
    return {'schema': 'ar.research-content-cards.v2' if request['schema'] == SCHEMA_V2 else 'ar.research-content-cards.v1', 'company': request['company'],
            'research_date': request['as_of'], 'generated_at': request['generated_at'],
            'material_cutoff_at': source['source_cutoff_at'], 'pack_hash': pack_hash,
            'registration_status': 'NEW_DRAFT_NOT_PREREGISTERED', 'authoring': request['authoring'],
            'source_authenticity': 'UNVERIFIED', 'rights': dict(materials.RIGHTS),
            'facts': {'status': 'CITED_DRAFT_NOT_HUMAN_VERIFIED', 'observations': list(facts.values()),
                      'calculations': list(calculations.values()), 'responses': responses},
            'valuation': valuation, 'technical': technical,
            'execution_feedback': _feedback(request['feedback'], request, cycle_root, closure_root), **LABELS}


def report(cards):
    lines = ['# Research Content Draft', cards['company'],
        'WORKFLOW_DEBUG; AI draft; human review PENDING; no U4, paper or trading authority.',
        'Research date: ' + cards['research_date'], 'Original material cutoff: ' + cards['material_cutoff_at'],
        'Hash checks verify bytes, not issuer authenticity, financial interpretation or source rights.',
        '## 1. Fact Responses']
    for row in cards['facts']['observations']:
        lines += [f"### {row['id']}", f"{text(row['metric'])}: {row['value']} {row['unit']} / {text(row['period'])}",
                  f"Physical page {row['citation']['page']}, lines {row['citation']['start']}-{row['citation']['end']}; source SHA256 {row['citation']['sha256']}",
                  text(row['citation']['expected']), 'SOURCE_BYTES_VERIFIED_SEMANTICS_UNVERIFIED / E3']
    for row in cards['facts']['calculations']:
        lines += [f"{row['id']}: {text(row['operator'])} {text(row['operands'])} = {row['value']} {row['unit']}; {row['warning']}"]
    for row in cards['facts']['responses']:
        lines += [f"### {row['claim_id']} / {row['assessment']} (AI assertion, not thesis score)", text(row['question']),
                  text(row['reasoning']), 'Counterevidence: ' + text(row['counterevidence']),
                  'Still needed: ' + text(row['missing_evidence'])]
        for citation in row['original_citations']:
            lines += [f"Original question evidence: physical page {citation['page']}, lines {citation['start']}-{citation['end']}, SHA256 {citation['sha256']}", text(citation['expected'])]
    for heading, key in [('2. Valuation', 'valuation'), ('3. Technical Strategy', 'technical'), ('4. Execution Feedback', 'execution_feedback')]:
        lines += ['## ' + heading, text(cards[key])]
    lines += ['Not a trading instruction; research signal, human executes.']
    return ('\n\n'.join(lines) + '\n').encode('utf-8')


def create(request, pack_root, pack_hash, output_root, *, cycle_root=None, closure_root=None):
    observed = materials._time(_observed_at())
    if (materials._time(request['generated_at']) > observed
            or materials._date(request['as_of']) != observed.astimezone(material.timezone(timedelta(hours=8))).date()):
        _fail('OBSERVED_DATE')
    output = materials._root(output_root)
    for protected in (pack_root, cycle_root, closure_root):
        if protected is not None:
            root = materials._root(protected)
            if root == output or root in output.parents or output in root.parents:
                _fail('ROOT_OVERLAP')
    identity = _execution_identity()
    cards = build(request, pack_root, pack_hash, cycle_root=cycle_root, closure_root=closure_root)
    files = {'request.json': ev.canonical(request).encode(), 'cards.json': ev.canonical(cards).encode(), 'report.md': report(cards)}
    if _execution_identity() != identity:
        _fail('CODE_CHANGED')
    manifest = {'schema': 'ar.research-content-manifest.v1', 'pack_hash': pack_hash,
                'created_at': observed.isoformat(), 'execution_identity': identity,
                'files': {name: ev.sha(raw) for name, raw in files.items()}, **LABELS}
    manifest['content_hash'] = ev.sealed(manifest)
    manifest_raw = ev.canonical(manifest).encode()
    # governance-mutation: CONTENT_OUTPUT_SIZE_PREFLIGHT
    if any(len(raw) > ev.MAX_FILE for raw in (*files.values(), manifest_raw)):
        _fail('OUTPUT_SIZE')
    materials._create_private_root(output)
    for name, raw in files.items():
        backup.write_new(output / name, raw)
    backup.write_new(output / 'content-manifest.json', manifest_raw)
    return verify(output, manifest['content_hash'], pack_root, pack_hash, cycle_root=cycle_root, closure_root=closure_root)


def verify(output_root, content_hash, pack_root, pack_hash, *, cycle_root=None, closure_root=None):
    root = materials._root(output_root)
    manifest = ev.parse(ev.read_local(root, 'content-manifest.json'))
    materials._exact(manifest, {'schema', 'pack_hash', 'created_at', 'execution_identity', 'files', 'content_hash', *LABELS})
    body = {key: value for key, value in manifest.items() if key != 'content_hash'}
    materials._hash(content_hash); materials._hash(pack_hash)
    materials._exact(manifest['execution_identity'], {'code_sha', 'source_tree_hash'})
    materials._hash(manifest['execution_identity']['code_sha'], 40)
    materials._hash(manifest['execution_identity']['source_tree_hash'])
    created_at = materials._time(manifest['created_at'])
    # governance-mutation: CONTENT_OUTPUT_PIN
    if (manifest['schema'] != 'ar.research-content-manifest.v1' or manifest['content_hash'] != content_hash
            or ev.sealed(body) != content_hash or manifest['pack_hash'] != pack_hash
            or any(type(manifest[key]) is not type(value) or manifest[key] != value for key, value in LABELS.items())):
        _fail('OUTPUT_PIN')
    materials._exact(manifest['files'], {'request.json', 'cards.json', 'report.md'})
    if {path.name for path in root.iterdir()} != {*manifest['files'], 'content-manifest.json'}:
        _fail('OUTPUT_INVENTORY')
    raw = {name: ev.read_local(root, name) for name in manifest['files']}
    if any(ev.sha(raw[name]) != pin for name, pin in manifest['files'].items()):
        _fail('OUTPUT_FILE_HASH')
    request = ev.parse(raw['request.json'])
    if (materials._time(request['generated_at']) > created_at
            or materials._date(request['as_of']) != created_at.astimezone(material.timezone(timedelta(hours=8))).date()):
        _fail('OBSERVED_DATE')
    cards = build(request, pack_root, pack_hash, cycle_root=cycle_root, closure_root=closure_root)
    # governance-mutation: CONTENT_OUTPUT_DERIVATION
    if raw['cards.json'] != ev.canonical(cards).encode() or raw['report.md'] != report(cards):
        _fail('OUTPUT_DERIVATION')
    return {'schema': 'ar.research-content-receipt.v1', 'content_hash': content_hash, 'pack_hash': pack_hash,
            'report_sha256': ev.sha(raw['report.md']), 'company': cards['company'],
            'research_date': cards['research_date'], 'material_cutoff_at': cards['material_cutoff_at'],
            'card_statuses': {key: cards[key]['status'] for key in ('facts', 'valuation', 'technical', 'execution_feedback')}, **LABELS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('create', 'verify'))
    parser.add_argument('--pack', required=True, type=Path)
    parser.add_argument('--pack-hash', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--request', type=Path)
    parser.add_argument('--content-hash')
    parser.add_argument('--cycle', type=Path)
    parser.add_argument('--closure', type=Path)
    args = parser.parse_args()
    kwargs = {'cycle_root': args.cycle, 'closure_root': args.closure}
    if args.action == 'create':
        if args.request is None:
            parser.error('--request required')
        value = create(ev.parse(ev.read_local(args.request.parent, args.request.name)), args.pack, args.pack_hash, args.output, **kwargs)
    else:
        if args.content_hash is None:
            parser.error('--content-hash required')
        value = verify(args.output, args.content_hash, args.pack, args.pack_hash, **kwargs)
    print(ev.canonical(value))


if __name__ == '__main__':
    main()
