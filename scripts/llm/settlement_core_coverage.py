"""Read a fixed historical settlement acceptance matrix; never dispatch calls."""
import argparse
from pathlib import Path
import re
import sys
import tempfile

import core_source_closure as closure
import core_source_gaps as gaps
from experiments.data_governance.endpoint_calls import read_endpoint_receipts
import workbench_evidence as ev
from workbench_runtime_env import safe_path

DAY = '20261030'
STOCK = '603629.SH'
SCOPES = (
    ('stock-daily', 'daily', STOCK, 'close,trade_date,ts_code'),
    ('stock-flow', 'moneyflow_dc', STOCK, 'net_amount,trade_date,ts_code'),
    ('index-sh', 'index_daily', '000001.SH', 'pct_chg,trade_date,ts_code'),
    ('index-sz', 'index_daily', '399001.SZ', 'pct_chg,trade_date,ts_code'),
    ('index-cyb', 'index_daily', '399006.SZ', 'pct_chg,trade_date,ts_code'),
    ('market-flow', 'moneyflow_mkt_dc', None, 'net_amount,trade_date'),
)
NEW_SCOPES = frozenset({'stock-daily', 'index-sh', 'market-flow'})


def _scope(api, code, fields):
    params = {'trade_date': DAY}
    if code is not None:
        params['ts_code'] = code
    return {'api_name': api, 'params': params, 'fields': fields}


def plan_for_approval(approval_ref):
    if type(approval_ref) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', approval_ref):
        raise ValueError('SETTLEMENT_APPROVAL_REFERENCE')
    return {
        'schema': 'ar.settlement-core-plan.v1', 'approval_ref': approval_ref,
        'purpose': closure.PURPOSE, 'attempts_per_scope': 1, 'automatic_retry': False,
        'scopes': [_scope(api, code, fields) for key, api, code, fields in SCOPES if key in NEW_SCOPES],
    }


def _pinned_receipts(endpoints, files):
    expected_dirs = {str(parent) for name in files for parent in Path(name).parents if str(parent) != '.'}
    actual_dirs = {p.relative_to(endpoints).as_posix() for p in endpoints.rglob('*') if p.is_dir()}
    if actual_dirs != expected_dirs:
        raise ValueError('SETTLEMENT_CAPTURE_DIRECTORY_SHAPE')
    # The parser opens files by path. Stage exact verified bytes in a fresh
    # private directory, never pass it the externally supplied source paths.
    with tempfile.TemporaryDirectory(prefix='ar-settlement-pinned-') as tmp:
        held = Path(tmp).resolve()
        for name, expected in files.items():
            raw = ev.read_local(endpoints, name)
            if ev.sha(raw) != expected:
                raise ValueError('SETTLEMENT_CAPTURE_CHANGED')
            target = held / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        return read_endpoint_receipts(held)


