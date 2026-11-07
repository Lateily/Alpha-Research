"""Opt-in legacy daily adapter, not a source certification or trading engine."""
from datetime import datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import math

import foundation_materials as materials
import workbench_evidence as ev
from experiments.research_workflows import smc_ict_input as strict
from experiments.research_workflows.smc_ict_concepts import atr_at, confirmed_pivots

SCOPE = 'SQLITE_MAIN_FILE_IMMUTABLE_READ_NOT_FULL_WAL_OR_PUBLICATION_ACCEPTANCE'
KEYS = {'schema', 'company', 'source_trade_date', 'captured_at', 'source_scope',
        'source_db_sha256_before_after', 'source_health_sha256', 'source_health_as_of',
        'wal_present_at_capture', 'wal_size_bytes', 'daily', 'moneyflow', 'adjustment_factors',
        'counts', 'daily_parser', 'atomic_observations', 'pending', 'human_review',
        'sample_purpose', 'source_authenticity', 'rights', 'production_authority',
        'paper_authority', 'trading_authority', 'claim_allowed', 'prospective_sample_eligible',
        'provider_calls', 'model_calls', 'observation_hash'}
MAX_OBSERVATION_BYTES = 512 * 1024


def _fail(reason):
    raise ev.EvidenceError('RESEARCH_DAILY_' + reason)


