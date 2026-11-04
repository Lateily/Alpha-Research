"""Public-entry regressions: pinned earnings output -> library -> exact query."""
import copy
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts/llm')]
from tests import test_foundation_research as research_tests
import foundation_materials as materials
import workbench_evidence as ev
import workbench_earnings_trial as earnings


class ResultIndexTests(unittest.TestCase):
    adapter = research_tests.MaterialResearchTests.adapter
    prepare = research_tests.MaterialResearchTests.prepare

    def setUp(self):
        research_tests.MaterialResearchTests.setUp(self)
        self.packet_request = copy.deepcopy(self.request)
        self.pack = self.prepare()
        self.result = earnings.run(self.root / 'pack', self.root / 'case', expected_pack_hash=self.pack['pack_hash'])
        self.request = {'schema': 'ar.research-result-intake.v1', 'library_id': 'results-test',
            'material_id': 'research-result-cash-quality', 'version': 'v1',
            'expected_source_library_hash': self.request['expected_library_hash'],
            'expected_pack_hash': self.pack['pack_hash'], 'expected_result_hash': ev.sealed(self.result),
            'expected_destination_library_hash': None, 'result': self.result}
        self.destination = self.root / 'result-library'
        self.stage = 0

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('foundation_results'), 'result intake/query adapter is missing')
        return importlib.import_module('foundation_results')

    def ingest(self, request=None, destination=None, stage=None):
        self.stage += 1
        return self.module().ingest_result(self.library, self.root / 'pack', self.root / 'case/600000.SH',
            destination or self.destination, stage or self.root / ('stage-' + str(self.stage)), request or self.request)

    def query(self, pin, **filters):
        return self.module().query_results(self.destination, expected_library_hash=pin, **filters)

    def test_real_entry_archives_all_bytes_and_queries_research_date(self):
        before = materials.verify_library(self.library)['library_hash']
        result = self.ingest()
        self.assertEqual(result['disposition'], 'IMPORTED')
        view = self.query(result['library_hash'], industry_key='UNSPECIFIED', research_date='20200106', ts_code='600000.SH')
        self.assertEqual(len(view['results']), 1)
        row = view['results'][0]
        self.assertEqual(row['research_date'], '20200106')
        self.assertEqual(row['source_cutoff_at'], '2020-01-03T15:00:00+08:00')
        self.assertEqual(row.get('source_documents', [{}])[0].get('published_at'), self.row['published_at'])
        self.assertEqual(row['human_review'], 'PENDING')
        self.assertEqual(row['assessments'], ['UNRESOLVED'])
        self.assertFalse(row['paper_authority'])
        self.assertEqual(row['result_hash'], self.request['expected_result_hash'])
        self.assertEqual(row['report_sha256'], self.result['reports'][0]['report_sha256'])
        verified = materials.verify_library(self.destination, expected_library_hash=result['library_hash'])
        hashes = set(verified['files'].values())
        self.assertTrue(all(ev.sha(p.read_bytes()) in hashes for p in (self.root / 'case/600000.SH').rglob('*') if p.is_file()))
        self.assertIn(ev.sha(self.pdf), hashes)
        self.assertEqual(materials.verify_library(self.library)['library_hash'], before)

    def test_query_empty_and_combined_filters_do_not_substitute_dates(self):
        result = self.ingest(); pin = result['library_hash']
        for filters in ({'industry_key': 'OTHER'}, {'research_date': '20200103'}, {'ts_code': '600001.SH'},
                        {'industry_key': 'UNSPECIFIED', 'industry_taxonomy': 'OTHER'}, {'taxonomy_version': 'OTHER'}):
            with self.subTest(filters=filters):
                view = self.query(pin, **filters)
                self.assertEqual(view['results'], [])
                self.assertEqual(view['status'], 'EMPTY')
        self.assertEqual(len(self.query(pin, industry_key='UNSPECIFIED', industry_taxonomy='UNSPECIFIED',
                                        taxonomy_version='UNSPECIFIED', research_date='20200106')['results']), 1)

    def test_wrong_source_pack_result_pins_refuse_without_writes(self):
        for key in ('expected_source_library_hash', 'expected_pack_hash', 'expected_result_hash'):
            with self.subTest(key=key):
                value = copy.deepcopy(self.request); value[key] = 'f' * 64
                with self.assertRaises(ValueError): self.ingest(value)
                self.assertFalse(self.destination.exists())
                self.assertFalse((self.root / ('stage-' + str(self.stage))).exists())

    def test_query_pin_is_checked_even_for_an_empty_filter(self):
        self.ingest()
        with self.assertRaises(ValueError): self.query('f' * 64, industry_key='NO_MATCH')

    def test_closed_or_malformed_request_never_starts_staging(self):
        for value in ({**self.request, 'material_id': 42}, {**self.request, 'version': False},
                      {**self.request, 'production_authority': True}, {**self.request, 'result': None}):
            with self.subTest(value=str(type(value.get('material_id')))):
                with self.assertRaises(ValueError): self.ingest(value)
                self.assertFalse(self.destination.exists())
                self.assertFalse((self.root / ('stage-' + str(self.stage))).exists())

    def test_importer_code_change_before_registration_refuses_publication(self):
        self.module(); adapter = self.adapter()
        stable = {'code_sha':'a' * 40, 'source_tree_hash':'b' * 64}
        changed = {'code_sha':'c' * 40, 'source_tree_hash':'d' * 64}
        with mock.patch.object(adapter, '_execution_identity', side_effect=[stable, stable, changed]):
            with self.assertRaisesRegex(ValueError, 'IMPORT_CODE_CHANGED'):
                self.ingest()
        self.assertFalse(self.destination.exists())

    def test_changed_case_missing_extra_and_symlink_files_refuse(self):
        module = self.module()
        case = self.root / 'case/600000.SH'
        target = case / 'report.md'; original = target.read_bytes()
        for mode in ('changed', 'missing', 'extra', 'symlink'):
            with self.subTest(mode=mode):
                if mode == 'changed': target.write_bytes(b'changed')
                if mode == 'missing': target.unlink()
                if mode == 'extra': (case / 'unlisted.txt').write_text('extra')
                if mode == 'symlink':
                    target.unlink(); target.symlink_to(case / 'human-review.md')
                with self.assertRaises((ValueError, OSError)):
                    module.ingest_result(self.library, self.root / 'pack', case, self.destination, self.root / ('bad-' + mode), self.request)
                self.assertFalse(self.destination.exists())
                if target.is_symlink(): target.unlink()
                target.write_bytes(original)
                if mode == 'extra': (case / 'unlisted.txt').unlink()

    def test_empty_directory_and_hardlinked_case_files_are_refused(self):
        case = self.root / 'case/600000.SH'
        extra = case / 'unexpected'; extra.mkdir()
        with self.assertRaises(ValueError): self.ingest()
        extra.rmdir()
        os.link(case / 'report.md', self.root / 'linked-report.md')
        with self.assertRaises(ValueError): self.ingest()
        self.assertFalse(self.destination.exists())

    def test_large_accepted_pack_is_archived_without_raising_library_file_limits(self):
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        for lines in (('Revenue was 100 CNY.', 'Cash flow was 20 CNY.'), ('Page two unique text.',),
                      ('Page three unique text.',), ('Page four unique text.',)):
            writer.add_page(PdfReader(io.BytesIO(research_tests.pdf_bytes(lines))).pages[0])
        buffer = io.BytesIO(); writer.write(buffer); raw = buffer.getvalue()
        (self.source / 'three.pdf').write_bytes(raw)
        row = copy.deepcopy(self.row); row['files'] = [{'source_path': 'three.pdf', 'sha256': ev.sha(raw), 'size_bytes': len(raw)}]
        source = self.root / 'multi-source'
        admitted = materials.ingest_material(self.source, source, {'schema':'ar.material-intake.v1',
            'library_id':'multi-page', 'created_at':'2020-01-06T12:00:00+08:00', 'materials':[row]})
        packet = copy.deepcopy(self.packet_request); packet['expected_library_hash'] = admitted['library_hash']
        packet['documents'][0].update(sha256=ev.sha(raw), pages=[1,2,3,4])
        packet['questions'][0]['citations'][0]['sha256'] = ev.sha(raw)
        pack = self.adapter().prepare_research_pack(source, packet, self.root / 'multi-pack')
        output = earnings.run(self.root / 'multi-pack', self.root / 'multi-case', expected_pack_hash=pack['pack_hash'])
        request = copy.deepcopy(self.request); request.update(expected_source_library_hash=admitted['library_hash'],
            expected_pack_hash=pack['pack_hash'], expected_result_hash=ev.sealed(output), result=output)
        try:
            receipt = self.module().ingest_result(source, self.root / 'multi-pack', self.root / 'multi-case/600000.SH',
                self.destination, self.root / 'multi-stage', request)
        except ValueError as exc:
            self.fail('A valid multi-page result must fit the existing per-material limit: ' + str(exc))
        stored = materials.verify_library(self.destination)
        self.assertTrue(all(len(r['files']) <= 16 for r in stored['materials']))
        self.assertEqual(len(self.query(receipt['library_hash'])['results']), 1)

    def test_contradictory_report_status_is_not_promoted(self):
        value = copy.deepcopy(self.request); value['result']['reports'][0]['data_status'] = 'HUMAN_APPROVED'
        value['expected_result_hash'] = ev.sealed(value['result'])
        with self.assertRaises(ValueError): self.ingest(value)
        self.assertFalse(self.destination.exists())

    def test_coherently_rehashed_case_cannot_replace_frozen_renderer_output(self):
        case = self.root / 'case/600000.SH'
        page = next((case / 'evidence/pages').glob('*.txt')); page.write_text('Replaced quotation.\n')
        receipt = ev.parse((case / 'receipt.json').read_bytes())
        receipt['outputs'][page.relative_to(case).as_posix()] = ev.sha(page.read_bytes())
        from experiments.research_workflows.evidence import canonical
        (case / 'receipt.json').write_bytes(canonical(receipt))
        current = {p.relative_to(case).as_posix():p.read_bytes() for p in case.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
        (case / 'SHA256SUMS').write_text(''.join(ev.sha(raw) + '  ' + name + '\n' for name, raw in sorted(current.items())))
        value = copy.deepcopy(self.request)
        value['result']['reports'][0]['receipt_sha256'] = ev.sha((case / 'receipt.json').read_bytes())
        value['expected_result_hash'] = ev.sealed(value['result'])
        with self.assertRaises(ValueError): self.ingest(value)
        self.assertFalse(self.destination.exists())

    def test_same_material_version_cannot_acknowledge_a_different_result(self):
        first = self.ingest()
        packet = copy.deepcopy(self.packet_request); packet['questions'][0]['question'] += ' Different version content.'
        pack = self.adapter().prepare_research_pack(self.library, packet, self.root / 'conflict-pack')
        output = earnings.run(self.root / 'conflict-pack', self.root / 'conflict-case', expected_pack_hash=pack['pack_hash'])
        value = copy.deepcopy(self.request); value.update(expected_pack_hash=pack['pack_hash'], result=output,
            expected_result_hash=ev.sealed(output), expected_destination_library_hash=first['library_hash'])
        with self.assertRaises(ValueError):
            self.module().ingest_result(self.library, self.root / 'conflict-pack', self.root / 'conflict-case/600000.SH',
                self.destination, self.root / 'conflict-stage', value)
        self.assertEqual(materials.verify_library(self.destination)['library_hash'], first['library_hash'])

    def test_appended_result_and_portable_query_preserve_prior_record(self):
        first = self.ingest()
        packet = copy.deepcopy(self.packet_request); packet['questions'][0]['question'] += ' A distinct draft.'
        pack = self.adapter().prepare_research_pack(self.library, packet, self.root / 'second-pack')
        output = earnings.run(self.root / 'second-pack', self.root / 'second-case', expected_pack_hash=pack['pack_hash'])
        request = copy.deepcopy(self.request); request.update(version='v2', expected_destination_library_hash=first['library_hash'],
            expected_pack_hash=pack['pack_hash'], expected_result_hash=ev.sealed(output), result=output)
        second = self.module().ingest_result(self.library, self.root / 'second-pack', self.root / 'second-case/600000.SH',
            self.destination, self.root / 'second-stage', request)
        self.assertEqual(len(self.query(second['library_hash'])['results']), 2)
        for name in ('library', 'pack', 'case', 'second-pack', 'second-case'):
            (self.root / name).rename(self.root / ('offline-' + name))
        self.assertEqual(len(self.query(second['library_hash'], research_date='20200106')['results']), 2)
        with self.assertRaises(ValueError): self.query(first['library_hash'])

    def test_succeeded_label_and_false_review_or_authority_cannot_be_imported(self):
        for field, replacement in (('human_review', 'PASS'), ('production_authority', True),
                                   ('paper_authority', True), ('status', 'STOP')):
            with self.subTest(field=field):
                value = copy.deepcopy(self.request); value['result'][field] = replacement
                value['expected_result_hash'] = ev.sealed(value['result'])
                with self.assertRaises(ValueError): self.ingest(value)
                self.assertFalse(self.destination.exists())

    def test_exact_retry_is_read_only_and_conflicting_version_refuses(self):
        first = self.ingest(); value = copy.deepcopy(self.request)
        value['expected_destination_library_hash'] = first['library_hash']
        second = self.ingest(value)
        self.assertEqual(second['disposition'], 'ALREADY_IMPORTED')
        self.assertEqual(second['library_hash'], first['library_hash'])
        self.assertFalse((self.root / 'stage-2').exists())
        value['version'] = 'v2'
        with self.assertRaises(ValueError): self.ingest(value)
        self.assertEqual(materials.verify_library(self.destination)['library_hash'], first['library_hash'])

    def test_first_destination_and_stale_append_guards_preserve_history(self):
        first = self.ingest()
        with self.assertRaises(ValueError): self.ingest()
        value = copy.deepcopy(self.request); value['expected_destination_library_hash'] = 'f' * 64
        with self.assertRaises(ValueError): self.ingest(value)
        self.assertEqual(materials.verify_library(self.destination)['library_hash'], first['library_hash'])

    def test_locked_material_append_rejects_stale_pin_without_new_registration(self):
        self.module()
        original = materials.verify_library(self.library)
        row = copy.deepcopy(self.row); row['material_id'] = 'new-original'; row['version'] = 'v2'
        raw = b'Unique additional material.\n'; (self.source / 'extra.txt').write_bytes(raw)
        row['files'] = [{'source_path': 'extra.txt', 'sha256': ev.sha(raw), 'size_bytes': len(raw)}]
        manifest = {'schema': 'ar.material-intake.v1', 'library_id': original['library_id'],
                    'created_at': '2020-01-06T12:00:00+08:00', 'materials': [row]}
        with self.assertRaises(ValueError):
            materials.ingest_material(self.source, self.library, manifest, expected_library_hash='f' * 64)
        self.assertEqual(materials.verify_library(self.library)['library_hash'], original['library_hash'])
        with self.assertRaises(ValueError):
            materials.ingest_material(self.source, self.library, manifest, require_new=True)
        self.assertEqual(materials.verify_library(self.library)['library_hash'], original['library_hash'])

    def test_two_stale_appenders_have_one_winner_without_partial_registration(self):
        first = self.ingest()
        manifests = []
        for n in range(2):
            raw = ('Additional original ' + str(n)).encode(); filename = 'append-' + str(n) + '.txt'
            (self.source / filename).write_bytes(raw)
            row = copy.deepcopy(self.row); row.update(material_id='additional-' + str(n),
                files=[{'source_path':filename, 'sha256':ev.sha(raw), 'size_bytes':len(raw)}])
            manifests.append({'schema':'ar.material-intake.v1', 'library_id':'results-test',
                              'created_at':'2020-01-06T12:00:00+08:00', 'materials':[row]})
        def append(manifest):
            try:
                materials.ingest_material(self.source, self.destination, manifest, expected_library_hash=first['library_hash'])
                return 'COMMITTED'
            except ValueError:
                return 'STALE_REFUSED'
        with ThreadPoolExecutor(max_workers=2) as workers:
            statuses = list(workers.map(append, manifests))
        self.assertEqual(sorted(statuses), ['COMMITTED', 'STALE_REFUSED'])
        final = materials.verify_library(self.destination)
        self.assertEqual(len(final['registrations']), 2)
        self.assertEqual(len(self.query(final['library_hash'])['results']), 1)

    def test_every_interrupted_write_remains_blocked_or_fully_published(self):
        module = self.module(); original = module.backup.write_new
        calls = []
        def count(*args, **kwargs):
            calls.append(str(args[0])); return original(*args, **kwargs)
        with mock.patch.object(module.backup, 'write_new', side_effect=count):
            self.ingest(destination=self.root / 'complete-library', stage=self.root / 'complete-stage')
        for stop_at in range(1, len(calls) + 1):
            target = self.root / ('interrupted-library-' + str(stop_at))
            stage = self.root / ('interrupted-stage-' + str(stop_at)); observed = []
            def interrupted(*args, **kwargs):
                result = original(*args, **kwargs); observed.append(True)
                if len(observed) == stop_at: raise OSError('synthetic write interruption')
                return result
            with mock.patch.object(module.backup, 'write_new', side_effect=interrupted):
                with self.assertRaises(OSError): self.ingest(destination=target, stage=stage)
            with self.assertRaises((ValueError, OSError)): self.ingest(destination=target, stage=stage)
            try:
                verified = materials.verify_library(target)
            except (ValueError, OSError):
                continue
            if verified['materials']:
                view = module.query_results(target, expected_library_hash=verified['library_hash'])
                self.assertEqual(len(view['results']), 1)
                self.assertEqual(view['results'][0]['human_review'], 'PENDING')
            else:
                self.assertEqual(module.query_results(target, expected_library_hash=verified['library_hash'])['results'], [])
    def test_old_producer_identity_is_preserved_separately_from_importer(self):
        value = copy.deepcopy(self.request)
        value['result']['consumer_execution_identity']['code_sha'] = 'c' * 40
        value['expected_result_hash'] = ev.sealed(value['result'])
        receipt = self.ingest(value)
        row = self.query(receipt['library_hash'])['results'][0]
        self.assertEqual(row['consumer_execution_identity']['code_sha'], 'c' * 40)
        self.assertEqual(row['importer_execution_identity']['code_sha'], 'a' * 40)
        self.assertEqual(row['execution_attestation'], 'RECORDED_NOT_REMOTE_ATTESTED')

    def test_reopened_library_tamper_is_not_hidden_by_filters(self):
        receipt = self.ingest()
        registered = materials.verify_library(self.destination)
        path = next(name for name in registered['files'] if name.endswith('.md'))
        (self.destination / path).write_bytes(b'corrupted saved report')
        with self.assertRaises(ValueError): self.query(receipt['library_hash'], industry_key='NO_MATCH')

    def test_cli_intake_and_query_use_the_same_contract(self):
        self.module(); import foundation_cli as cli
        payload = {'source_library_root': str(self.library), 'pack_root': str(self.root / 'pack'),
                   'artifact_root': str(self.root / 'case/600000.SH'), 'staging_root': str(self.root / 'cli-stage'),
                   'intake': self.request}
        source = self.root / 'operator.json'; source.write_text(ev.canonical(payload))
        capture = io.StringIO()
        with mock.patch('sys.stdout', capture):
            self.assertEqual(cli.main(['research-result-ingest', '--request', str(source), '--write-root', str(self.destination)]), 0)
        pin = json.loads(capture.getvalue())['result']['library_hash']
        capture = io.StringIO()
        with mock.patch('sys.stdout', capture):
            self.assertEqual(cli.main(['research-results', '--library-root', str(self.destination), '--expected-library-hash', pin,
                                      '--industry', 'UNSPECIFIED', '--date', '20200106']), 0)
        self.assertEqual(len(json.loads(capture.getvalue())['result']['results']), 1)


if __name__ == '__main__':
    unittest.main()
