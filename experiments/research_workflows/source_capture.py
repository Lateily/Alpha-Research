#!/usr/bin/env python3
"""Opt-in, bounded source snapshots. Listings are not financial thesis verdicts."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from research_workflows import followup
    from research_workflows.evidence import TrialError, canonical, date8, exact, sha, text, timestamp
else:
    from . import followup
    from .evidence import TrialError, canonical, date8, exact, sha, text, timestamp

SourceError = TrialError
CODES = ('002119.SZ', '600667.SH', '688035.SH')
CN = timezone(timedelta(hours=8))
MAX_BYTES = 4 * 1024 * 1024
MAX_CALLS = 17  # Six price/factor calls, two catalogs, at most nine listing pages.
MAX_PAGES = 3
SOURCE_SCHEMA = 'ar.workflow-sources.v2'
LEGACY_SOURCE_SCHEMA = 'ar.workflow-sources.v1'
FIELDS = {
    'daily': ('ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'vol', 'amount'),
    'adj_factor': ('ts_code', 'trade_date', 'adj_factor'),
}
URLS = {'daily': 'https://api.tushare.pro', 'adj_factor': 'https://api.tushare.pro',
        'sz_catalog': 'https://www.cninfo.com.cn/new/data/szse_stock.json',
        'sh_catalog': 'https://www.cninfo.com.cn/new/data/szse_stock.json',
        'announcements': 'https://www.cninfo.com.cn/new/hisAnnouncement/query'}
ERROR_CATEGORIES = frozenset({'HTTP_ERROR', 'DNS_ERROR', 'TIMEOUT', 'TLS_CERTIFICATE_ERROR',
                             'TLS_ERROR', 'CONNECTION_ERROR', 'INCOMPLETE_RESPONSE',
                             'HTTP_PROTOCOL_ERROR', 'NETWORK_ERROR', 'POLICY_REFUSED'})


def safe_error(exc):
    # Never classify by provider text: URLs, headers and reasons can contain secrets.
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        exc = exc.reason
    status = None
    if isinstance(exc, urllib.error.HTTPError) and type(exc.code) is int and 100 <= exc.code <= 599:
        category, status = 'HTTP_ERROR', exc.code
    elif isinstance(exc, socket.gaierror):
        category = 'DNS_ERROR'
    elif isinstance(exc, (TimeoutError, socket.timeout)):
        category = 'TIMEOUT'
    elif isinstance(exc, ssl.SSLCertVerificationError):
        category = 'TLS_CERTIFICATE_ERROR'
    elif isinstance(exc, ssl.SSLError):
        category = 'TLS_ERROR'
    elif isinstance(exc, ConnectionError):
        category = 'CONNECTION_ERROR'
    elif isinstance(exc, http.client.IncompleteRead):
        category = 'INCOMPLETE_RESPONSE'
    elif isinstance(exc, http.client.HTTPException):
        category = 'HTTP_PROTOCOL_ERROR'
    elif isinstance(exc, SourceError):
        category = 'POLICY_REFUSED'
    else:
        category = 'NETWORK_ERROR'
    return {'category': category, 'http_status': status}


def validate_diagnostic(record):
    # Historical v1 exchanges lack diagnostics; do not invent a cause for them.
    if 'diagnostic' not in record:
        return
    value = record['diagnostic']
    if not isinstance(value, dict) or set(value) != {'category', 'http_status'}:
        raise SourceError('ERROR_DIAGNOSTIC_INVALID')
    category, status = value['category'], value['http_status']
    if not isinstance(category, str) or category not in ERROR_CATEGORIES:
        raise SourceError('ERROR_DIAGNOSTIC_INVALID')
    if (category == 'HTTP_ERROR' and not (type(status) is int and 100 <= status <= 599)
            or category != 'HTTP_ERROR' and status is not None
            or record['error'] != ('SOURCE_REFUSED' if category == 'POLICY_REFUSED' else 'SOURCE_FAILED')
            or record['body'] is not None or record['sha256'] is not None):
        raise SourceError('ERROR_DIAGNOSTIC_INVALID')


def validate_exchange_record(record, schema):
    base = {'request', 'body', 'sha256', 'error'}
    if not isinstance(record, dict) or set(record) not in (base, base | {'diagnostic'}):
        raise SourceError('EXCHANGE_RECORD_FIELDS_INVALID')
    if record['error'] not in (None, 'SOURCE_FAILED', 'SOURCE_REFUSED'):
        raise SourceError('EXCHANGE_RECORD_STATUS_INVALID')
    if record['error'] is None:
        if 'diagnostic' in record:
            raise SourceError('EXCHANGE_RECORD_FIELDS_INVALID')
    else:
        if record['body'] is not None or record['sha256'] is not None:
            raise SourceError('EXCHANGE_FAILURE_PAYLOAD_INVALID')
    validate_diagnostic(record)


def load(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SourceError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result

    def constant(_):
        raise SourceError('NONFINITE_JSON')

    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        pending = [result]
        while pending:
            value = pending.pop()
            if isinstance(value, str):
                value.encode('utf-8')
            elif isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        return result
    except SourceError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise SourceError('INVALID_JSON') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError('REDIRECT_REFUSED')


class HttpTransport:
    def __init__(self, token='', *, enabled=False):
        if not enabled or os.environ.get('AR_OFFLINE') == '1':
            raise SourceError('explicit network opt-in required; AR_OFFLINE must not be 1')
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, op, params):
        if op not in URLS:
            raise SourceError('ENDPOINT_REFUSED')
        headers = {'User-Agent': 'AR-workflow-source-check/1', 'Accept': 'application/json'}
        body = None
        if op in FIELDS:
            if not self.token:
                raise SourceError('TOKEN_UNAVAILABLE')
            body = canonical({'api_name': op, 'token': self.token, 'params': params, 'fields': ','.join(FIELDS[op])})
            headers['Content-Type'] = 'application/json'
        elif op == 'announcements':
            body = urllib.parse.urlencode(params).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        return urllib.request.Request(URLS[op], data=body, headers=headers)

    def check_response(self, raw):
        if len(raw) > MAX_BYTES:
            raise SourceError('RESPONSE_TOO_LARGE')
        if self.token and self.token.encode() in raw:
            raise SourceError('SECRET_RESPONSE_REFUSED')
        pending = [load(raw)]
        while pending:
            value = pending.pop()
            if isinstance(value, str) and self.token and self.token in value:
                raise SourceError('SECRET_RESPONSE_REFUSED')
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        return raw

    def __call__(self, op, params):
        req = self.request(op, params)
        # No retries, no redirect, no environment URL override, TLS verification on.
        with self.opener.open(req, timeout=20) as response:
            if response.status != 200 or response.geturl() != URLS[op]:
                raise SourceError('HTTP_RESPONSE_REFUSED')
            return self.check_response(response.read(MAX_BYTES + 1))


class ExchangeLog:
    def __init__(self, transport=None, records=None, *, schema=SOURCE_SCHEMA):
        if schema not in (LEGACY_SOURCE_SCHEMA, SOURCE_SCHEMA):
            raise SourceError('SOURCE_SCHEMA_INVALID')
        if schema == LEGACY_SOURCE_SCHEMA and (transport is not None or records is None):
            raise SourceError('LEGACY_SOURCE_REPLAY_ONLY')
        self.schema = schema
        self.urls = dict(URLS)
        if schema == LEGACY_SOURCE_SCHEMA:
            self.urls['sh_catalog'] = 'https://www.cninfo.com.cn/new/data/sse_stock.json'
        self.transport = transport
        self.records = [] if records is None else records
        self.position = 0
        for record in self.records:
            validate_exchange_record(record, schema)

    def ask(self, op, params):
        if self.position >= MAX_CALLS:
            raise SourceError('REQUEST_BUDGET_EXHAUSTED')
        identity = {'operation': op, 'url': self.urls[op], 'params': params}
        if self.transport is None:
            if self.position >= len(self.records) or self.records[self.position]['request'] != identity:
                raise SourceError('EXCHANGE_REQUEST_BINDING_INVALID')
            record = self.records[self.position]
        else:
            try:
                raw = self.transport(op, params)
                if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
                    raise SourceError('RESPONSE_SIZE_OR_TYPE_INVALID')
                record = {'request': identity, 'body': base64.b64encode(raw).decode(), 'sha256': sha(raw), 'error': None}
            except (OSError, http.client.HTTPException, SourceError) as exc:
                # Provider messages/HTTP error bodies may echo credentials; never retain them.
                diagnostic = safe_error(exc)
                record = {'request': identity, 'body': None, 'sha256': None,
                          'error': 'SOURCE_REFUSED' if diagnostic['category'] == 'POLICY_REFUSED' else 'SOURCE_FAILED',
                          'diagnostic': diagnostic}
            self.records.append(record)
        self.position += 1
        if record['error'] is not None:
            raise SourceError(record['error'])
        try:
            raw = base64.b64decode(record['body'], validate=True)
        except (ValueError, TypeError):
            raise SourceError('INVALID_RESPONSE_ENCODING') from None
        if len(raw) > MAX_BYTES or sha(raw) != record['sha256']:
            raise SourceError('RESPONSE_HASH_INVALID')
        return load(raw)


def validate_request(request, checked_at, prior):
    exact(request, {'schema', 'before_date', 'after_date', 'announcement_start', 'announcement_end'}, 'source request')
    if request['schema'] != 'ar.workflow-source-request.v1':
        raise SourceError('REQUEST_SCHEMA_INVALID')
    for field in ('before_date', 'after_date', 'announcement_start', 'announcement_end'):
        date8(request[field])
    today = timestamp(checked_at).astimezone(CN).strftime('%Y%m%d')
    if not (request['before_date'] < request['after_date'] <= today
            and request['announcement_start'] <= request['announcement_end'] <= today):
        raise SourceError('REQUEST_DATE_RANGE_INVALID')
    if prior and (timestamp(prior['checked_at']) > timestamp(checked_at)
                  or prior['request']['announcement_start'] != request['announcement_start']
                  or prior['request']['announcement_end'] > request['announcement_end']
                  or prior['request']['after_date'] > request['after_date']):
        raise SourceError('HISTORY_SCOPE_OR_TIME_CHANGED')


def number(value, positive=False):
    try:
        finite = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise SourceError('NUMERIC_VALUE_UNAVAILABLE')
    if value < 0 or (positive and value == 0):
        raise SourceError('NUMERIC_VALUE_INVALID')
    return value


def table(payload, op, code, dates):
    if not isinstance(payload, dict) or type(payload.get('code')) is not int or payload['code'] != 0:
        raise SourceError('PROVIDER_ERROR')
    data = payload.get('data')
    if not isinstance(data, dict):
        raise SourceError('MALFORMED_TABLE')
    fields, rows = data.get('fields'), data.get('items')
    if (not isinstance(fields, list) or any(not isinstance(x, str) for x in fields)
            or len(fields) != len(set(fields)) or set(fields) != set(FIELDS[op]) or not isinstance(rows, list)):
        raise SourceError('TABLE_FIELDS_INVALID')
    result = {}
    for raw in rows:
        if not isinstance(raw, list) or len(raw) != len(fields):
            raise SourceError('TABLE_ROW_WIDTH_INVALID')
        row = dict(zip(fields, raw))
        if row['ts_code'] != code:
            raise SourceError('PRICE_IDENTITY_INVALID')
        day = date8(row['trade_date'])
        if not min(dates) <= day <= max(dates) or day in result:
            raise SourceError('PRICE_DATE_INVALID')
        result[day] = row
    if not set(dates).issubset(result):
        raise SourceError('PRICE_COVERAGE_MISSING')
    return {day: result[day] for day in dates}


def prices(log, code, request):
    dates = [request['before_date'], request['after_date']]
    params = {'ts_code': code, 'start_date': dates[0], 'end_date': dates[1]}
    daily = table(log.ask('daily', params), 'daily', code, dates)
    factors = table(log.ask('adj_factor', params), 'adj_factor', code, dates)
    rows = []
    for day in dates:
        row = daily[day]
        for field in ('open', 'high', 'low', 'close', 'pre_close'):
            number(row[field], positive=True)
        if not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
            raise SourceError('OHLC_INVALID')
        rows.append({k: row[k] for k in ('ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close')})
        rows[-1].update(volume_shares=number(number(row['vol']) * 100), amount_cny=number(number(row['amount']) * 1000),
                        adj_factor=number(factors[day]['adj_factor'], positive=True))
    comparable = rows[0]['adj_factor'] == rows[1]['adj_factor']
    delta = (rows[1]['close'] / rows[0]['close'] - 1) * 100 if comparable else None
    if delta is not None and not math.isfinite(delta):
        raise SourceError('PRICE_CHANGE_NONFINITE')
    return {'ts_code': code, 'status': 'COMPLETE', 'rows': rows, 'failure_reason': None,
            'comparison_status': 'RAW_PRICE_COMPARABLE' if comparable else 'CORPORATE_ACTION_REVIEW_REQUIRED',
            'close_change_pct': round(delta, 8) if comparable else None}


def org_id(catalog, code):
    rows = catalog.get('stockList') if isinstance(catalog, dict) else None
    if not isinstance(rows, list):
        raise SourceError('CATALOG_UNAVAILABLE')
    matched = [r for r in rows if isinstance(r, dict) and r.get('code') == code[:6]]
    if len(matched) != 1 or not isinstance(matched[0].get('orgId'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', matched[0]['orgId']):
        raise SourceError('COMPANY_IDENTITY_UNAVAILABLE')
    return matched[0]['orgId']


def announcement(row, code, org, request, checked_at):
    if not isinstance(row, dict) or row.get('secCode') != code[:6] or row.get('orgId') != org:
        raise SourceError('ANNOUNCEMENT_IDENTITY_INVALID')
    ms = row.get('announcementTime')
    if type(ms) not in (int, float) or not 0 < ms < 10**14 or not math.isfinite(ms):
        raise SourceError('ANNOUNCEMENT_TIME_INVALID')
    dt = datetime.fromtimestamp(ms / 1000, tz=CN)
    day = dt.strftime('%Y%m%d')
    if not request['announcement_start'] <= day <= request['announcement_end'] or dt > timestamp(checked_at):
        raise SourceError('ANNOUNCEMENT_DATE_INVALID')
    doc, title, path = row.get('announcementId'), row.get('announcementTitle'), row.get('adjunctUrl')
    if not isinstance(doc, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', doc) or not isinstance(title, str) or not title.strip():
        raise SourceError('ANNOUNCEMENT_FIELDS_INVALID')
    if not isinstance(path, str) or not re.fullmatch(r'finalpage/[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Za-z0-9_-]+\.[Pp][Dd][Ff]', path):
        raise SourceError('PDF_LOCATION_INVALID')
    return {'id': doc, 'company': code, 'org_id': org, 'title': title, 'published_on': day,
            'published_at': dt.isoformat(), 'url': 'https://static.cninfo.com.cn/' + path, 'body_status': 'NOT_FETCHED'}


def announcements(log, code, org, request, checked_at):
    items, total = {}, None
    start = datetime.strptime(request['announcement_start'], '%Y%m%d').strftime('%Y-%m-%d')
    end = datetime.strptime(request['announcement_end'], '%Y%m%d').strftime('%Y-%m-%d')
    for page in range(1, MAX_PAGES + 1):
        params = {'stock': code[:6] + ',' + org, 'tabName': 'fulltext', 'pageSize': 100, 'pageNum': page,
                  'column': 'sse' if log.schema == LEGACY_SOURCE_SCHEMA and code.endswith('SH') else 'szse',
                  'plate': 'sz' if code.endswith('SZ') else 'sh',
                  'category': '', 'trade': '', 'seDate': start + '~' + end, 'searchkey': '', 'secid': '',
                  'sortName': '', 'sortType': '', 'isHLtitle': 'false'}
        data = log.ask('announcements', params)
        if (not isinstance(data, dict) or type(data.get('totalAnnouncement')) is not int
                or data['totalAnnouncement'] < 0 or type(data.get('hasMore')) is not bool
                or not isinstance(data.get('announcements'), list)):
            raise SourceError('PAGINATION_FIELDS_INVALID')
        count = data['totalAnnouncement']
        if total is not None and total != count:
            raise SourceError('INDEX_CHANGED_DURING_QUERY')
        total = count
        for raw in data['announcements']:
            row = announcement(raw, code, org, request, checked_at)
            if row['id'] in items:
                raise SourceError('REPEATED_ANNOUNCEMENT')
            items[row['id']] = row
        if not data['hasMore']:
            if len(items) != total:
                raise SourceError('ANNOUNCEMENT_COUNT_MISMATCH')
            return {'ts_code': code, 'status': 'NO_ANNOUNCEMENTS_IN_QUERY' if not items else 'LISTINGS_FOR_REVIEW',
                    'query_complete': True, 'pages': page, 'items': sorted(items.values(), key=lambda r: (r['published_on'], r['id'])),
                    'query_start': request['announcement_start'], 'query_end': request['announcement_end'],
                    'body_status': 'NOT_FETCHED', 'failure_reason': None}
        if not data['announcements'] or len(items) >= total:
            raise SourceError('PAGINATION_PROGRESS_INVALID')
    raise SourceError('PAGINATION_BUDGET_EXHAUSTED')


def derive(request, checked_at, log, mode, prior):
    validate_request(request, checked_at, prior)
    if prior and prior['source_mode'] != mode:
        raise SourceError('HISTORY_SOURCE_MODE_CHANGED')
    price_rows, announcement_rows, catalogs = [], [], {}
    for code in CODES:
        try:
            price_rows.append(prices(log, code, request))
        except SourceError as exc:
            price_rows.append({'ts_code': code, 'status': 'DATA_BLOCKED', 'failure_reason': str(exc),
                               'rows': [], 'comparison_status': 'DATA_BLOCKED', 'close_change_pct': None})
    for name in ('sz_catalog', 'sh_catalog'):
        try:
            catalogs[name] = log.ask(name, {})
        except SourceError:
            catalogs[name] = None
    for code in CODES:
        try:
            catalog = catalogs['sz_catalog' if code.endswith('SZ') else 'sh_catalog']
            row = announcements(log, code, org_id(catalog, code), request, checked_at)
        except SourceError as exc:
            row = {'ts_code': code, 'status': 'DATA_BLOCKED', 'failure_reason': str(exc), 'query_complete': False,
                   'query_start': request['announcement_start'], 'query_end': request['announcement_end'],
                   'pages': None, 'items': [], 'body_status': 'NOT_FETCHED'}
        previous = next((r for r in prior['announcements'] if r['ts_code'] == code and r['query_complete']), None) if prior else None
        if not row['query_complete']:
            change = 'UNDETERMINED'
        elif previous is None:
            change = 'INITIAL_INDEX'
        else:
            old = {r['id']: r for r in previous['items']}
            new = {r['id']: r for r in row['items']}
            if set(new) - set(old):
                change = 'NEW_LISTINGS_REVIEW_REQUIRED'
            elif old != new:
                change = 'REVISED_LISTINGS_REVIEW_REQUIRED'
            else:
                change = 'NO_LISTING_CHANGES'
        row['change'] = change
        announcement_rows.append(row)
    blocked = any(r['status'] == 'DATA_BLOCKED' for r in price_rows + announcement_rows)
    return {'schema': log.schema, 'sample_purpose': 'WORKFLOW_DEBUG', 'source_mode': mode,
            'request': request, 'checked_at': checked_at, 'subjects': list(CODES),
            'status': 'DATA_BLOCKED' if blocked else 'COLLECTED_FOR_REVIEW',
            'prices': price_rows, 'announcements': announcement_rows, 'human_review': 'PENDING',
            'thesis_status': 'UNRESOLVED', 'authority': dict(followup.AUTHORITY), 'claim_allowed': False,
            'previous_receipt_sha256': sha(canonical(prior)) if prior else None,
            'request_count': log.position, 'network_calls': log.position if mode == 'LIVE_READ_ONLY' else 0,
            'model_calls': 0, 'scheduler_enabled': False, 'filing_bodies_fetched': False}


def report(receipt):
    lines = ['# 三票价量与公告来源检查', f"状态：{receipt['status']}；{receipt['source_mode']} / WORKFLOW_DEBUG。",
             f"观察时间：{receipt['checked_at']}；价量比较 {receipt['request']['before_date']} 至 {receipt['request']['after_date']}。",
             '人工核验 PENDING，财报命题 UNRESOLVED；成功读取不代表研究结论成立。',
             '公告仅检查本次查询区间内的列表，未下载正文；列表不变不能证明 PDF 正文未修订。']
    for row in receipt['prices']:
        lines += [f"## {row['ts_code']} · 价量 {row['status']}", f"比较状态：{row['comparison_status']}；原因：{text(row['failure_reason'])}"]
        for bar in row['rows']:
            lines += [f"{bar['trade_date']}：收盘 {bar['close']}；成交量 {bar['volume_shares']} 股；成交额 {bar['amount_cny']} 元。"]
    for row in receipt['announcements']:
        lines += [f"## {row['ts_code']} · 公告 {row['status']}",
                  f"区间：{row['query_start']} 至 {row['query_end']}；查询完整：{row['query_complete']}；变更：{row['change']}；正文：NOT_FETCHED。",
                  f"失败原因：{text(row['failure_reason'])}"]
        for item in row['items']:
            lines += [f"- {item['published_on']} [{text(item['title'])}]({item['url']})；待核原文。"]
    return ('\n\n'.join(lines) + '\n\n不是买卖指令；研究信号，human executes。\n').encode()


def capture(request, output, checked_at, *, transport=None, allow_network=False, previous=None):
    prior = verify(previous) if previous else None
    validate_request(request, checked_at, prior)
    output = followup._destination(output, [Path.home() / 'ar-live', Path(__file__).resolve().parents[2]] + ([previous] if previous else []))
    mode = 'INJECTED_TRANSPORT_UNVERIFIED'
    if transport is None:
        transport = HttpTransport(os.environ.get('TUSHARE_TOKEN', ''), enabled=allow_network)
        mode = 'LIVE_READ_ONLY'
    log = ExchangeLog(transport)
    receipt = derive(request, checked_at, log, mode, prior)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.sources-', dir=output.parent))
    try:
        for name, data in {'receipt.json': receipt, 'request.json': request, 'previous.json': prior, 'exchanges.json': log.records}.items():
            (temp / name).write_bytes(canonical(data))
        (temp / 'status.md').write_bytes(report(receipt))
        followup._seal_inventory(temp)
        verify(temp)
        output.mkdir()
        for path in temp.iterdir():
            shutil.move(str(path), str(output / path.name))
        return receipt
    finally:
        shutil.rmtree(temp)


def verify(output):
    output = followup._plain_path(output)
    inventory = followup._inventory(output)
    if set(inventory) != {'receipt.json', 'request.json', 'previous.json', 'exchanges.json', 'status.md'}:
        raise SourceError('PACKAGE_FILE_SET_INVALID')
    expected = ''.join(f'{digest}  {name}\n' for name, digest in sorted(inventory.items()))
    if (output / 'SHA256SUMS').read_text() != expected:
        raise SourceError('PACKAGE_HASH_INVALID')
    receipt = load((output / 'receipt.json').read_bytes())
    request = load((output / 'request.json').read_bytes())
    prior = load((output / 'previous.json').read_bytes())
    records = load((output / 'exchanges.json').read_bytes())
    if receipt['source_mode'] not in {'LIVE_READ_ONLY', 'INJECTED_TRANSPORT_UNVERIFIED'}:
        raise SourceError('SOURCE_MODE_INVALID')
    log = ExchangeLog(records=records, schema=receipt['schema'])
    result = derive(request, receipt['checked_at'], log, receipt['source_mode'], prior)
    if log.position != len(records) or canonical(result) != canonical(receipt) or (output / 'status.md').read_bytes() != report(result):
        raise SourceError('RECEIPT_DIFFERS_FROM_REOPENED_RESPONSES')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check')
    check.add_argument('--request', required=True, type=Path)
    check.add_argument('--output', required=True, type=Path)
    check.add_argument('--previous', type=Path)
    check.add_argument('--live-read-only', action='store_true')
    reopen = commands.add_parser('verify')
    reopen.add_argument('--package', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            result = verify(args.package)
        else:
            result = capture(load(args.request.read_bytes()), args.output, datetime.now(timezone.utc).isoformat(),
                             allow_network=args.live_read_only, previous=args.previous)
        print(json.dumps({'status': result['status'], 'checked_at': result['checked_at'], 'human_review': result['human_review'],
                          'thesis_status': result['thesis_status'], 'request_count': result['request_count']}))
        return 2 if result['status'] == 'DATA_BLOCKED' else 0
    except (OSError, ValueError, KeyError, TypeError):
        print('REFUSED: source request/package unavailable or invalid; no approval or registration performed')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
