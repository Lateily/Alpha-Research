"""Pure, source-bound daily evidence; never a calendar or trading approval."""
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
import re

import foundation_materials as materials
import research_content as content
import research_daily as daily
import workbench_evidence as ev

URL = 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml'
CAPTURE_FIELDS = {'file', 'url', 'final_url', 'http_status', 'content_type', 'bytes',
                  'sha256', 'observed_at', 'published_on', 'note'}
SHANGHAI = timezone(timedelta(hours=8))
HOLIDAYS = (
    ('\u4e00', '\u5143\u65e6', (1, 1), (1, 3), (1, 5), [(1, 4)]),
    ('\u4e8c', '\u6625\u8282', (2, 15), (2, 23), (2, 24), [(2, 14), (2, 28)]),
    ('\u4e09', '\u6e05\u660e\u8282', (4, 4), (4, 6), (4, 7), []),
    ('\u56db', '\u52b3\u52a8\u8282', (5, 1), (5, 5), (5, 6), [(5, 9)]),
    ('\u4e94', '\u7aef\u5348\u8282', (6, 19), (6, 21), (6, 22), []),
    ('\u516d', '\u4e2d\u79cb\u8282', (9, 25), (9, 27), (9, 28), []),
    ('\u4e03', '\u56fd\u5e86\u8282', (10, 1), (10, 7), (10, 8), [(9, 20), (10, 10)]),
)


def _fail(reason):
    raise ev.EvidenceError('DAILY_BASIS_' + reason)


def _read(read, name):
    try:
        raw = read(name)
    except (KeyError, OSError):
        _fail('SOURCE_READ')
    if type(raw) is not bytes or len(raw) > ev.MAX_FILE:
        _fail('SOURCE_SIZE')
    return raw


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs, self.parts, self.ignored, self.nodes = [], None, [], 0

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > 20000:
            _fail('HTML_SIZE')
        if tag in {'script', 'style'}:
            self.ignored.append(tag)
        if self.ignored:
            return
        if tag == 'p':
            if self.parts is not None:
                _fail('HOLIDAY_AMBIGUITY')
            self.parts = []

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == 'p' and self.parts is not None:
            self.paragraphs.append(''.join(''.join(self.parts).split()))
            self.parts = None

    def handle_data(self, value):
        if not self.ignored and self.parts is not None:
            self.parts.append(value)


def _day_text(pair):
    day = date(2026, *pair)
    weekday = '\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u65e5'[day.weekday()]
    return f'{day.month}\u6708{day.day}\u65e5\uff08\u661f\u671f{weekday}\uff09'


def _paragraph(row):
    ordinal, name, start, end, reopen, weekends = row
    text = (f'\uff08{ordinal}\uff09{name}\uff1a{_day_text(start)}\u81f3{_day_text(end)}'
            f'\u4f11\u5e02\uff0c{_day_text(reopen)}\u8d77\u7167\u5e38\u5f00\u5e02\u3002')
    if weekends:
        text += '\u53e6\u5916\uff0c' + '\u3001'.join(map(_day_text, weekends)) + '\u4e3a\u5468\u672b\u4f11\u5e02\u3002'
    return text


