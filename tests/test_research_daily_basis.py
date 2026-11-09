"""Synthetic source-bound daily evidence never becomes technical approval."""
import copy
from datetime import date, timedelta
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts/llm'),
               str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import workbench_evidence as ev
from test_research_daily import observation

URL = 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml'
PARAGRAPHS = [
    '\uff08\u4e00\uff09\u5143\u65e6\uff1a1\u67081\u65e5\uff08\u661f\u671f\u56db\uff09\u81f31\u67083\u65e5\uff08\u661f\u671f\u516d\uff09\u4f11\u5e02\uff0c1\u67085\u65e5\uff08\u661f\u671f\u4e00\uff09\u8d77\u7167\u5e38\u5f00\u5e02\u3002\u53e6\u5916\uff0c1\u67084\u65e5\uff08\u661f\u671f\u65e5\uff09\u4e3a\u5468\u672b\u4f11\u5e02\u3002',
    '\uff08\u4e8c\uff09\u6625\u8282\uff1a2\u670815\u65e5\uff08\u661f\u671f\u65e5\uff09\u81f32\u670823\u65e5\uff08\u661f\u671f\u4e00\uff09\u4f11\u5e02\uff0c2\u670824\u65e5\uff08\u661f\u671f\u4e8c\uff09\u8d77\u7167\u5e38\u5f00\u5e02\u3002\u53e6\u5916\uff0c2\u670814\u65e5\uff08\u661f\u671f\u516d\uff09\u30012\u670828\u65e5\uff08\u661f\u671f\u516d\uff09\u4e3a\u5468\u672b\u4f11\u5e02\u3002',
    '\uff08\u4e09\uff09\u6e05\u660e\u8282\uff1a4\u67084\u65e5\uff08\u661f\u671f\u516d\uff09\u81f34\u67086\u65e5\uff08\u661f\u671f\u4e00\uff09\u4f11\u5e02\uff0c4\u67087\u65e5\uff08\u661f\u671f\u4e8c\uff09\u8d77\u7167\u5e38\u5f00\u5e02\u3002',
    '\uff08\u56db\uff09\u52b3\u52a8\u8282\uff1a5\u67081\u65e5\uff08\u661f\u671f\u4e94\uff09\u81f35\u67085\u65e5\uff08\u661f\u671f\u4e8c\uff09\u4f11\u5e02\uff0c5\u67086\u65e5\uff08\u661f\u671f\u4e09\uff09\u8d77\u7167\u5e38\u5f00\u5e02\u3002\u53e6\u5916\uff0c5\u67089\u65e5\uff08\u661f\u671f\u516d\uff09\u4e3a\u5468\u672b\u4f11\u5e02\u3002',
    '\uff08\u4e94\uff09\u7aef\u5348\u8282\uff1a6\u670819\u65e5\uff08\u661f\u671f\u4e94\uff09\u81f36\u670821\u65e5\uff08\u661f\u671f\u65e5\uff09\u4f11\u5e02\uff0c6\u670822\u65e5\uff08\u661f\u671f\u4e00\uff09\u8d77\u7167\u5e38\u5f00\u5e02\u3002',
    '\uff08\u516d\uff09\u4e2d\u79cb\u8282\uff1a9\u670825\u65e5\uff08\u661f\u671f\u4e94\uff09\u81f39\u670827\u65e5\uff08\u661f\u671f\u65e5\uff09\u4f11\u5e02\uff0c9\u670828\u65e5\uff08\u661f\u671f\u4e00\uff09\u8d77\u7167\u5e38\u5f00\u5e02\u3002',
    '\uff08\u4e03\uff09\u56fd\u5e86\u8282\uff1a10\u67081\u65e5\uff08\u661f\u671f\u56db\uff09\u81f310\u67087\u65e5\uff08\u661f\u671f\u4e09\uff09\u4f11\u5e02\uff0c10\u67088\u65e5\uff08\u661f\u671f\u56db\uff09\u8d77\u7167\u5e38\u5f00\u5e02\u3002\u53e6\u5916\uff0c9\u670820\u65e5\uff08\u661f\u671f\u65e5\uff09\u300110\u670810\u65e5\uff08\u661f\u671f\u516d\uff09\u4e3a\u5468\u672b\u4f11\u5e02\u3002',
]