def _capture(root, plan_pin, capture_pin, *, cutoff, not_before):
    root = safe_path(root)
    gaps._hash(plan_pin)
    gaps._hash(capture_pin)
    plan = ev.parse(ev.read_local(root, 'plan.json'))
    # governance-mutation: SETTLEMENT_PLAN_PIN
    if ev.sealed(plan) != plan_pin:
        raise ValueError('SETTLEMENT_PLAN_PIN')
    if ev.canonical(plan) != ev.canonical(plan_for_approval(plan['approval_ref'])):
        raise ValueError('SETTLEMENT_PLAN_SCOPE')
    raw = ev.read_local(root, 'capture.json')
    if ev.sha(raw) != capture_pin:
        raise ValueError('SETTLEMENT_CAPTURE_PIN')
    capture = ev.parse(raw)
    if (set(capture) != {'schema', 'plan_hash', 'sealed_at', 'evidence_hash'}
            or capture['schema'] != 'ar.settlement-core-capture.v1' or capture['plan_hash'] != plan_pin):
        raise ValueError('SETTLEMENT_CAPTURE_BINDING')
    sealed = gaps._time(capture['sealed_at'])
    endpoints = root / 'endpoints'
    # governance-mutation: SETTLEMENT_CAPTURE_ROOT
    if endpoints.is_symlink() or not endpoints.is_dir():
        raise ValueError('SETTLEMENT_CAPTURE_ENDPOINT_ROOT')
    files = gaps._inventory(endpoints)
    # governance-mutation: SETTLEMENT_CAPTURE_BYTES
    if ev.sealed(files) != capture['evidence_hash']:
        raise ValueError('SETTLEMENT_CAPTURE_BYTES')
    # governance-mutation: SETTLEMENT_CAPTURE_PARSE_PINNED
    rows = _pinned_receipts(endpoints, files)
    if gaps._inventory(endpoints) != files:
        raise ValueError('SETTLEMENT_CAPTURE_CHANGED')
    result = {}
    allowed = {ev.sealed(item) for item in plan['scopes']}
    for row in rows:
        start, terminal = row['start'], row['result']
        scope = {k: start[k] for k in ('api_name', 'params', 'fields')}
        key = ev.sealed(scope)
        # governance-mutation: SETTLEMENT_CAPTURE_SCOPE
        if key not in allowed or key in result:
            raise ValueError('SETTLEMENT_CAPTURE_SCOPE')
        invoked = gaps._time(start['invoked_at'])
        completed = terminal['completed_at']
        if (start['target_trade_date'] != DAY or start['collector_run_id'] != 'settlement-' + plan_pin[:32]
                or not not_before <= invoked <= sealed
                or completed is not None and not invoked <= gaps._time(completed) <= sealed):
            raise ValueError('SETTLEMENT_CAPTURE_TIME_OR_RUN')
        result[key] = ({
            'logical_call_id': start['logical_call_id'], 'completed_at': completed,
            'observation_time': completed or start['invoked_at'],
            'request_status': terminal['request_status'], 'quality': terminal['dataset_quality'],
            'gaps': terminal['gaps'], 'error_code': terminal['error_code'],
            'response_hash': terminal['response_hash'], 'catalog_hash': start['catalog_hash'],
        }, row, files)
    # governance-mutation: SETTLEMENT_CAPTURE_CUTOFF
    if sealed > cutoff:
        return {}, None
    return result, {'plan_hash': plan_pin, 'capture_sha256': capture_pin,
                    'sealed_at': capture['sealed_at'], 'approval_evidence': closure.APPROVAL_EVIDENCE}


def _reconcile(ledger, capture, legacy):
    history = legacy['history'] if legacy else []
    if capture is None:
        if not history:
            return 'NO_CALL_EVIDENCE'
        return None if legacy['status'] in {'VALID_SCOPE_OBSERVED', 'RECOVERED_SCOPE_OBSERVED'} else (
            'CONFLICTING_TIME_EVIDENCE' if legacy['status'] == 'CONFLICTING_TIME_EVIDENCE' else 'LEGACY_SCOPE_NOT_VALID')
    current, row, files = capture
    current_reason = None if current['quality'] == 'OBSERVED_SCOPE_VALID' else 'CAPTURE_NOT_SCOPE_VALID'
    if not history:
        return current_reason
    if any(old['logical_call_id'] == current['logical_call_id'] for old in history):
        if not closure._visible_call(ledger, legacy, row, {'files': files}):
            raise ValueError('SETTLEMENT_DUPLICATE_CALL_BINDING')
    now = gaps._time(current['observation_time'])
    latest = gaps._time(history[-1]['observation_time'])
    # governance-mutation: SETTLEMENT_CAPTURE_NEWER_LEDGER
    if latest > now:
        return _reconcile(ledger, None, legacy)
    # governance-mutation: SETTLEMENT_CAPTURE_TIME_CONFLICT
    if latest == now:
        observed = (current['request_status'], current['quality'], tuple(current['gaps']),
                    current['response_hash'], current['error_code'])
        for old in history:
            if gaps._time(old['observation_time']) == now and observed != (
                    old['request_status'], old['dataset_quality'], tuple(old['reasons']),
                    old['response_hash'], old['error_code']):
                return 'CONFLICTING_TIME_EVIDENCE'
    return current_reason