def _calendar(value, dates, generated):
    if value is None:
        return None
    materials._exact(value, {'raw_utf8', 'capture_receipt'})
    raw, receipt = value['raw_utf8'], value['capture_receipt']
    if type(raw) is not str or len(raw) > ev.MAX_FILE:
        _fail('CALENDAR_SIZE')
    try:
        encoded = raw.encode('utf-8')
    except UnicodeError:
        _fail('CALENDAR_ENCODING')
    if len(encoded) > ev.MAX_FILE:
        _fail('CALENDAR_SIZE')
    materials._exact(receipt, CAPTURE_FIELDS)
    materials._hash(receipt['sha256'])
    if (receipt['url'] != URL or receipt['final_url'] != URL
            or receipt['file'] != 'raw/sse_notice_2026_annual_20251222.shtml'
            or type(receipt['http_status']) is not int or receipt['http_status'] != 200
            or type(receipt['bytes']) is not int or receipt['bytes'] != len(encoded)
            or receipt['sha256'] != ev.sha(encoded)
            or receipt['published_on'] != '2025-12-22'
            or type(receipt['content_type']) is not str
            or re.fullmatch(r'text/html(?:;\s*charset=[Uu][Tt][Ff]-8)?', receipt['content_type']) is None
            or type(receipt['note']) is not str or len(receipt['note']) > 4096):
        _fail('CALENDAR_CAPTURE')
    captured = materials._time(receipt['observed_at'])
    publication_bound = datetime(2025, 12, 22, 23, 59, 59, tzinfo=SHANGHAI)
    if not publication_bound <= captured <= generated:
        _fail('CALENDAR_CHRONOLOGY')
    parser = _Paragraphs()
    parser.feed(raw); parser.close()
    holidays = [p for p in parser.paragraphs if re.match(r'^\uff08[\u4e00-\u9fff0-9]+\uff09', p)]
    if (parser.parts is not None or parser.ignored or holidays != list(map(_paragraph, HOLIDAYS))
            or not any('2026\u5e74' in p and '\u4f11\u5e02\u5b89\u6392' in p for p in parser.paragraphs)):
        _fail('HOLIDAY_AMBIGUITY')
    closed = set()
    for _, _, start, end, _, _ in HOLIDAYS:
        day, last = date(2026, *start), date(2026, *end)
        while day <= last:
            closed.add(day); day += timedelta(days=1)
    first, last = materials._date(dates[0]), materials._date(dates[-1])
    if first.year != 2026 or last.year != 2026:
        _fail('CALENDAR_YEAR')
    days, scheduled = [], []
    while first <= last:
        key = first.strftime('%Y%m%d'); opened = first.weekday() < 5 and first not in closed
        days.append({'trade_date': key, 'scheduled_open': opened})
        if opened:
            scheduled.append(key)
        first += timedelta(days=1)
    return {'status': 'SCHEDULE_CANDIDATE_NOT_CERTIFIED', 'days': days,
            'observed_date_comparison': 'MATCH' if scheduled == dates else 'DATA_CONFLICT',
            'missing_observed_dates': sorted(set(scheduled) - set(dates)),
            'unexpected_observed_dates': sorted(set(dates) - set(scheduled)),
            'source_sha256': receipt['sha256'], 'capture_receipt': dict(receipt),
            'suspension_coverage': 'UNKNOWN', 'emergency_closure_coverage': 'UNKNOWN',
            'technical_wiring': 'NOT_AUTHORIZED'}


