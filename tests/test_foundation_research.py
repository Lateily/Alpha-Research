"""Original PDF -> externally pinned pack -> existing local earnings job."""
import copy
import importlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, TextStringObject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/llm'))
import foundation_materials as materials
import workbench_evidence as ev


def pdf_bytes(lines=('Revenue was 100 CNY.', 'Cash flow was 20 CNY.')):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(('BT /F1 12 Tf 40 750 Td ' + ' '.join('(' + line + ') Tj 0 -18 Td' for line in lines) + ' ET').encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    result = io.BytesIO(); writer.write(result)
    return result.getvalue()


class MaterialResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        self.library = self.root / 'library'
        self.pdf = pdf_bytes(); (self.source / 'filing.pdf').write_bytes(self.pdf)
        self.row = {'material_id': 'issuer-filing', 'kind': 'original', 'version': 'v1',
            'title': 'Synthetic filing', 'industry_key': 'UNSPECIFIED', 'industry_taxonomy': 'UNSPECIFIED',
            'taxonomy_version': 'UNSPECIFIED', 'ts_code': '600000.SH', 'trade_date': '20200103',
            'run_id': 'synthetic-materials', 'code_sha': 'a' * 40,
            'published_at': '2020-01-02T08:00:00+08:00', 'available_at': '2020-01-02T09:00:00+08:00',
            'cutoff_at': '2020-01-03T15:00:00+08:00',
            'provenance': {'publisher': 'UNVERIFIED', 'provider_id': 'issuer-site',
                'source_locator': 'https://issuer.example.invalid/filing.pdf', 'captured_at': '2020-01-02T10:00:00+08:00'},
            'original_refs': [], 'files': [{'source_path': 'filing.pdf', 'sha256': ev.sha(self.pdf), 'size_bytes': len(self.pdf)}]}
        receipt = materials.ingest_material(self.source, self.library,
            {'schema': 'ar.material-intake.v1', 'library_id': 'synthetic-library',
             'created_at': '2020-01-06T12:00:00+08:00', 'materials': [self.row]})
        self.request = {'schema': 'ar.material-research-request.v1', 'company': '600000.SH',
            'as_of': '20200106', 'source_cutoff_at': '2020-01-03T15:00:00+08:00',
            'generated_at': '2020-01-06T18:00:00+08:00', 'expected_library_hash': receipt['library_hash'],
            'authoring': {'kind': 'AI_DRAFT', 'model': 'SYNTHETIC_TEST', 'prompt_version': 'materials-test.v1'},
            'documents': [{'material_id': 'issuer-filing', 'version': 'v1', 'sha256': ev.sha(self.pdf), 'pages': [1]}],
            'questions': [{'id': 'cash-quality', 'question': 'Does cash conversion support the reported revenue?',
                'criteria': {'metric': 'cash_conversion', 'operator': '>=', 'threshold': None, 'unit': 'ratio',
                    'measurement': 'same-period normalized figures', 'due_at': None, 'wrong_if': 'persistent cash gap'},
                'citations': [{'sha256': ev.sha(self.pdf), 'page': 1, 'start': 1, 'end': 1, 'expected': 'Revenue was 100 CNY.'}],
                'missing_evidence': ['Normalized cash flow and comparison period require review.']}]}
        for name in ('socket', 'create_connection', 'getaddrinfo'):
            guard = mock.patch.object(socket, name, side_effect=AssertionError('network not allowed'))
            guard.start(); self.addCleanup(guard.stop)

    def adapter(self):
        self.assertIsNotNone(importlib.util.find_spec('foundation_research'), 'real material research preparation is missing')
        adapter = importlib.import_module('foundation_research')
        if not getattr(self, '_identity_guard', None):
            self._identity_guard = mock.patch.object(adapter, '_execution_identity',
                return_value={'code_sha': 'a' * 40, 'source_tree_hash': 'b' * 64}, create=True)
            self._identity_guard.start(); self.addCleanup(self._identity_guard.stop)
            clock = mock.patch.object(adapter, '_observed_at', return_value='2020-01-06T18:30:00+08:00', create=True)
            clock.start(); self.addCleanup(clock.stop)
        return adapter

    def prepare(self, value=None, name='pack'):
        return self.adapter().prepare_research_pack(self.library, value or self.request, self.root / name)

    def test_real_pdf_prepare_verify_and_existing_earnings_renderer(self):
        adapter = self.adapter()
        result = self.prepare()
        verified = adapter.verify_research_pack(self.root / 'pack', result['pack_hash'])
        self.assertEqual(verified['company'], '600000.SH')
        self.assertEqual(verified['documents'], 1)
        self.assertEqual(verified['pages'], 1)
        self.assertEqual(verified['human_review'], 'PENDING')
        self.assertFalse(verified['production_authority'])
        self.assertEqual((self.root / 'pack/inputs/originals' / (ev.sha(self.pdf) + '.pdf')).read_bytes(), self.pdf)
        from experiments.research_workflows import trial
        request = json.loads((self.root / 'pack/requests/earnings-600000.SH.json').read_bytes())
        rendered = trial.build(request, self.root / 'pack/inputs')
        self.assertEqual(rendered['artifact']['rows'][0]['draft_assessment'], 'UNRESOLVED')
        self.assertIsNone(request['payload']['registered_at'])
        self.assertIn('Revenue was 100 CNY.', rendered['report'])
        self.assertIn('physical page 1', rendered['report'])
        self.assertEqual(request['sources']['questions']['published_on'], '20200106')

    def test_preparation_records_actual_code_identity_and_refuses_drift(self):
        adapter = self.adapter()
        prepared = self.prepare()
        self.assertEqual(prepared.get('preparation_execution_identity'), {'code_sha': 'a' * 40, 'source_tree_hash': 'b' * 64})
        with mock.patch.object(adapter, '_execution_identity', side_effect=[
                {'code_sha': 'a' * 40, 'source_tree_hash': 'b' * 64},
                {'code_sha': 'c' * 40, 'source_tree_hash': 'd' * 64}]):
            with self.assertRaisesRegex(ValueError, 'CODE_CHANGED'):
                self.prepare(name='drift')
        self.assertFalse((self.root / 'drift').exists())

    def test_wrong_library_hash_and_unadmitted_documents_never_write(self):
        for name in ('hash', 'quarantine', 'company', 'document-sha'):
            with self.subTest(name=name):
                value = copy.deepcopy(self.request)
                if name == 'hash': value['expected_library_hash'] = 'f' * 64
                if name == 'quarantine': value['documents'][0]['material_id'] = 'quarantined-original'
                if name == 'company': value['company'] = '600001.SH'
                if name == 'document-sha': value['documents'][0]['sha256'] = 'f' * 64
                with self.assertRaises(ValueError): self.prepare(value, name)
                self.assertFalse((self.root / name).exists())

    def test_quotes_are_checked_against_selected_pdf_not_request_self_claims(self):
        for name in ('wrong-text', 'wrong-page', 'missing-line', 'inverted-lines'):
            with self.subTest(name=name):
                value = copy.deepcopy(self.request); citation = value['questions'][0]['citations'][0]
                if name == 'wrong-text': citation['expected'] = 'Revenue was 999 CNY.'
                if name == 'wrong-page': citation['page'] = 2
                if name == 'missing-line': citation['end'] = 9000
                if name == 'inverted-lines': citation.update(start=2, end=1)
                with self.assertRaises(ValueError): self.prepare(value, name)
                self.assertFalse((self.root / name).exists())

    def test_source_cutoff_and_new_question_dates_cannot_be_backdated(self):
        for name in ('future-source', 'backdated-question', 'future-cutoff'):
            with self.subTest(name=name):
                value = copy.deepcopy(self.request)
                if name == 'future-source': value['source_cutoff_at'] = '2020-01-01T15:00:00+08:00'
                if name == 'backdated-question': value['generated_at'] = '2020-01-07T18:00:00+08:00'
                if name == 'future-cutoff': value['source_cutoff_at'] = '2020-01-07T15:00:00+08:00'
                with self.assertRaises(ValueError): self.prepare(value, name)
                self.assertFalse((self.root / name).exists())

    def test_closed_request_limits_and_no_automatic_assessment(self):
        for name in ('pages-bool', 'duplicate-pages', 'empty-gaps', 'question-verdict', 'duplicate-question', 'too-many-pages'):
            with self.subTest(name=name):
                value = copy.deepcopy(self.request)
                if name == 'pages-bool': value['documents'][0]['pages'] = [True]
                if name == 'duplicate-pages': value['documents'][0]['pages'] = [1, 1]
                if name == 'empty-gaps': value['questions'][0]['missing_evidence'] = []
                if name == 'question-verdict': value['questions'][0]['assessment'] = 'SUPPORTS'
                if name == 'duplicate-question': value['questions'] *= 2
                if name == 'too-many-pages': value['documents'][0]['pages'] = list(range(1, 34))
                with self.assertRaises(ValueError): self.prepare(value, name)
                self.assertFalse((self.root / name).exists())

    def reseal(self, root):
        marker = json.loads((root / 'material-pack.json').read_bytes())
        marker['files'] = {name: ev.sha((root / name).read_bytes()) for name in marker['files']}
        marker['pack_hash'] = ev.sealed({k: v for k, v in marker.items() if k != 'pack_hash'})
        (root / 'material-pack.json').write_text(ev.canonical(marker))
        return marker['pack_hash']

    def test_coherent_reseal_cannot_replace_external_pin(self):
        receipt = self.prepare()
        request = copy.deepcopy(self.request); request['questions'][0]['question'] = 'Different valid new draft'
        self.prepare(request, 'replacement'); root = self.root / 'replacement'
        with self.assertRaisesRegex(ValueError, 'PACK_PIN_MISMATCH'):
            self.adapter().verify_research_pack(root, receipt['pack_hash'])

    def test_page_text_is_rederived_even_with_a_new_coherent_pin(self):
        self.prepare(); root = self.root / 'pack'
        page = next((root / 'inputs/pages').glob('*.txt'))
        page.write_text('Revenue was 999 CNY.\n')
        with self.assertRaisesRegex(ValueError, 'DERIVATION_MISMATCH'):
            self.adapter().verify_research_pack(root, self.reseal(root))

    def test_missing_extra_and_symlink_files_are_rejected(self):
        for name in ('missing', 'extra', 'symlink'):
            with self.subTest(name=name):
                receipt = self.prepare(name=name); root = self.root / name
                target = root / 'inputs/questions.json'
                if name == 'missing': target.unlink()
                if name == 'extra': (root / 'extra.txt').write_text('extra')
                if name == 'symlink':
                    original = self.root / 'original-questions.json'; target.rename(original); target.symlink_to(original)
                with self.assertRaises(ValueError): self.adapter().verify_research_pack(root, receipt['pack_hash'])

    def test_extra_regular_file_cannot_be_ignored_by_pack_verifier(self):
        receipt = self.prepare(); root = self.root / 'pack'
        (root / 'unregistered.txt').write_text('not in the frozen input')
        with self.assertRaises(ValueError): self.adapter().verify_research_pack(root, receipt['pack_hash'])

    def test_existing_pack_and_output_aliases_do_not_overwrite_history(self):
        self.prepare(); before = {str(p): p.read_bytes() for p in (self.root / 'pack').rglob('*') if p.is_file()}
        with self.assertRaises((ValueError, OSError)): self.prepare()
        self.assertEqual(before, {str(p): p.read_bytes() for p in (self.root / 'pack').rglob('*') if p.is_file()})
        alias = self.root / 'alias'; alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)): self.prepare(name='alias/new-pack')
        self.assertFalse((self.source / 'new-pack').exists())

    def test_blank_and_oversize_pdf_extraction_refuses_without_network(self):
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
        raw = io.BytesIO(); writer.write(raw)
        for data in (raw.getvalue(), b'%PDF-' + b' ' * (12 * 1024 * 1024)):
            with self.assertRaises(ValueError): self.adapter().extract_pages(data, [1])

    def test_material_pack_job_requires_external_pin_before_rendering(self):
        self.prepare()
        import workbench_earnings_trial as earnings
        with self.assertRaisesRegex(ValueError, 'PIN_REQUIRED'):
            earnings.run(self.root / 'pack', self.root / 'result')
        self.assertFalse((self.root / 'result').exists())

    def test_interrupted_material_root_never_downgrades_to_legacy_job(self):
        adapter = self.adapter()
        original = adapter.backup.write_new
        def crash(path, raw, **kwargs):
            if Path(path).name == adapter.MARKER:
                raise OSError('crash before sealing')
            return original(path, raw, **kwargs)
        with mock.patch.object(adapter.backup, 'write_new', side_effect=crash):
            with self.assertRaises(OSError): self.prepare()
        pdf = next((self.root / 'pack/inputs/originals').glob('*.pdf'))
        pdf.write_bytes(pdf_bytes(('Different original.',)))
        import nonprod_workbench as wb
        import workbench_workspace as ws
        system = ws.Workspace(wb.Store(self.root / 'interrupted-state'), earnings_pack_root=self.root / 'pack')
        job = system.start_job({'command_id': 'interrupted-material-001', 'kind': 'earnings-trial'})
        self.assertEqual(job['status'], 'STOP')
        self.assertIn('PIN_REQUIRED', job['result']['error'])
        self.assertFalse(any((self.root / 'interrupted-state').rglob('report.md')))

    def test_observed_preparation_time_is_not_caller_asserted_history(self):
        adapter = self.adapter()
        with mock.patch.object(adapter, '_observed_at', return_value='2026-11-04T18:00:00+08:00', create=True):
            with self.assertRaisesRegex(ValueError, 'DRAFT_DATE_NOT_OBSERVED'):
                self.prepare(name='backdated')
        self.assertFalse((self.root / 'backdated').exists())
        result = self.prepare()
        self.assertEqual(result['prepared_at'], '2020-01-06T18:30:00+08:00')
        trial = json.loads((self.root / 'pack/requests/earnings-600000.SH.json').read_bytes())
        self.assertEqual(trial['sources']['questions']['observed_at'], result['prepared_at'])
        self.assertEqual(trial['generated_at'], result['prepared_at'])
        self.assertNotEqual(trial['generated_at'], self.request['generated_at'])
        self.assertEqual(adapter.verify_research_pack(self.root / 'pack', result['pack_hash'])['prepared_at'], result['prepared_at'])

    def test_utc_midnight_boundary_preflights_and_renders_with_normalized_time(self):
        adapter = self.adapter()
        value = copy.deepcopy(self.request)
        value.update(as_of='20200107', generated_at='2020-01-06T18:00:00Z')
        import workbench_earnings_trial as earnings
        try:
            with mock.patch.object(adapter, '_observed_at', return_value='2020-01-06T18:30:00Z', create=True):
                receipt = self.prepare(value)
            result = earnings.run(self.root / 'pack', self.root / 'utc-result', expected_pack_hash=receipt['pack_hash'])
        except ValueError as exc:
            self.fail('Valid UTC-boundary input must prepare and render: ' + str(exc))
        self.assertEqual(result['status'], 'COMPLETED_HISTORICAL_EARNINGS')
        trial = json.loads((self.root / 'pack/requests/earnings-600000.SH.json').read_bytes())
        self.assertEqual(trial['generated_at'], '2020-01-07T02:30:00+08:00')

    def test_decoded_active_pdf_names_are_refused_through_admission_and_prepare(self):
        class EscapedName(NameObject):
            def write_to_stream(self, stream, encryption_key=None):
                stream.write(str(self).replace('OpenAction', 'Open#41ction').replace('JavaScript', 'Java#53cript').replace('/JS', '/#4A#53').encode())
        writer = PdfWriter(clone_from=io.BytesIO(self.pdf))
        writer._root_object[EscapedName('/OpenAction')] = DictionaryObject({
            NameObject('/S'): EscapedName('/JavaScript'), EscapedName('/JS'): TextStringObject('void(0)')})
        buffer = io.BytesIO(); writer.write(buffer); raw = buffer.getvalue()
        self.assertIsNone(materials.ACTIVE_PDF.search(raw))
        (self.source / 'active.pdf').write_bytes(raw)
        row = copy.deepcopy(self.row); row['files'] = [{'source_path': 'active.pdf', 'sha256': ev.sha(raw), 'size_bytes': len(raw)}]
        admitted = materials.ingest_material(self.source, self.root / 'active-library', {
            'schema': 'ar.material-intake.v1', 'library_id': 'active-test',
            'created_at': '2020-01-06T12:00:00+08:00', 'materials': [row]})
        value = copy.deepcopy(self.request); value['expected_library_hash'] = admitted['library_hash']
        value['documents'][0]['sha256'] = value['questions'][0]['citations'][0]['sha256'] = ev.sha(raw)
        with self.assertRaises(ValueError):
            self.adapter().prepare_research_pack(self.root / 'active-library', value, self.root / 'active-pack')
        self.assertFalse((self.root / 'active-pack').exists())

    def test_job_rejects_wrong_external_pin_before_any_report(self):
        self.prepare()
        import workbench_earnings_trial as earnings
        with self.assertRaises(ValueError):
            earnings.run(self.root / 'pack', self.root / 'result', expected_pack_hash='f' * 64)
        self.assertFalse((self.root / 'result').exists())

    def test_pack_changed_during_render_is_not_success(self):
        receipt = self.prepare()
        import workbench_earnings_trial as earnings
        from experiments.research_workflows import trial
        original = trial.write_trial
        def change_after_write(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.root / 'pack/inputs/questions.json').write_text('changed during render')
            return result
        with mock.patch.object(trial, 'write_trial', side_effect=change_after_write):
            with self.assertRaises(ValueError):
                earnings.run(self.root / 'pack', self.root / 'result', expected_pack_hash=receipt['pack_hash'])
        self.assertTrue((self.root / 'result').exists())

    def test_each_interrupted_write_is_retained_and_cannot_fake_completeness(self):
        adapter = self.adapter(); complete = self.prepare()
        count = len(complete['files']) + 1
        original = adapter.backup.write_new
        for stop_at in range(1, count + 1):
            name = 'crash-' + str(stop_at); calls = []
            def interrupted(*args, **kwargs):
                result = original(*args, **kwargs)
                calls.append(True)
                if len(calls) == stop_at: raise OSError('synthetic write interruption')
                return result
            with mock.patch.object(adapter.backup, 'write_new', side_effect=interrupted):
                with self.assertRaises(OSError): self.prepare(name=name)
            with self.assertRaises((ValueError, OSError)): self.prepare(name=name)
            root = self.root / name
            if stop_at == count:
                self.assertEqual(adapter.verify_research_pack(root, complete['pack_hash'])['questions'], 1)
            else:
                with self.assertRaises((ValueError, OSError)): adapter.verify_research_pack(root, complete['pack_hash'])
            import workbench_earnings_trial as earnings
            with self.assertRaisesRegex(ValueError, 'PIN_REQUIRED'):
                earnings.run(root, self.root / ('crash-result-' + str(stop_at)))
            self.assertEqual((self.source / 'filing.pdf').read_bytes(), self.pdf)

    def test_existing_workspace_executes_bound_pack_but_private_mode_denies_it(self):
        receipt = self.prepare()
        import nonprod_workbench as wb
        import workbench_workspace as ws
        try:
            system = ws.Workspace(wb.Store(self.root / 'state'), earnings_pack_root=self.root / 'pack',
                                  earnings_pack_hash=receipt['pack_hash'])
        except TypeError:
            self.fail('existing earnings workspace has no independent material pack binding')
        result = system.start_job({'command_id': 'material-job-001', 'kind': 'earnings-trial'})
        self.assertEqual(result['status'], 'SUCCEEDED')
        job = system.snapshot()['jobs'][-1]
        self.assertEqual(job['result']['material_pack']['pack_hash'], receipt['pack_hash'])
        self.assertEqual(job['result']['human_review'], 'PENDING')
        reopened = ws.Workspace(wb.Store(self.root / 'state'), earnings_pack_root=self.root / 'pack',
                                earnings_pack_hash=receipt['pack_hash'])
        self.assertEqual(reopened.start_job({'command_id': 'material-job-001', 'kind': 'earnings-trial'})['disposition'], 'IDEMPOTENT')
        private = ws.Workspace(wb.Store(self.root / 'private'), earnings_pack_root=self.root / 'pack',
            earnings_pack_hash=receipt['pack_hash'], private_mode=True)
        with self.assertRaises(ws.WorkspaceError):
            private.start_job({'command_id': 'private-material-001', 'kind': 'earnings-trial'}, actor='owner@example.com')

    def test_offline_cli_prepares_and_verifies_real_entrypoint(self):
        self.adapter()
        import foundation_cli as cli
        path = self.root / 'operator-request.json'; path.write_text(ev.canonical(self.request))
        out = io.StringIO()
        with mock.patch('sys.stdout', out):
            code = cli.main(['research-pack', '--library-root', str(self.library), '--request', str(path), '--write-root', str(self.root / 'cli-pack')])
        self.assertEqual(code, 0)
        receipt = json.loads(out.getvalue())['result']
        with mock.patch('sys.stdout', io.StringIO()):
            self.assertEqual(cli.main(['research-pack-verify', '--pack-root', str(self.root / 'cli-pack'), '--expected-pack-hash', receipt['pack_hash']]), 0)


if __name__ == '__main__':
    unittest.main()