def shares(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < 2**40:
        _fail('VOLUME_INVALID')
    candidate = round(value)
    # Replay the declared producer; closeness alone is never evidence.
    # governance-mutation: DAILY_EXACT_REPLAY
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        if value != candidate and (float(Decimal(candidate) / 100) * 100.0).hex() != float(value).hex():
            _fail('VOLUME_NOT_PRODUCER_REPLAY')
    return candidate


def _quantity(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        _fail('QUANTITY_INVALID')
    number = Decimal(str(value))
    if number < 0 or (positive and number == 0):
        _fail('QUANTITY_INVALID')
    return number


def bounded_bytes(observation):
    """Fence shape before canonical serialization, including unused metadata."""
    pending, nodes, text_bytes = [(observation, 0)], 0, 0
    while pending:
        value, depth = pending.pop(); nodes += 1
        if depth > 10 or nodes > 20000:
            _fail('OBSERVATION_SIZE')
        if type(value) is dict:
            if len(value) > 64 or any(type(key) is not str for key in value):
                _fail('OBSERVATION_SIZE')
            pending.extend((item, depth + 1) for pair in value.items() for item in pair)
        elif type(value) is list:
            if len(value) > 512:
                _fail('OBSERVATION_SIZE')
            pending.extend((item, depth + 1) for item in value)
        elif type(value) is str:
            size = len(value.encode('utf-8')); text_bytes += size
            if size > 4096 or text_bytes > MAX_OBSERVATION_BYTES:
                _fail('OBSERVATION_SIZE')
        elif type(value) is int:
            if value.bit_length() > 1024:
                _fail('OBSERVATION_SIZE')
        elif type(value) not in (float, bool, type(None)):
            _fail('OBSERVATION_SIZE')
    raw = ev.canonical(observation).encode()
    # governance-mutation: DAILY_OBSERVATION_SIZE
    if len(raw) > MAX_OBSERVATION_BYTES:
        _fail('OBSERVATION_SIZE')
    return raw


def adapt(observation, pin, company, generated_at):
    # Retain a detached canonical snapshot before checking or deriving anything.
    source = ev.parse(bounded_bytes(observation))
    materials._exact(source, KEYS); materials._hash(pin)
    # governance-mutation: DAILY_OBSERVATION_PIN
    if source['observation_hash'] != pin or ev.sealed({k: v for k, v in source.items() if k != 'observation_hash'}) != pin:
        _fail('OBSERVATION_PIN')
    if (source['schema'] != 'ar.local-daily-context-observation.v1' or source['company'] != company
            or source['source_scope'] != SCOPE or source['source_authenticity'] != 'UNVERIFIED'
            or source['human_review'] != 'PENDING' or source['sample_purpose'] != 'WORKFLOW_DEBUG'
            or source['rights'] != 'UNVERIFIED_PRIVATE_LOCAL_ONLY'):
        _fail('SOURCE_SCOPE')
    for key in ('production_authority', 'paper_authority', 'trading_authority', 'claim_allowed', 'prospective_sample_eligible'):
        if source[key] is not False:
            _fail('AUTHORITY')
    for key in ('source_db_sha256_before_after', 'source_health_sha256'):
        materials._hash(source[key])
    for key in ('provider_calls', 'model_calls'):
        if type(source[key]) is not int or source[key] != 0:
            _fail('SOURCE_SCOPE')
    day = materials._date(source['source_trade_date'])
    end = datetime.combine(day, datetime.min.time().replace(hour=15), strict.SHANGHAI)
    captured = materials._time(source['captured_at'])
    # governance-mutation: DAILY_OBSERVATION_DATE
    if not end <= captured <= materials._time(generated_at) or source['source_health_as_of'] != source['source_trade_date']:
        _fail('OBSERVATION_DATE')
    if type(source['wal_present_at_capture']) is not bool:
        _fail('WAL_SCOPE')
    size = source['wal_size_bytes']
    if size is not None and (type(size) is not int or size < 0):
        _fail('WAL_SCOPE')
    materials._exact(source['counts'], {'daily', 'moneyflow', 'adjustment_factors'})
    for key in ('daily', 'moneyflow', 'adjustment_factors'):
        rows = source[key]
        if (type(rows) is not list or len(rows) > 512 or type(source['counts'][key]) is not int
                or source['counts'][key] != len(rows)):
            _fail('ROW_COUNT')
    bars, trace = [], []
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        for row in source['daily']:
            materials._exact(row, {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'volume_shares', 'amount_cny'})
            if any(type(row[key]) is str and len(row[key]) > 64 for key in ('open', 'high', 'low', 'close')):
                _fail('PRICE_REPRESENTATION_SIZE')
            volume = shares(row['volume_shares']); _quantity(row['amount_cny'])
            bars.append({'ts_code': row['ts_code'], 'date': row['trade_date'],
                         **{key: row[key] for key in ('open', 'high', 'low', 'close')}, 'volume': volume})
            trace.append({'date': row['trade_date'], 'source_value': row['volume_shares'],
                          'source_float_hex': float(row['volume_shares']).hex(), 'shares': volume,
                          'method': 'INTEGER_EXACT' if row['volume_shares'] == volume else 'EXACT_FLOAT64_LOTS_X100_REPLAY'})
        parsed = strict._parse_daily(bars, end, company)
        dates = [bar['date'] for bar in bars]
        factor_dates = []
        for row in source['adjustment_factors']:
            materials._exact(row, {'ts_code', 'trade_date', 'adj_factor'})
            if row['ts_code'] != company:
                _fail('FACTOR_IDENTITY')
            factor_dates.append(row['trade_date']); _quantity(row['adj_factor'], positive=True)
        # governance-mutation: DAILY_FACTOR_COVERAGE
        if factor_dates != dates:
            _fail('FACTOR_COVERAGE')
        flow_dates = []
        for row in source['moneyflow']:
            materials._exact(row, {'ts_code', 'trade_date', 'net_amount_cny', 'net_amount_rate', 'input_hash'})
            if row['ts_code'] != company or row['trade_date'] not in dates:
                _fail('FLOW_IDENTITY')
            materials._hash(row['input_hash']); flow_dates.append(row['trade_date'])
            for key in ('net_amount_cny', 'net_amount_rate'):
                if type(row[key]) not in (int, float) or not math.isfinite(row[key]):
                    _fail('FLOW_NUMBER')
        if flow_dates != sorted(set(flow_dates)):
            _fail('FLOW_ORDER')
        atr = atr_at(parsed, len(parsed) - 1)
        rendered = format(atr, 'f').rstrip('0').rstrip('.') if atr is not None and '.' in format(atr, 'f') else str(atr)
        observations = {'scope': 'RAW_DESCRIPTORS_NOT_DAILY_STRATEGY', 'atr14_raw': rendered if atr is not None else None,
                        'confirmed_pivots_2_left_2_right': confirmed_pivots(parsed, 2, 2)}
    return {'schema': 'ar.research-daily-card.v1', 'status': 'INPUT_ADAPTED_GATES_PENDING',
            'company': company, 'source_trade_date': source['source_trade_date'], 'captured_at': source['captured_at'],
            'observation_hash': pin, 'source_scope': SCOPE, 'source_authenticity': 'UNVERIFIED',
            'producer_rule': 'feature_store_float64_lots_x100.v1',
            'volume_scope': 'REGULAR_DAILY_AH_VOLUME_NOT_SUPPLIED', 'timeframe': 'DAILY_CLOSED_RAW',
            'daily_bars': bars, 'adjustment_factors': source['adjustment_factors'],
            'conversion_trace': trace, 'conversion_count': sum(row['method'] != 'INTEGER_EXACT' for row in trace),
            'observations': observations, 'entry_stop_target': None, 'human_review': 'PENDING',
            'paper_registration_allowed': False, 'daily_workflow': 'MANUAL_EVIDENCE_REQUIRED',
            'missing_inputs': ['Source/unit authenticity and PIT corporate actions', 'Daily strategy and manual timing evidence',
                               'Settled flow/sector interpretation', 'After-cost entry/stop/target R/R >= 2'],
            'warning': 'Input adaptation is not strategy acceptance, current market freshness or a minute signal.'}