def _action(action, facts, source_map, read, company, generated, first, last, coverage_end):
    materials._exact(action, {'effective_date', 'kind', 'fact_id', 'citation'})
    effective = materials._date(action['effective_date'])
    if effective > generated.astimezone(SHANGHAI).date() or (coverage_end is not None and effective > coverage_end):
        _fail('ACTION_DATE')
    if action['kind'] != 'SHARE_CANCELLATION' or type(action['fact_id']) is not str or action['fact_id'] not in facts:
        _fail('ACTION_REFERENCE')
    fact, citation = facts[action['fact_id']], action['citation']
    materials._exact(citation, {'sha256', 'page', 'start', 'end', 'expected'})
    materials._hash(citation['sha256'])
    if (type(fact) is not dict or fact.get('unit') != 'COUNT'
            or fact.get('period') not in {action['effective_date'], effective.isoformat()}
            or not isinstance(fact.get('citation'), dict)
            or fact['citation'].get('sha256') != citation['sha256']):
        _fail('ACTION_FACT_TYPE')
    quantity = content._number(fact.get('value'))
    if quantity <= 0 or quantity != quantity.to_integral_value():
        _fail('ACTION_QUANTITY')
    if (any(type(citation[k]) is not int or citation[k] < 1 for k in ('page', 'start', 'end'))
            or citation['page'] > 2048 or citation['end'] < citation['start']
            or type(citation['expected']) is not str):
        _fail('ACTION_QUOTE_RANGE')
    pin, page = citation['sha256'], citation['page']
    name = f'inputs/pages/{pin}-p{page}.txt'
    raw = _read(read, name)
    try:
        lines = raw.decode('utf-8').splitlines()
    except UnicodeError:
        _fail('ACTION_ENCODING')
    quote = '\n'.join(lines[citation['start'] - 1:citation['end']])
    if citation['end'] > len(lines) or quote != citation['expected']:
        _fail('ACTION_QUOTE')
    compact = ''.join(quote.split())
    source_dates = {date(int(y), int(m), int(d)) for y, m, d in re.findall(
        r'(20[0-9]{2})\u5e74([0-9]{1,2})\u6708([0-9]{1,2})\u65e5', compact)}
    source_dates.update(date.fromisoformat(s) for s in re.findall(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', compact))
    tokens = re.findall(r'(?<![0-9.,])((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)\s*\u80a1', quote)
    uncertain = re.search(r'(?:\u62df|\u672a|\u8ba1\u5212|\u5c06|\u4e0d\u4e88|\u4e0d\u4f1a)[^\u3002\uff1b;]{0,40}\u6ce8\u9500', compact)
    if (effective not in source_dates or '\u56de\u8d2d\u6ce8\u9500' not in compact or uncertain
            or not any(content._number(token.replace(',', '')) == quantity for token in tokens)):
        _fail('ACTION_SEMANTICS')
    try:
        documents = source_map['documents']; pages = source_map['pages']
        if source_map['schema'] != 'ar.material-research-provenance.v1' or type(documents) is not list or not 1 <= len(documents) <= 8 or type(pages) is not dict or len(pages) > 32:
            _fail('SOURCE_MAP')
        matches = [d for d in documents if d['selection']['sha256'] == pin]
        if len(matches) != 1:
            _fail('ACTION_SOURCE_BINDING')
        document = matches[0]; selection = document['selection']; material = document['material']
        metadata = pages[f'pdf-{pin}-p{page}']; original = f'inputs/originals/{pin}.pdf'
        if (material['ts_code'] != company or material['kind'] != 'original'
                or selection['material_id'] != material['material_id'] or selection['version'] != material['version']
                or page not in selection['pages'] or document['original_path'] != original
                or not any(f['sha256'] == pin for f in material['files'])
                or metadata['sha256'] != pin or metadata['physical_page'] != page
                or metadata['text_path'] != name or metadata['original_path'] != original
                or metadata['text_sha256'] != ev.sha(raw)):
            _fail('ACTION_SOURCE_BINDING')
        published = materials._time(material['published_at']); available = materials._time(material['available_at'])
        captured = materials._time(material['provenance']['captured_at'])
        if not published <= available <= captured <= generated:
            _fail('ACTION_SOURCE_CHRONOLOGY')
    except (KeyError, TypeError, IndexError):
        _fail('SOURCE_MAP')
    return {'effective_date': action['effective_date'], 'kind': action['kind'], 'fact_id': action['fact_id'],
            'quantity': content._decimal(quantity), 'citation': dict(citation),
            'published_at': material['published_at'], 'available_at': material['available_at'],
            'captured_at': material['provenance']['captured_at'], 'in_window': first <= effective <= last,
            'source_authenticity': 'UNVERIFIED', 'event_time_availability': 'NOT_INFERRED_FROM_EFFECTIVE_DATE'}


def derive(value, facts, read, *, company, generated_at):
    """Parent verifies the content/pack; this helper rebinds every used source byte."""
    materials._ticker(company); generated = materials._time(generated_at)
    result = {'schema': 'ar.research-daily-basis.v1', 'status': 'DATA_BLOCKED', 'company': company,
              'observation': None, 'calendar': None, 'actions': [], 'declared_coverage_end': None,
              'continuity_status': 'UNKNOWN_NO_ABSENCE_PROOF', 'eligible': False,
              'vintage': {'status': 'CAPTURE_ONLY_NOT_EVENT_VINTAGE', 'available_at': None},
              'unknowns': {'action_absence': 'UNKNOWN', 'suspensions': 'UNKNOWN', 'emergency_closures': 'UNKNOWN',
                           'units': 'NOT_CERTIFIED', 'context': 'NOT_CERTIFIED', 'settled_flow': 'NOT_CERTIFIED', 'costs': 'NOT_SUPPLIED'},
              'entry_stop_target': None, 'after_cost_rr': None, 'source_authenticity': 'UNVERIFIED',
              'rights': 'UNVERIFIED_PRIVATE_LOCAL_ONLY', **content.LABELS}
    if value is None:
        return result
    materials._exact(value, {'observation', 'observation_hash', 'calendar', 'actions', 'coverage_end'})
    if type(facts) is not dict or len(facts) > 96:
        _fail('FACTS')
    adapted = daily.adapt(value['observation'], value['observation_hash'], company, generated_at)
    dates = [row['date'] for row in adapted['daily_bars']]
    first, last = materials._date(dates[0]), materials._date(dates[-1])
    coverage = materials._date(value['coverage_end']) if value['coverage_end'] is not None else None
    if coverage is not None and coverage > generated.astimezone(SHANGHAI).date():
        _fail('COVERAGE_DATE')
    result['declared_coverage_end'] = value['coverage_end']
    result['observation'] = {key: adapted[key] for key in ('observation_hash', 'captured_at', 'source_trade_date',
        'source_scope', 'producer_rule', 'conversion_count', 'volume_scope')}
    result['observation']['row_count'] = len(dates)
    result['vintage']['available_at'] = adapted['captured_at']
    result['calendar'] = _calendar(value['calendar'], dates, generated)
    actions = value['actions']
    if type(actions) is not list or len(actions) > 32:
        _fail('ACTION_LIMIT')
    source_map = ev.parse(_read(read, 'source-map.json')) if actions else None
    seen = set()
    for action in actions:
        row = _action(action, facts, source_map, read, company, generated, first, last, coverage)
        citation = row['citation']
        identity = (row['effective_date'], row['kind'], citation['sha256'],
                    citation['page'], citation['start'], citation['end'])
        if identity in seen:
            _fail('DUPLICATE_ACTION')
        seen.add(identity); result['actions'].append(row)
    if any(row['in_window'] for row in result['actions']):
        result['continuity_status'] = 'BREAK'
    return result