def calendar(paragraphs=None):
    raw = '<html><p>\u4e0a\u6d77\u8bc1\u5238\u4ea4\u6613\u62402026\u5e74\u90e8\u5206\u8282\u5047\u65e5\u4f11\u5e02\u5b89\u6392</p>'
    raw += ''.join('<p>' + p + '</p>' for p in (PARAGRAPHS if paragraphs is None else paragraphs)) + '</html>'
    return {'raw_utf8': raw, 'capture_receipt': {
        'file': 'raw/sse_notice_2026_annual_20251222.shtml', 'url': URL, 'final_url': URL,
        'http_status': 200, 'content_type': 'text/html', 'bytes': len(raw.encode()),
        'sha256': ev.sha(raw.encode()), 'observed_at': '2026-07-01T16:00:00+08:00',
        'published_on': '2025-12-22', 'note': 'Synthetic capture, not actual source authentication.'}}


def fixture():
    source = observation()
    value = {'observation': source, 'observation_hash': source['observation_hash'],
             'calendar': calendar(), 'actions': [], 'coverage_end': '20260803'}
    pin = 'a' * 64
    quote = '\u516c\u53f8\u4e8e2026\u5e747\u67089\u65e5\u56de\u8d2d\u6ce8\u95004,565\u80a1\u9650\u5236\u6027\u80a1\u7968\u3002'
    raw = ('Heading\n' + quote + '\n').encode()
    citation = {'sha256': pin, 'page': 41, 'start': 2, 'end': 2, 'expected': quote}
    facts = {'cancelled': {'id': 'cancelled', 'value': '4565', 'period': '20260709', 'unit': 'COUNT',
                           'citation': copy.deepcopy(citation)}}
    selection = {'material_id': 'cancel-note', 'version': 'v1', 'sha256': pin, 'pages': [41]}
    material = {'material_id': 'cancel-note', 'version': 'v1', 'kind': 'original', 'ts_code': '603986.SH',
                'published_at': '2026-07-10T23:59:59+08:00', 'available_at': '2026-07-11T10:00:00+08:00',
                'provenance': {'captured_at': '2026-07-11T10:00:00+08:00', 'provider_id': 'synthetic',
                               'source_locator': 'https://issuer.example.invalid/cancellation'},
                'files': [{'sha256': pin, 'size_bytes': 100, 'source_path': 'sources/cancel.pdf'}]}
    name = 'inputs/pages/' + pin + '-p41.txt'
    mapping = {'schema': 'ar.material-research-provenance.v1', 'documents': [
        {'selection': selection, 'material': material, 'original_path': 'inputs/originals/' + pin + '.pdf'}],
        'pages': {'pdf-' + pin + '-p41': {'sha256': pin, 'physical_page': 41, 'text_sha256': ev.sha(raw),
                  'original_path': 'inputs/originals/' + pin + '.pdf', 'text_path': name}},
        'extractor': {'name': 'pypdf', 'version': '6.10.0'}, 'prepared_at': '2026-08-03T16:00:00+08:00'}
    files = {'source-map.json': ev.canonical(mapping).encode(), name: raw}
    return value, facts, files, citation, mapping


class DailyBasisTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('research_daily_basis'), 'daily basis helper missing')
        return importlib.import_module('research_daily_basis')

    def derive(self, value=None, facts=None, files=None):
        base, default_facts, default_files, _, _ = fixture()
        return self.module().derive(base if value is None else value,
            default_facts if facts is None else facts,
            (default_files if files is None else files).__getitem__,
            company='603986.SH', generated_at='2026-08-04T16:00:00+08:00')

    def test_schedule_includes_weekends_and_never_certifies_or_creates_levels(self):
        result = self.derive()
        schedule = result['calendar']
        self.assertEqual(schedule['status'], 'SCHEDULE_CANDIDATE_NOT_CERTIFIED')
        self.assertEqual(len(schedule['days']), 32)
        self.assertEqual(schedule['observed_date_comparison'], 'MATCH')
        self.assertEqual([x['trade_date'] for x in schedule['days'] if not x['scheduled_open']][:2], ['20260704', '20260705'])
        self.assertFalse(result['eligible'])
        self.assertEqual(result['human_review'], 'PENDING')
        self.assertEqual(result['continuity_status'], 'UNKNOWN_NO_ABSENCE_PROOF')
        self.assertIsNone(result['entry_stop_target'])
        self.assertIsNone(result['after_cost_rr'])

    def test_missing_daily_or_calendar_is_honest_and_does_not_read_sources(self):
        result = self.module().derive(None, {}, lambda name: self.fail('Unexpected source read'),
            company='603986.SH', generated_at='2026-08-04T16:00:00+08:00')
        self.assertIsNone(result['observation']); self.assertIsNone(result['calendar'])
        value, _, _, _, _ = fixture(); value['calendar'] = None
        result = self.derive(value)
        self.assertIsNone(result['calendar']); self.assertFalse(result['eligible'])

    def test_calendar_rejects_wrong_origin_hash_length_status_and_chronology(self):
        for change in ('url', 'redirect', 'hash', 'length', 'status', 'bool-status', 'type',
                       'publication', 'early', 'future', 'extra', 'file'):
            value, _, _, _, _ = fixture(); receipt = value['calendar']['capture_receipt']
            if change == 'url': receipt['url'] = 'https://evil.invalid/notice'
            if change == 'redirect': receipt['final_url'] = URL + '?copy=1'
            if change == 'hash': receipt['sha256'] = 'f' * 64
            if change == 'length': receipt['bytes'] += 1
            if change == 'status': receipt['http_status'] = 404
            if change == 'bool-status': receipt['http_status'] = True
            if change == 'type': receipt['content_type'] = 'application/json'
            if change == 'publication': receipt['published_on'] = '2026-12-22'
            if change == 'early': receipt['observed_at'] = '2025-12-21T12:00:00+08:00'
            if change == 'future': receipt['observed_at'] = '2026-08-05T12:00:00+08:00'
            if change == 'extra': receipt['approved'] = True
            if change == 'file': receipt['file'] = '../annual.shtml'
            with self.subTest(change=change), self.assertRaises(ValueError): self.derive(value)

    def test_calendar_rejects_missing_duplicate_changed_or_script_only_holidays(self):
        variants = [PARAGRAPHS[:-1], PARAGRAPHS + [PARAGRAPHS[0]],
                    [PARAGRAPHS[0].replace('1\u67081\u65e5', '1\u67082\u65e5'), *PARAGRAPHS[1:]],
                    [PARAGRAPHS[0].replace('\u661f\u671f\u56db', '\u661f\u671f\u4e94'), *PARAGRAPHS[1:]],
                    [*PARAGRAPHS, '\uff08\u516b\uff09\u989d\u5916\u4f11\u5e02\u3002']]
        for paragraphs in variants:
            value, _, _, _, _ = fixture(); value['calendar'] = calendar(paragraphs)
            with self.subTest(paragraphs=paragraphs), self.assertRaises(ValueError): self.derive(value)
        value, _, _, _, _ = fixture()
        raw = '<script>' + ''.join('<p>' + p + '</p>' for p in PARAGRAPHS) + '</script>'
        value['calendar']['raw_utf8'] = raw
        value['calendar']['capture_receipt'].update(bytes=len(raw.encode()), sha256=ev.sha(raw.encode()))
        with self.assertRaises(ValueError): self.derive(value)

    def test_positive_cancellation_binds_quote_count_date_and_material_availability(self):
        value, facts, files, citation, _ = fixture()
        value['actions'] = [{'effective_date': '20260709', 'kind': 'SHARE_CANCELLATION',
                             'fact_id': 'cancelled', 'citation': citation}]
        before = copy.deepcopy(value)
        result = self.derive(value, facts, files)
        self.assertEqual(result['continuity_status'], 'BREAK')
        self.assertEqual(result['actions'][0]['quantity'], '4565')
        self.assertEqual(result['actions'][0]['available_at'], '2026-07-11T10:00:00+08:00')
        self.assertTrue(result['actions'][0]['in_window'])
        self.assertEqual(value, before)
        self.assertFalse(result['eligible'])

    def test_action_rejects_missing_fact_units_period_quantity_date_and_forgery(self):
        for change in ('missing', 'unit', 'period', 'zero', 'fraction', 'negative', 'count-date', 'quote',
                       'date', 'kind', 'extra', 'duplicate', 'fact-source'):
            value, facts, files, citation, _ = fixture()
            action = {'effective_date': '20260709', 'kind': 'SHARE_CANCELLATION', 'fact_id': 'cancelled', 'citation': citation}
            value['actions'] = [action]
            if change == 'missing': action['fact_id'] = 'absent'
            if change == 'unit': facts['cancelled']['unit'] = 'CNY'
            if change == 'period': facts['cancelled']['period'] = '2026H1'
            if change == 'zero': facts['cancelled']['value'] = '0'
            if change == 'fraction': facts['cancelled']['value'] = '1.5'
            if change == 'negative': facts['cancelled']['value'] = '-1'
            if change == 'count-date': facts['cancelled']['value'] = '2026'
            if change == 'quote': citation['expected'] = 'Forged cancellation'
            if change == 'date': action['effective_date'] = '20260710'
            if change == 'kind': action['kind'] = 'NO_ACTION'
            if change == 'extra': action['verified'] = True
            if change == 'duplicate': value['actions'].append(copy.deepcopy(action))
            if change == 'fact-source': facts['cancelled']['citation']['sha256'] = 'b' * 64
            with self.subTest(change=change), self.assertRaises(ValueError): self.derive(value, facts, files)

    def test_action_rejects_source_map_company_hash_selection_and_late_material(self):
        for change in ('company', 'selection', 'pagehash', 'missingdoc', 'duplicatedoc', 'late', 'timeorder', 'wording'):
            value, facts, files, citation, mapping = fixture()
            value['actions'] = [{'effective_date': '20260709', 'kind': 'SHARE_CANCELLATION', 'fact_id': 'cancelled', 'citation': citation}]
            doc = mapping['documents'][0]
            if change == 'company': doc['material']['ts_code'] = '600000.SH'
            if change == 'selection': doc['selection']['pages'] = [40]
            if change == 'pagehash': next(iter(mapping['pages'].values()))['text_sha256'] = 'f' * 64
            if change == 'missingdoc': mapping['documents'] = []
            if change == 'duplicatedoc': mapping['documents'].append(copy.deepcopy(doc))
            if change == 'late': doc['material']['available_at'] = '2026-08-05T16:00:00+08:00'
            if change == 'timeorder': doc['material']['published_at'] = '2026-07-12T16:00:00+08:00'
            if change == 'wording':
                name = next(x for x in files if x != 'source-map.json')
                files[name] = files[name].replace('\u56de\u8d2d\u6ce8\u9500'.encode(), '\u8ba1\u5212\u589e\u52a0'.encode())
                citation['expected'] = citation['expected'].replace('\u56de\u8d2d\u6ce8\u9500', '\u8ba1\u5212\u589e\u52a0')
                next(iter(mapping['pages'].values()))['text_sha256'] = ev.sha(files[name])
            files['source-map.json'] = ev.canonical(mapping).encode()
            with self.subTest(change=change), self.assertRaises(ValueError): self.derive(value, facts, files)

    def test_capture_only_empty_actions_and_outside_window_never_prove_absence(self):
        result = self.derive()
        self.assertEqual(result['vintage']['status'], 'CAPTURE_ONLY_NOT_EVENT_VINTAGE')
        self.assertEqual(result['vintage']['available_at'], '2026-08-03T16:00:00+08:00')
        self.assertEqual(result['unknowns']['action_absence'], 'UNKNOWN')
        self.assertEqual(result['unknowns']['settled_flow'], 'NOT_CERTIFIED')
        self.assertEqual(result['unknowns']['units'], 'NOT_CERTIFIED')
        self.assertEqual(result['unknowns']['costs'], 'NOT_SUPPLIED')

    def test_daily_pin_company_dates_and_input_truth_flags_are_rejected(self):
        for change in ('pin', 'company', 'coverage', 'extra', 'calendar-extra'):
            value, _, _, _, _ = fixture()
            if change == 'pin': value['observation_hash'] = 'f' * 64
            if change == 'company': value['observation']['company'] = '600000.SH'
            if change == 'coverage': value['coverage_end'] = '20270101'
            if change == 'extra': value['eligible'] = True
            if change == 'calendar-extra': value['calendar']['certified'] = True
            with self.subTest(change=change), self.assertRaises(ValueError): self.derive(value)

    def test_outside_window_and_incomplete_disclosure_coverage_remain_unknown(self):
        value, facts, files, citation, mapping = fixture()
        name = next(x for x in files if x != 'source-map.json')
        files[name] = files[name].replace('7\u67089\u65e5'.encode(), '6\u67089\u65e5'.encode())
        citation['expected'] = citation['expected'].replace('7\u67089\u65e5', '6\u67089\u65e5')
        facts['cancelled']['period'] = '20260609'
        next(iter(mapping['pages'].values()))['text_sha256'] = ev.sha(files[name])
        files['source-map.json'] = ev.canonical(mapping).encode()
        value['actions'] = [{'effective_date': '20260609', 'kind': 'SHARE_CANCELLATION',
                             'fact_id': 'cancelled', 'citation': citation}]
        value['coverage_end'] = '20260701'
        result = self.derive(value, facts, files)
        self.assertFalse(result['actions'][0]['in_window'])
        self.assertEqual(result['continuity_status'], 'UNKNOWN_NO_ABSENCE_PROOF')
        self.assertEqual(result['unknowns']['action_absence'], 'UNKNOWN')

    def test_calendar_file_limit_is_not_expanded(self):
        from unittest import mock
        value, _, _, _, _ = fixture()
        with mock.patch.object(self.module().ev, 'MAX_FILE', 8):
            with self.assertRaises(ValueError): self.derive(value)

    def test_planned_or_negated_cancellation_is_not_positive_action_evidence(self):
        for wording in ('\u62df\u56de\u8d2d\u6ce8\u9500', '\u672a\u56de\u8d2d\u6ce8\u9500'):
            value, facts, files, citation, mapping = fixture()
            name = next(x for x in files if x != 'source-map.json')
            files[name] = files[name].replace('\u56de\u8d2d\u6ce8\u9500'.encode(), wording.encode())
            citation['expected'] = citation['expected'].replace('\u56de\u8d2d\u6ce8\u9500', wording)
            next(iter(mapping['pages'].values()))['text_sha256'] = ev.sha(files[name])
            files['source-map.json'] = ev.canonical(mapping).encode()
            value['actions'] = [{'effective_date': '20260709', 'kind': 'SHARE_CANCELLATION',
                                 'fact_id': 'cancelled', 'citation': citation}]
            with self.subTest(wording=wording), self.assertRaises(ValueError): self.derive(value, facts, files)

    def test_duplicate_citation_with_an_alias_fact_is_still_duplicate_evidence(self):
        value, facts, files, citation, _ = fixture()
        facts['alias'] = copy.deepcopy(facts['cancelled']); facts['alias']['id'] = 'alias'
        value['actions'] = [{'effective_date': '20260709', 'kind': 'SHARE_CANCELLATION',
                             'fact_id': identifier, 'citation': copy.deepcopy(citation)}
                            for identifier in ('cancelled', 'alias')]
        with self.assertRaises(ValueError): self.derive(value, facts, files)


if __name__ == '__main__':
    unittest.main()