def project(ledger, *, expected_head, incident_path, incident_pin, observed_at,
            recheck_root=None, grant_pin=None, receipt_pin=None, consumption_marker=None,
            capture_root=None, plan_pin=None, capture_pin=None):
    required = [{'api_name': api, 'ts_code': code, 'trade_date': DAY, 'fields': fields}
                for key, api, code, fields in SCOPES if key in {'stock-flow', 'stock-daily'}]
    prior_scope = required[1]
    prior = closure.closure(
        ledger, required, expectation_pin=ev.sealed(required), expected_head=expected_head,
        observed_at=observed_at, incident_path=incident_path, incident_pin=incident_pin,
        incident_scope=ev.sealed(prior_scope), recheck_root=recheck_root, grant_pin=grant_pin,
        receipt_pin=receipt_pin, consumption_marker=consumption_marker)
    cutoff = gaps._time(observed_at)
    raw = closure._read(incident_path)
    if ev.sha(raw) != incident_pin:
        raise ValueError('SETTLEMENT_INCIDENT_CHANGED')
    original = ev.parse(raw)
    official = next(s for s in original['steps'] if s['step'] == 'official_sample')
    dates = closure._source_dates(official)
    _, not_before = closure._incident(incident_path, incident_pin, prior_scope, cutoff)
    captures, capture_ref = {}, None
    if any(x is not None for x in (capture_root, plan_pin, capture_pin)):
        if any(x is None for x in (capture_root, plan_pin, capture_pin)):
            raise ValueError('SETTLEMENT_CAPTURE_ARGUMENTS')
        captures, capture_ref = _capture(capture_root, plan_pin, capture_pin,
                                         cutoff=cutoff, not_before=not_before)
    prior_rows = {r['api_name']: r for r in prior['coverage']['scopes']}
    output = []
    for key, api, code, fields in SCOPES:
        scope = _scope(api, code, fields)
        original_date = dates.get(api, {}).get(code) if code else None
        if original_date is not None:
            gaps.datetime.strptime(original_date, '%Y%m%d')
        capture = captures.get(ev.sealed(scope))
        legacy = prior_rows.get(api)
        reason = _reconcile(ledger, capture, legacy)
        # Do not let a valid late observation set original availability or publication.
        output.append({'scope_id': key, **scope, 'original_date': original_date,
                       'original_role': 'CONTEXT_ONLY' if code is None else 'SETTLEMENT_DATE_GATE',
                       'status': 'OBSERVED_SCOPE_VALID' if reason is None else 'DATA_BLOCKED', 'reason': reason,
                       'receipt': capture[0] if capture is not None else None,
                       'legacy_history': legacy['history'] if legacy else []})
    valid = sum(row['status'] == 'OBSERVED_SCOPE_VALID' for row in output)
    return {'schema': 'ar.settlement-core-coverage.v1', 'as_of': prior['coverage']['observed_at'],
            'incident': prior['incident'], 'prior_authorized_recheck': prior['recheck'],
            'capture': capture_ref, 'scopes': output,
            'counts': {'expected': len(output), 'observed': sum(
                bool(row['receipt'] or row['legacy_history']) for row in output),
                'valid': valid, 'blocked': len(output) - valid},
            'status': 'OBSERVED_SCOPE_VALID' if valid == len(output) else 'DATA_BLOCKED',
            'original_run_repaired': False, 'dispatch_allowed': False, **gaps.LABELS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ledger', 'incident-path'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('expected-head', 'incident-pin', 'observed-at'):
        parser.add_argument('--' + name, required=True)
    for name in ('recheck-root', 'consumption-marker', 'capture-root'):
        parser.add_argument('--' + name, type=Path)
    for name in ('grant-pin', 'receipt-pin', 'plan-pin', 'capture-pin'):
        parser.add_argument('--' + name)
    args = vars(parser.parse_args())
    print(ev.canonical(project(args.pop('ledger'), **args)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError):
        print('SETTLEMENT_CORE_COVERAGE_REFUSED', file=sys.stderr)
        raise SystemExit(2)
