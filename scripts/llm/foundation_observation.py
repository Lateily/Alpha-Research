"""Operator-scoped, one-attempt source observation; never an automatic retry."""
from __future__ import annotations

import hashlib
import http.client
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.data_governance.endpoint_calls import EndpointSession, EndpointObservationError, read_endpoint_receipts
import workbench_evidence as ev
from workbench_backup import durable_directory, write_new

FIELDS = {'daily': ['close', 'trade_date', 'ts_code'],
          'moneyflow_dc': ['net_amount', 'trade_date', 'ts_code']}


def digest(value):
    return hashlib.sha256(ev.canonical(value).encode()).hexdigest()


def initial_grant():
    return {'schema': 'ar.source-observation-grant.v1', 'ts_code': '603629.SH',
            'trade_date': '20261104', 'apis': ['daily', 'moneyflow_dc'],
            'max_attempts_per_api': 1, 'approval_ref': 'Junyan-chat-20261105-initial',
            'previous_receipt_hash': None}


def _verify_receipt(value):
    if (not isinstance(value, dict) or value.get('schema') != 'ar.source-observation.v1'
            or value.get('receipt_hash') != digest({k: v for k, v in value.items() if k != 'receipt_hash'})):
        raise ValueError('OBSERVATION_RECEIPT_INVALID')
    return value


def retry_grant(previous, *, api_name, approval_ref):
    previous = _verify_receipt(previous)
    failed = {row['start']['api_name'] for row in previous['calls']
              if row['result']['dataset_quality'] != 'OBSERVED_SCOPE_VALID'}
    if api_name not in failed:
        raise ValueError('OBSERVATION_RETRY_REQUIRES_GAP')
    grant = initial_grant()
    grant.update(apis=[api_name], approval_ref=approval_ref,
                 previous_receipt_hash=previous['receipt_hash'])
    return grant


def _grant(value, expected, previous):
    initial = initial_grant()
    # governance-mutation: FOUNDATION_OBSERVATION_GRANT
    if (not isinstance(value, dict) or set(value) != set(initial)
            or digest(value) != expected or any(value[k] != initial[k] for k in
                ('schema', 'ts_code', 'trade_date', 'max_attempts_per_api'))
            or type(value['max_attempts_per_api']) is not int
            or not isinstance(value['approval_ref'], str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value['approval_ref'])):
        raise ValueError('OBSERVATION_GRANT_INVALID')
    if value['previous_receipt_hash'] is None:
        if value != initial or previous is not None:
            raise ValueError('OBSERVATION_INITIAL_SCOPE_INVALID')
    else:
        if previous is None or len(value['apis']) != 1:
            raise ValueError('OBSERVATION_RETRY_REQUIRES_GAP')
        if value != retry_grant(previous, api_name=value['apis'][0], approval_ref=value['approval_ref']):
            raise ValueError('OBSERVATION_RETRY_BINDING_INVALID')
    return value


def observe(root, grant, *, expected_grant_hash, invoke, previous=None):
    grant = _grant(grant, expected_grant_hash, previous)
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('OBSERVATION_ROOT_SYMLINK')
    durable_directory(root)
    generation = root / expected_grant_hash
    # O_EXCL is the durable one-use reservation. Interrupted runs are not reused.
    try:
        generation.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError('OBSERVATION_GRANT_ALREADY_CONSUMED') from None
    write_new(generation / 'grant.json', ev.canonical(grant).encode())
    session = EndpointSession(generation / 'endpoints', collector_run_id='scoped-' + expected_grant_hash[:32],
                              target_trade_date=grant['trade_date'])
    for api in grant['apis']:
        params = {'ts_code': grant['ts_code'], 'trade_date': grant['trade_date']}
        fields = FIELDS[api]
        try:
            session.observe(api, params, ','.join(fields), lambda: invoke(api, params, fields))
        except EndpointObservationError as error:
            if str(error) not in {'PERMISSION_DENIED', 'PARAM_ERROR', 'PROVIDER_ERROR',
                                  'SOURCE_DOWN', 'INVALID_RESPONSE'}:
                raise ValueError('OBSERVATION_RECORDING_INCOMPLETE') from None
    calls = read_endpoint_receipts(generation / 'endpoints')
    receipt = {'schema': 'ar.source-observation.v1', 'grant_hash': expected_grant_hash,
               # governance-mutation: FOUNDATION_OBSERVATION_GAPS
               'status': 'OBSERVED_SCOPE_VALID' if all(
                   row['result']['dataset_quality'] == 'OBSERVED_SCOPE_VALID' for row in calls) else 'DATA_BLOCKED',
               'calls': calls, 'research_readiness': 'NOT_EVALUATED', 'rights': 'UNVERIFIED',
               'approval_evidence': 'OPERATOR_PINNED_CHAT_REFERENCE_NOT_REMOTE_ATTESTATION',
               'automatic_retry': False, 'production_authority': False,
               'retry_status': 'SEPARATE_PRECISE_APPROVAL_REQUIRED'}
    receipt['receipt_hash'] = digest(receipt)
    write_new(generation / 'receipt.json', ev.canonical(receipt).encode())
    return receipt


def tushare_once(token):
    """Fixed host, one POST, no proxy/redirect/fallback, bounded read and timeout."""
    if not isinstance(token, str) or not token or len(token) > 512 or any(c.isspace() for c in token):
        raise ValueError('OBSERVATION_TOKEN_UNAVAILABLE')
    def invoke(api, params, fields):
        if api not in FIELDS or params != {'ts_code': '603629.SH', 'trade_date': '20261104'} or fields != FIELDS[api]:
            raise ValueError('OBSERVATION_TRANSPORT_SCOPE_INVALID')
        connection = http.client.HTTPSConnection('api.tushare.pro', timeout=20)
        try:
            raw = json.dumps({'api_name': api, 'token': token, 'params': params,
                              'fields': ','.join(fields)}).encode()
            connection.request('POST', '/', body=raw, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status in {401, 403}:
                raise PermissionError('OBSERVATION_PERMISSION_DENIED')
            if response.status != 200:
                raise OSError('OBSERVATION_HTTP_FAILED')
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise ValueError('OBSERVATION_RESPONSE_LIMIT')
            return ev.parse(body)
        finally:
            connection.close()
    return invoke
