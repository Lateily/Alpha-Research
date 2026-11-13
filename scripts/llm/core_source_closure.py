"""Join an exact historical gap and consumed recheck without dispatch or repair."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

import core_source_gaps as gaps
import workbench_evidence as ev
from workbench_runtime_env import safe_path


PURPOSE = 'LATE_HISTORICAL_RECHECK_NOT_AS_KNOWN_THEN'
APPROVAL_EVIDENCE = 'OPERATOR_PINNED_CHAT_REFERENCE_NOT_REMOTE_ATTESTATION'
DOWNSTREAM = frozenset({
    'security_registry', 'feature_store', 'e1_event_layer', 'fwd_backfill', 'fund_daily_mark',
    'position_review', 'setup_promoter', 'court_10d', 'export_contracts', 'macro_m1c',
    'funnel_candidates', 'candidate_battery', 'funnel_finalize',
})


def _read(path):
    path = safe_path(path)
    return ev.read_local(path.parent, path.name)


def _source_dates(official):
    last = official['tail'].strip().splitlines()[-1]
    body, marker, source_dates = last.partition(' source_dates=')
    if not marker or not body.startswith('DATA_BLOCKED: settlement-date mismatch across sources '):
        raise ValueError('CLOSURE_NO_SETTLEMENT_DATE_EVIDENCE')
    return ev.parse(source_dates.encode())


def _incident(path, pin, scope, when):
    raw = _read(path)
    # governance-mutation: CORE_CLOSURE_INCIDENT_PIN
    if ev.sha(raw) != pin:
        raise ValueError('CLOSURE_INCIDENT_PIN_MISMATCH')
    value = ev.parse(raw)
    run_id = value['run_id']
    if (type(run_id) is not str or not re.fullmatch(r'[0-9]{8}_[0-9]{6}_[0-9]{10,22}_[0-9a-f]{8}', run_id)
            or value['target_trade_date'] is not None or value['published'] is not False
            or value['report'] != 'INCOMPLETE' or value['data_quality'] != 'DATA_BLOCKED'):
        raise ValueError('CLOSURE_INCIDENT_NOT_FAILED')
    london = ZoneInfo('Europe/London')
    generated = datetime.strptime(value['generated_at'], '%Y%m%d %H:%M')
    started = datetime.strptime(run_id[:15], '%Y%m%d_%H%M%S')
    # Original report clocks carry minute precision and London local time.
    # Ambiguous wall times cannot anchor the chronology of an approval.
    if generated.replace(tzinfo=london, fold=0).utcoffset() != generated.replace(tzinfo=london, fold=1).utcoffset():
        raise ValueError('CLOSURE_AMBIGUOUS_INCIDENT_TIME')
    not_before = generated.replace(tzinfo=london).astimezone(timezone.utc) + timedelta(minutes=1)
    if generated + timedelta(minutes=1) <= started or when < not_before:
        raise ValueError('CLOSURE_INCIDENT_NOT_YET_VISIBLE')
    if type(value['steps']) is not list or not 1 <= len(value['steps']) <= 64:
        raise ValueError('CLOSURE_INCIDENT_STEP_LIMIT')
    steps = {s['step']: s for s in value['steps']}
    if len(steps) != len(value['steps']):
        raise ValueError('CLOSURE_INCIDENT_DUPLICATE_STEP')
    official = steps['official_sample']
    if official['status'] != 'FAILED' or type(official['exit_code']) is not int or official['exit_code'] == 0:
        raise ValueError('CLOSURE_OFFICIAL_SAMPLE_NOT_FAILED')
    dates = _source_dates(official)
    api, code, day = (scope[k] for k in ('api_name', 'ts_code', 'trade_date'))
    companion = 'daily' if api == 'moneyflow_dc' else 'moneyflow_dc'
    stale = dates[api][code]
    if (type(stale) is not str or not re.fullmatch('[0-9]{8}', stale) or not stale < day
            or dates[companion][code] != day or not dates['index_daily']
            or set(dates['index_daily'].values()) != {day}):
        raise ValueError('CLOSURE_INCIDENT_SCOPE_MISMATCH')
    datetime.strptime(stale, '%Y%m%d')
    return {
        'run_id': run_id, 'original_sha256': pin, 'attempted_trade_date': day,
        'accepted_trade_date': None, 'observed_source_date': stale,
        'status': 'DATA_BLOCKED', 'reason': 'SETTLEMENT_SOURCE_DATE_MISMATCH',
        'published': False, 'failed_step': 'official_sample',
        'generated_at_london': value['generated_at'],
        'downstream_observations': {
            name: steps[name]['status'] for name in sorted(DOWNSTREAM & steps.keys())
            if steps[name]['status'] in {'SKIPPED_STALE_INPUT', 'DATA_BLOCKED', 'PARTIAL'}
        },
    }, not_before


def _visible_call(ledger, scope, row, source):
    call_id = row['start']['logical_call_id']
    binding = gaps._binding(row, source['files'])
    for observed in scope['history']:
        if observed['logical_call_id'] != call_id:
            continue
        # Ledger batches may contain other calls; the call's original
        # START, terminal, catalog and projection must still match exactly.
        batch_hash = gaps._hash(observed['evidence_hash'])
        batch = gaps.evidence(Path(ledger) / 'sources' / batch_hash)
        if batch['evidence_hash'] != batch_hash:
            raise ValueError('CLOSURE_LEDGER_BATCH_CHANGED')
        for candidate in batch['calls']:
            if candidate['start']['logical_call_id'] == call_id:
                # governance-mutation: CORE_CLOSURE_PER_CALL_BINDING
                # governance-mutation: CORE_CLOSURE_WRONG_TERMINAL
                if gaps._binding(candidate, batch['files']) == binding:
                    return True
                raise ValueError('CLOSURE_LEDGER_CALL_MISMATCH')
    return False


def _recheck(ledger, root, grant_pin, receipt_pin, marker, scope, not_before):
    root = safe_path(root)
    grant = ev.parse(ev.read_local(root, 'grant.json'))
    if ev.sealed(grant) != grant_pin:
        raise ValueError('CLOSURE_GRANT_PIN_MISMATCH')
    fields = grant['fields']
    approval = grant['approval_ref']
    expected = {
        'schema': 'ar.historical-recheck-grant.v1', 'api_name': scope['api_name'],
        'params': {k: scope[k] for k in ('ts_code', 'trade_date')},
        'fields': fields, 'max_attempts': 1, 'approval_ref': approval,
        'purpose': PURPOSE, 'automatic_retry': False, 'production_authority': False,
        'prospective_sample_eligible': False,
    }
    if (type(fields) is not list or not all(type(field) is str for field in fields)
            or ','.join(sorted(fields)) != scope['fields'] or type(approval) is not str
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', approval)
            or ev.canonical(grant) != ev.canonical(expected)):
        raise ValueError('CLOSURE_GRANT_SCOPE')

    receipt = ev.parse(ev.read_local(root, 'receipt.json'))
    unsealed = {k: v for k, v in receipt.items() if k != 'receipt_hash'}
    if receipt['receipt_hash'] != receipt_pin or ev.sealed(unsealed) != receipt_pin:
        raise ValueError('CLOSURE_RECEIPT_PIN_MISMATCH')
    # governance-mutation: CORE_CLOSURE_CONSUMPTION
    if ev.parse(_read(marker)) != {'receipt_hash': receipt_pin}:
        raise ValueError('CLOSURE_CONSUMPTION_MISMATCH')
    source = gaps.evidence(root / 'endpoints')
    if len(source['calls']) != 1:
        raise ValueError('CLOSURE_RECHECK_EXACTLY_ONE')
    row = source['calls'][0]
    start, result = row['start'], row['result']
    if (start['api_name'] != expected['api_name'] or start['params'] != expected['params']
            or start['fields'] != scope['fields']
            or start['collector_run_id'] != 'historical-' + grant_pin[:32]):
        raise ValueError('CLOSURE_RECHECK_CALL_BINDING')
    valid = result['dataset_quality'] == 'OBSERVED_SCOPE_VALID'
    expected_receipt = {
        'schema': 'ar.historical-recheck.v1', 'grant_hash': grant_pin, 'calls': source['calls'],
        'status': 'OBSERVED_SCOPE_VALID' if valid else 'DATA_BLOCKED',
        'purpose': PURPOSE, **gaps.LABELS, 'human_review': 'PENDING',
        'approval_evidence': APPROVAL_EVIDENCE,
    }
    if ev.canonical(unsealed) != ev.canonical(expected_receipt):
        raise ValueError('CLOSURE_RECHECK_TERMINAL_BINDING')
    # governance-mutation: CORE_CLOSURE_LATE_ONLY
    if gaps._time(start['invoked_at']) < not_before:
        raise ValueError('CLOSURE_RECHECK_NOT_LATE')
    history = scope['history']
    # governance-mutation: CORE_CLOSURE_VISIBLE_RECHECK
    if not _visible_call(ledger, scope, row, source):
        return {'status': 'AUTHORIZED_RECHECK_NOT_VISIBLE'}
    observation_time = gaps._time(result['completed_at'] or start['invoked_at'])
    if (scope['status'] == 'CONFLICTING_TIME_EVIDENCE'
            or (history and gaps._time(history[-1]['observation_time']) > observation_time)):
        status = 'AUTHORIZED_RECHECK_RECONCILIATION_REQUIRED'
    else:
        status = 'AUTHORIZED_LATE_SCOPE_OBSERVED' if valid else 'AUTHORIZED_RECHECK_STILL_BLOCKED'
    return {'status': status, 'grant_hash': grant_pin, 'receipt_hash': receipt_pin,
            'logical_call_id': start['logical_call_id'], 'completed_at': result['completed_at'],
            'approval_evidence': APPROVAL_EVIDENCE, 'max_attempts': 1,
            # governance-mutation: CORE_CLOSURE_MARKER_NOT_CUSTODY
            'consumption_marker_evidence': 'SUPPLIED_MARKER_MATCHES_RECEIPT_NOT_CUSTODY_ATTESTED'}


def closure(root, expected_scopes, *, expectation_pin, expected_head, observed_at, incident_path,
            incident_pin, incident_scope, recheck_root=None, grant_pin=None, receipt_pin=None,
            consumption_marker=None):
    """Project observed impact and recheck separately; neither can authorize action."""
    gaps._hash(incident_pin)
    gaps._hash(incident_scope)
    when = gaps._time(observed_at)
    coverage = gaps.coverage(root, expected_scopes, expected_scope_hash=expectation_pin,
                             expected_head=expected_head, observed_at=observed_at)
    matches = [row for row in coverage['scopes'] if row['gap_id'] == incident_scope]
    if len(matches) != 1:
        raise ValueError('CLOSURE_INCIDENT_SCOPE_NOT_EXPECTED')
    scope = matches[0]
    incident, not_before = _incident(incident_path, incident_pin, scope, when)
    recheck = {'status': 'NO_AUTHORIZED_RECHECK_EVIDENCE'}
    args = (recheck_root, grant_pin, receipt_pin, consumption_marker)
    if any(value is not None for value in args):
        if any(value is None for value in args):
            raise ValueError('CLOSURE_RECHECK_INPUTS_INCOMPLETE')
        gaps._hash(grant_pin)
        gaps._hash(receipt_pin)
        recheck = _recheck(root, *args, scope, not_before)
    return {'schema': 'ar.core-source-incident-closure.v1', 'gap_id': incident_scope,
            'incident': incident, 'coverage': coverage, 'recheck': recheck,
            'original_run_repaired': False, 'dispatch_allowed': False, **gaps.LABELS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('root', 'incident', 'expectations'):
        parser.add_argument('--' + flag, type=Path, required=True)
    for flag in ('head', 'incident-pin', 'scope-pin', 'incident-scope', 'observed-at'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--recheck-root', type=Path)
    parser.add_argument('--consumption-marker', type=Path)
    parser.add_argument('--grant-pin')
    parser.add_argument('--receipt-pin')
    args = parser.parse_args()
    request = ev.parse(_read(args.expectations))
    if set(request) != {'schema', 'scopes'} or request['schema'] != 'ar.core-source-expectations.v1':
        raise ValueError('CLOSURE_EXPECTATION_ENVELOPE')
    result = closure(args.root, request['scopes'], expectation_pin=args.scope_pin, expected_head=args.head,
                     observed_at=args.observed_at, incident_path=args.incident, incident_pin=args.incident_pin,
                     incident_scope=args.incident_scope, recheck_root=args.recheck_root,
                     grant_pin=args.grant_pin, receipt_pin=args.receipt_pin, consumption_marker=args.consumption_marker)
    print(ev.canonical(result))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError):
        print('CORE_SOURCE_CLOSURE_REFUSED', file=sys.stderr)
        raise SystemExit(2)
