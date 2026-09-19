"""Synthetic provider fixtures; no market calls or human research verdicts."""
import copy
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.research_workflows import followup
from experiments.research_workflows import source_capture as sources

CODES = ('002119.SZ', '600667.SH', '688035.SH')
REQUEST = {'schema': 'ar.workflow-source-request.v1', 'before_date': '20260917',
           'after_date': '20260918', 'announcement_start': '20260901', 'announcement_end': '20260918'}
AT = '2026-09-19T10:00:00+00:00'


def listing(code, doc='A', day=1789660800000):
    return {'secCode': code[:6], 'orgId': 'org' + code[:6], 'announcementId': doc,
            'announcementTitle': 'Synthetic filing', 'announcementTime': day,
            'adjunctUrl': 'finalpage/2026-09-18/test.PDF'}


class Provider:
    def __init__(self, change=None):
        self.calls = []
        self.change = change or (lambda op, params, data: data)

    def __call__(self, op, params):
        self.calls.append((op, copy.deepcopy(params)))
        if op in ('daily', 'adj_factor'):
            code = params['ts_code']
            if op == 'daily':
                fields = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'vol', 'amount']
                rows = [[code, '20260917', 9.5, 10.5, 9, 10, 9.8, 100, 100],
                        [code, '20260918', 10, 11.5, 9.5, 11, 10, 200, 220]]
            else:
                fields = ['ts_code', 'trade_date', 'adj_factor']
                rows = [[code, '20260917', 1], [code, '20260918', 1]]
            data = {'code': 0, 'msg': '', 'data': {'fields': fields, 'items': rows}}
        elif op in ('sz_catalog', 'sh_catalog'):
            data = {'stockList': [{'code': c[:6], 'orgId': 'org' + c[:6], 'zwjc': 'Synthetic'}
                                  for c in CODES if c.endswith('SZ' if op == 'sz_catalog' else 'SH')]}
        elif op == 'announcements':
            data = {'totalAnnouncement': 0, 'hasMore': False, 'announcements': []}
        else:
            raise AssertionError(op)
        data = self.change(op, params, data)
        if isinstance(data, Exception):
            raise data
        return data if isinstance(data, bytes) else json.dumps(data, allow_nan=True).encode()


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def capture(self, provider=None, name='run', previous=None, request=None):
        out = self.root / name
        value = sources.capture(request or REQUEST, out, AT, transport=provider or Provider(), previous=previous)
        return out, value

    def bad_daily(self, edit):
        def change(op, p, data):
            if op == 'daily' and p['ts_code'] == CODES[0]:
                edit(data)
            return data
        return self.capture(Provider(change))[1]

    def bad_ann(self, edit):
        def change(op, p, data):
            if op == 'announcements' and p['stock'].startswith('688035,'):
                data = {'totalAnnouncement': 1, 'hasMore': False, 'announcements': [listing('688035.SH')]}
                edit(data)
            return data
        return self.capture(Provider(change))[1]

    def test_two_dates_and_three_subjects_are_frozen_and_replayed(self):
        fake = Provider()
        out, result = self.capture(fake)
        self.assertEqual(result['status'], 'COLLECTED_FOR_REVIEW')
        self.assertEqual(len(result['prices']), 3)
        first = result['prices'][0]
        self.assertEqual([r['trade_date'] for r in first['rows']], ['20260917', '20260918'])
        self.assertEqual(first['rows'][0]['volume_shares'], 10000)
        self.assertEqual(first['rows'][1]['amount_cny'], 220000)
        self.assertEqual(first['close_change_pct'], 10.0)
        self.assertEqual({p['ts_code'] for op, p in fake.calls if op == 'daily'}, set(CODES))
        self.assertEqual(result, sources.verify(out))

    def test_total_call_budget_is_a_hard_call_count(self):
        fake = Provider()
        log = sources.ExchangeLog(fake)
        for _ in range(17):
            log.ask('sz_catalog', {})
        with self.assertRaises(sources.SourceError):
            log.ask('sz_catalog', {})
        self.assertEqual(len(fake.calls), 17)

    def test_response_size_bound_is_enforced_before_recording(self):
        with patch.dict('os.environ', {'AR_OFFLINE': '0'}):
            transport = sources.HttpTransport(enabled=True)
        with self.assertRaises(sources.SourceError):
            transport.check_response(b' ' * (4 * 1024 * 1024 + 1) + b'{}')

    def test_prior_scope_and_time_cannot_silently_regress(self):
        prior, _ = self.capture()
        for field, value in [('announcement_start', '20260902'), ('announcement_end', '20260917'),
                             ('after_date', '20260916')]:
            with self.subTest(field=field), self.assertRaises(sources.SourceError):
                self.capture(previous=prior, name=field, request={**REQUEST, field: value})

    def test_synthetic_history_cannot_become_live_comparison_baseline(self):
        _, prior = self.capture()
        fake = Provider()
        with self.assertRaises(sources.SourceError):
            sources.derive(REQUEST, AT, sources.ExchangeLog(fake), 'LIVE_READ_ONLY', prior)
        self.assertEqual(fake.calls, [])

    def test_network_off_by_default_and_no_partial_output(self):
        with patch.dict('os.environ', {'AR_OFFLINE': '0'}), self.assertRaises(sources.SourceError):
            sources.HttpTransport()
        with patch.dict('os.environ', {'AR_OFFLINE': '0'}), self.assertRaisesRegex(sources.SourceError, 'network opt-in'):
            sources.capture(REQUEST, self.root / 'out', AT)
        self.assertFalse((self.root / 'out').exists())

    def test_future_or_reversed_dates_refused_before_transport(self):
        for field, value in [('after_date', '20260920'), ('before_date', '20260918'),
                             ('announcement_end', '20260920'), ('announcement_start', '20260919')]:
            req = {**REQUEST, field: value}
            provider = Provider()
            with self.assertRaises(sources.SourceError):
                self.capture(provider, request=req)
            self.assertEqual(provider.calls, [])

    def test_wrong_price_date_is_blocked_not_title_only(self):
        result = self.bad_daily(lambda d: d['data']['items'][0].__setitem__(1, '20260703'))
        self.assertEqual(result['prices'][0]['status'], 'DATA_BLOCKED')

    def test_valid_intermediate_dates_do_not_replace_comparison_endpoints(self):
        def change(op, p, d):
            if op in ('daily', 'adj_factor'):
                row = copy.deepcopy(d['data']['items'][0])
                row[1] = '20260916'
                d['data']['items'].insert(0, row)
            return d
        _, result = self.capture(Provider(change), request={**REQUEST, 'before_date': '20260916'})
        self.assertEqual(result['status'], 'COLLECTED_FOR_REVIEW')
        self.assertEqual([r['trade_date'] for r in result['prices'][0]['rows']], ['20260916', '20260918'])
        self.assertEqual(result['prices'][0]['close_change_pct'], 10.0)

    def test_wrong_price_company_cannot_replace_missing_subject(self):
        result = self.bad_daily(lambda d: d['data']['items'][0].__setitem__(0, '000001.SZ'))
        self.assertEqual(result['prices'][0]['status'], 'DATA_BLOCKED')

    def test_missing_price_row_has_no_zero_or_carried_quote(self):
        result = self.bad_daily(lambda d: d['data']['items'].pop())
        self.assertEqual(result['status'], 'DATA_BLOCKED')
        self.assertEqual(result['prices'][0]['rows'], [])
        self.assertIsNone(result['prices'][0]['close_change_pct'])

    def test_nonfinite_null_boolean_or_invalid_ohlc_refused(self):
        for value in (float('nan'), None, True, -1, 100):
            with self.subTest(value=value):
                self.root = Path(self.temp.name) / str(value)
                result = self.bad_daily(lambda d: d['data']['items'][0].__setitem__(5, value))
                self.assertEqual(result['prices'][0]['status'], 'DATA_BLOCKED')

    def test_derived_volume_overflow_is_explicitly_blocked(self):
        result = self.bad_daily(lambda d: d['data']['items'][0].__setitem__(7, 1e308))
        self.assertEqual(result['prices'][0]['status'], 'DATA_BLOCKED')
        self.assertEqual(result['prices'][0]['rows'], [])

    def test_huge_integer_is_blocked_instead_of_crashing_attempt(self):
        result = self.bad_daily(lambda d: d['data']['items'][0].__setitem__(7, 10**1000))
        self.assertEqual(result['prices'][0]['status'], 'DATA_BLOCKED')

    def test_interrupted_http_body_leaves_blocked_receipt(self):
        def change(op, p, d):
            return http.client.IncompleteRead(b'partial secret', 100) if op == 'daily' else d
        out, result = self.capture(Provider(change))
        self.assertEqual(result['status'], 'DATA_BLOCKED')
        self.assertNotIn('partial secret', (out / 'exchanges.json').read_text())
        self.assertEqual(sources.verify(out), result)

    def test_duplicate_fields_or_row_width_refused(self):
        for kind in ('field', 'width', 'duplicate'):
            self.root = Path(self.temp.name) / kind
            def edit(d):
                if kind == 'field':
                    d['data']['fields'][0] = 'close'
                elif kind == 'width':
                    d['data']['items'][0].pop()
                else:
                    d['data']['items'][1] = d['data']['items'][0]
            self.assertEqual(self.bad_daily(edit)['prices'][0]['status'], 'DATA_BLOCKED')

    def test_corporate_action_does_not_create_false_price_return(self):
        def change(op, p, d):
            if op == 'adj_factor':
                d['data']['items'][1][2] = 2
            return d
        _, result = self.capture(Provider(change))
        self.assertIsNone(result['prices'][0]['close_change_pct'])
        self.assertEqual(result['prices'][0]['comparison_status'], 'CORPORATE_ACTION_REVIEW_REQUIRED')

    def test_provider_error_is_not_empty_success(self):
        def change(op, p, d):
            return {'code': 40203, 'msg': 'quota', 'data': None} if op == 'daily' else d
        _, result = self.capture(Provider(change))
        self.assertEqual([x['status'] for x in result['prices']], ['DATA_BLOCKED'] * 3)

    def test_empty_success_is_explicitly_bounded_not_global_no_news(self):
        _, result = self.capture()
        row = result['announcements'][0]
        self.assertEqual(row['status'], 'NO_ANNOUNCEMENTS_IN_QUERY')
        self.assertTrue(row['query_complete'])
        self.assertEqual(row['query_start'], '20260901')
        self.assertEqual(row['query_end'], '20260918')
        self.assertEqual(row['body_status'], 'NOT_FETCHED')

    def test_unknown_catalog_identity_stops_query_for_that_subject(self):
        def change(op, p, d):
            if op == 'sz_catalog':
                d['stockList'] = []
            return d
        fake = Provider(change)
        _, result = self.capture(fake)
        self.assertEqual(result['announcements'][0]['status'], 'DATA_BLOCKED')
        self.assertFalse(any(op == 'announcements' and p['stock'].startswith('002119,') for op, p in fake.calls))

    def test_wrong_announcement_company_refused(self):
        result = self.bad_ann(lambda d: d['announcements'][0].update(secCode='000001'))
        self.assertFalse(result['announcements'][2]['query_complete'])

    def test_wrong_announcement_org_refused(self):
        result = self.bad_ann(lambda d: d['announcements'][0].update(orgId='other'))
        self.assertEqual(result['announcements'][2]['status'], 'DATA_BLOCKED')

    def test_out_of_window_announcement_refused(self):
        result = self.bad_ann(lambda d: d['announcements'][0].update(announcementTime=1787000000000))
        self.assertEqual(result['announcements'][2]['status'], 'DATA_BLOCKED')

    def test_huge_announcement_time_leaves_blocked_receipt(self):
        result = self.bad_ann(lambda d: d['announcements'][0].update(announcementTime=10**400))
        self.assertEqual(result['announcements'][2]['status'], 'DATA_BLOCKED')

    def test_invalid_unicode_is_blocked_before_report_rendering(self):
        with self.assertRaises(sources.SourceError):
            sources.load(b'{"title":"\\ud800"}')
        result = self.bad_ann(lambda d: d['announcements'][0].update(announcementTitle='Bad\ud800title'))
        self.assertEqual(result['announcements'][2]['status'], 'DATA_BLOCKED')

    def test_total_and_more_must_be_explicit_not_truthy(self):
        for edit in (lambda d: d.pop('hasMore'), lambda d: d.update(hasMore='false'),
                     lambda d: d.update(totalAnnouncement=True), lambda d: d.update(totalAnnouncement=2)):
            self.root = Path(self.temp.name) / str(id(edit))
            self.assertFalse(self.bad_ann(edit)['announcements'][2]['query_complete'])

    def test_pagination_collects_each_page_and_binds_query(self):
        def change(op, p, d):
            if op == 'announcements':
                self.assertEqual(p['seDate'], '2026-09-01~2026-09-18')
                return {'totalAnnouncement': 2, 'hasMore': p['pageNum'] == 1,
                        'announcements': [listing(p['stock'][:6] + '.SH', str(p['pageNum']))]}
            return d
        _, result = self.capture(Provider(change))
        self.assertEqual(result['announcements'][2]['pages'], 2)
        self.assertEqual(len(result['announcements'][2]['items']), 2)
        self.assertTrue(result['announcements'][2]['query_complete'])

    def test_repeated_page_or_changing_total_is_not_complete(self):
        for changed in (False, True):
            self.root = Path(self.temp.name) / str(changed)
            def change(op, p, d):
                if op == 'announcements':
                    return {'totalAnnouncement': 3 if changed and p['pageNum'] > 1 else 2,
                            'hasMore': p['pageNum'] == 1, 'announcements': [listing(p['stock'][:6] + '.SH')]}
                return d
            _, result = self.capture(Provider(change))
            self.assertFalse(result['announcements'][2]['query_complete'])

    def test_changed_total_even_with_matching_final_count_is_rejected(self):
        def change(op, p, d):
            if op == 'announcements':
                docs = ['A'] if p['pageNum'] == 1 else ['B', 'C']
                return {'totalAnnouncement': 2 if p['pageNum'] == 1 else 3,
                        'hasMore': p['pageNum'] == 1,
                        'announcements': [listing(p['stock'][:6] + '.SH', doc) for doc in docs]}
            return d
        _, result = self.capture(Provider(change))
        self.assertEqual(result['announcements'][2]['status'], 'DATA_BLOCKED')

    def test_page_budget_exhaustion_is_not_empty_success(self):
        def change(op, p, d):
            if op == 'announcements':
                return {'totalAnnouncement': 4, 'hasMore': True,
                        'announcements': [listing(p['stock'][:6] + '.SH', str(p['pageNum']))]}
            return d
        fake = Provider(change)
        _, result = self.capture(fake)
        self.assertEqual(result['announcements'][2]['status'], 'DATA_BLOCKED')
        self.assertLessEqual(len(fake.calls), 17)
        self.assertLessEqual(max(p['pageNum'] for op, p in fake.calls if op == 'announcements'), 3)

    def test_bad_pdf_path_stays_blocked_never_followed(self):
        result = self.bad_ann(lambda d: d['announcements'][0].update(adjunctUrl='https://evil.test/x.pdf'))
        self.assertEqual(result['announcements'][2]['status'], 'DATA_BLOCKED')

    def test_missing_listing_body_is_not_complete_financial_evidence(self):
        result = self.bad_ann(lambda d: None)
        row = result['announcements'][2]
        self.assertTrue(row['query_complete'])
        self.assertEqual(row['body_status'], 'NOT_FETCHED')
        self.assertEqual(row['items'][0]['body_status'], 'NOT_FETCHED')
        self.assertEqual(result['thesis_status'], 'UNRESOLVED')

    def test_dns_and_bad_json_have_failure_receipts_without_old_success(self):
        first, old = self.capture()
        for label, data in [('dns', OSError('secret token should never appear')), ('json', b'{}')]:
            def change(op, p, d):
                return data if op.endswith('catalog') else d
            out, result = self.capture(Provider(change), label, first)
            self.assertEqual(result['status'], 'DATA_BLOCKED')
            self.assertFalse(result['announcements'][0]['query_complete'])
            self.assertNotIn('secret token', (out / 'exchanges.json').read_text())
            self.assertEqual(sources.verify(first), old)
            self.assertEqual(sources.verify(out), result)

    def test_new_and_revised_listing_do_not_answer_thesis(self):
        first, _ = self.capture()
        def change(op, p, d):
            if op == 'announcements':
                return {'totalAnnouncement': 1, 'hasMore': False, 'announcements': [listing(p['stock'][:6] + '.SH')]}
            return d
        second, new = self.capture(Provider(change), 'second', first)
        self.assertEqual(new['announcements'][0]['change'], 'NEW_LISTINGS_REVIEW_REQUIRED')
        _, same = self.capture(Provider(change), 'same', second)
        self.assertEqual(same['announcements'][0]['change'], 'NO_LISTING_CHANGES')
        def revised(op, p, d):
            d = change(op, p, d)
            if op == 'announcements':
                d['announcements'][0]['announcementTitle'] = 'Revised listing'
            return d
        _, result = self.capture(Provider(revised), 'revised', second)
        self.assertEqual(result['announcements'][0]['change'], 'REVISED_LISTINGS_REVIEW_REQUIRED')
        self.assertEqual(result['thesis_status'], 'UNRESOLVED')
        self.assertEqual(result['human_review'], 'PENDING')
        self.assertFalse(any(result['authority'].values()))

    def test_resealed_receipt_and_raw_source_tamper_rejected(self):
        out, _ = self.capture()
        receipt = json.loads((out / 'receipt.json').read_bytes())
        receipt['human_review'] = 'VERIFIED'
        (out / 'receipt.json').write_text(json.dumps(receipt))
        followup._seal_inventory(out)
        with self.assertRaises(sources.SourceError):
            sources.verify(out)

    def test_resealed_raw_response_needs_its_own_hash(self):
        out, _ = self.capture()
        records = json.loads((out / 'exchanges.json').read_bytes())
        records[0]['sha256'] = '0' * 64
        (out / 'exchanges.json').write_text(json.dumps(records))
        followup._seal_inventory(out)
        with self.assertRaises(sources.SourceError):
            sources.verify(out)

    def test_resealed_exchange_request_cannot_change_company(self):
        out, _ = self.capture()
        records = json.loads((out / 'exchanges.json').read_bytes())
        records[0]['request']['params']['ts_code'] = '000001.SZ'
        (out / 'exchanges.json').write_text(json.dumps(records))
        followup._seal_inventory(out)
        with self.assertRaises(sources.SourceError):
            sources.verify(out)

    def test_new_output_only_and_symlinks_refused(self):
        out, _ = self.capture()
        with self.assertRaises(ValueError):
            self.capture(name='run')
        link = self.root / 'linked'
        link.symlink_to(out, target_is_directory=True)
        with self.assertRaises(ValueError):
            sources.verify(link)

    def test_transport_fixed_urls_and_no_redirect_or_token_in_request_record(self):
        with patch.dict('os.environ', {'TUSHARE_URL': 'https://evil.test', 'AR_OFFLINE': '0'}):
            transport = sources.HttpTransport('secret-token', enabled=True)
            req = transport.request('daily', {'ts_code': CODES[0], 'start_date': '20260917', 'end_date': '20260918'})
        self.assertEqual(req.full_url, 'https://api.tushare.pro')
        self.assertEqual(json.loads(req.data)['token'], 'secret-token')
        with self.assertRaises(sources.SourceError):
            transport.request('trade', {})
        with self.assertRaises(sources.SourceError):
            sources.NoRedirect().redirect_request(req, None, 302, '', {}, 'https://evil.test')

    def test_live_offline_guard_and_secret_response_refused(self):
        with patch.dict('os.environ', {'AR_OFFLINE': '1'}):
            with self.assertRaises(sources.SourceError):
                sources.HttpTransport('token', enabled=True)
        with patch.dict('os.environ', {'AR_OFFLINE': '0'}):
            transport = sources.HttpTransport('secret-token', enabled=True)
            with self.assertRaises(sources.SourceError):
                transport.check_response(b'{"msg":"secret-token"}')

    def test_json_escaped_token_echo_is_not_frozen(self):
        with patch.dict('os.environ', {'AR_OFFLINE': '0'}):
            transport = sources.HttpTransport('secret-token', enabled=True)
        with self.assertRaisesRegex(sources.SourceError, 'SECRET_RESPONSE_REFUSED'):
            transport.check_response(b'{"msg":"\\u0073ecret-token"}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
