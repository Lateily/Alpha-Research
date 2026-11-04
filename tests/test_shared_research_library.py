"""Shared public-entry query regressions; no restricted content distribution."""
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts/llm'), str(ROOT / 'tests')]
from tests import test_foundation_results as result_tests
import nonprod_workbench as wb
import workbench_shared_workspace as shared
from workbench_workspace import WorkspaceError
from workbench_shared_test_support import OWNER, MEMBER, fixture_state, http


class SharedLibraryTests(unittest.TestCase):
    adapter, prepare = result_tests.ResultIndexTests.adapter, result_tests.ResultIndexTests.prepare
    module, ingest = result_tests.ResultIndexTests.module, result_tests.ResultIndexTests.ingest

    def setUp(self):
        result_tests.ResultIndexTests.setUp(self)
        self.pin = self.ingest()['library_hash']
        shared_root = self.root / 'shared'; shared_root.mkdir()
        self.store, self.system = fixture_state(shared_root)
        self.code_patch = mock.patch.object(shared, 'execution_identity', return_value={'code_sha': 'a'*40, 'source_tree_hash': 'b'*64})
        self.code_patch.start(); self.addCleanup(self.code_patch.stop)
        self.view = shared.SharedWorkspace(self.system)
        allow = self.root / 'members.json'; allow.write_text(json.dumps({'members': [MEMBER]})); allow.chmod(0o600)
        self.private = wb.private_access('https://workbench.test-tail.ts.net:8443', OWNER, allow)
        for name in ('socket', 'create_connection', 'getaddrinfo'):
            guard = mock.patch.object(socket, name, side_effect=AssertionError('unexpected network'))
            guard.start(); self.addCleanup(guard.stop)

    def configure(self, pin=None):
        self.view = shared.SharedWorkspace(self.system, research_library_root=self.destination,
                                          research_library_hash=pin or self.pin)

    def get(self, suffix='', actor=OWNER, extra=()):
        return http(self.store, self.system, self.private,
                    '/api/shared-workspace/research-library' + suffix, login=actor, extra=extra, shared=self.view)

    def test_unconfigured_is_explicit_not_an_empty_success(self):
        status, value = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(value['status'], 'NOT_CONFIGURED')
        self.assertEqual(value['results'], [])
        self.assertIsNone(value['library_hash'])
        self.assertFalse(value['content_sharing_allowed'])

    def test_owner_and_member_query_the_same_pinned_metadata_only(self):
        self.configure()
        for actor in (OWNER, MEMBER):
            with self.subTest(actor=actor):
                status, value = self.get('?industry_key=UNSPECIFIED&research_date=20200106&ts_code=600000.SH', actor)
                self.assertEqual(status, 200)
                self.assertEqual(value['schema'], 'ar.shared-research-library.v1')
                self.assertEqual(value['my_workspace']['login'], actor)
                self.assertEqual(value['consumer_code_sha'], 'a'*40)
                self.assertEqual(value['library_hash'], self.pin)
                self.assertEqual(value['total'], 1)
                row = value['results'][0]
                self.assertEqual(row['research_date'], '20200106')
                self.assertEqual(row['source_cutoff_at'], '2020-01-03T15:00:00+08:00')
                self.assertEqual(row['assessments'], ['UNRESOLVED'])
                self.assertEqual(row['human_review'], 'PENDING')
                for key in ('report', 'questions', 'excerpt', 'citations', 'artifact_files', 'pack_files', 'path'):
                    self.assertNotIn(key, row)
                self.assertFalse(value['content_sharing_allowed'])
                self.assertEqual(value['content_status'], 'RIGHTS_UNVERIFIED_CONTENT_DENIED')
                self.assertFalse(value['rights']['sharing_allowed'])
                self.assertFalse(value['production_authority'])
                self.assertFalse(value['paper_authority'])

    def test_filters_are_exact_and_research_date_is_not_source_day(self):
        self.configure()
        for suffix in ('?research_date=20200103', '?industry_key=OTHER', '?industry_taxonomy=OTHER',
                       '?taxonomy_version=OTHER', '?ts_code=600001.SH', '?page=1'):
            status, value = self.get(suffix)
            self.assertEqual(status, 200)
            self.assertEqual(value['results'], [])
        self.assertEqual(self.get('?research_date=20200103')[1]['status'], 'EMPTY')
        self.assertEqual(self.get('?page=1')[1]['total'], 1)

    def test_url_parser_refuses_unknown_duplicate_empty_and_bad_values(self):
        self.configure()
        for suffix in ('?path=/etc/passwd', '?library_hash='+'a'*64, '?research_date=20200106&research_date=20200103',
                       '?research_date=', '?research_date=20201301', '?page=-1', '?page=1000', '?page=true',
                       '?ts_code=../../secret', '?industry_key=%FF', '#fragment'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.get(suffix)[0], 400)

    def test_unknown_login_and_spoofed_duplicate_identity_cannot_query(self):
        self.configure()
        self.assertEqual(self.get(actor='unknown@example.com')[0], 403)
        self.assertEqual(self.get(extra=(('Tailscale-User-Login', MEMBER),))[0], 403)

    def test_changed_evidence_never_reuses_a_previous_success_even_for_empty_query(self):
        self.configure(); self.assertEqual(self.get()[0], 200)
        blob = next(self.destination.glob('registrations/*/files/*'))
        blob.write_bytes(blob.read_bytes() + b'tamper')
        status, value = self.get('?industry_key=NO_MATCH')
        self.assertEqual(status, 409)
        self.assertEqual(value['error'], 'RESEARCH_LIBRARY_EVIDENCE_INVALID')
        self.assertNotIn('results', value)

    def test_wrong_external_pin_and_incomplete_operator_flags_are_refused(self):
        with self.assertRaises(WorkspaceError): self.configure('f'*64)
        for config in ({'research_library_root': self.destination}, {'research_library_hash': self.pin}):
            with self.assertRaises(WorkspaceError): shared.SharedWorkspace(self.system, **config)

    def test_no_raw_content_or_write_route_is_exposed(self):
        self.configure()
        for path in ('/api/shared-workspace/research-library/report.md', '/api/shared-workspace/research-library/files/original.pdf'):
            self.assertEqual(http(self.store,self.system,self.private,path,shared=self.view)[0],404)
        self.assertEqual(http(self.store,self.system,self.private,'/api/shared-workspace/research-library',
                              body={'report':'x'},shared=self.view)[0],403)

    def test_projection_whitelist_cannot_leak_future_stored_content_fields(self):
        self.configure()
        original = self.module().query_results
        def future_fields(*args, **kwargs):
            value = original(*args, **kwargs)
            value['results'][0]['report'] = self.result['reports'][0]['report']
            value['results'][0]['source_documents'][0]['excerpt'] = 'restricted source excerpt'
            return value
        with mock.patch.object(self.module(), 'query_results', side_effect=future_fields):
            status, value = self.get()
        self.assertEqual(status, 200)
        self.assertNotIn('report', value['results'][0])
        self.assertNotIn('excerpt', value['results'][0]['source_documents'][0])

    def test_browser_response_context_is_closed(self):
        result = subprocess.run(['node','--test',str(ROOT/'tests/nonprod-research-library.test.mjs')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_startup_flags_cannot_enable_local_or_overlapping_access(self):
        for args in (['--research-library-root',str(self.destination)],
                     ['--research-library-hash',self.pin],
                     ['--research-library-root',str(self.destination),'--research-library-hash',self.pin]):
            with self.assertRaises(wb.WorkbenchError) as found: wb.main(args)
            self.assertEqual(found.exception.code,'RESEARCH_LIBRARY_CONFIGURATION_REQUIRED')
        args=['--private-origin',self.private.origin,'--owner-login',OWNER,
              '--private-allowlist',str(self.root/'members.json'),'--shared-workspace-v1',
              '--research-library-root',str(self.destination),'--research-library-hash',self.pin,
              '--state-root',str(self.destination/'overlap')]
        with self.assertRaises(wb.WorkbenchError) as found: wb.main(args)
        self.assertEqual(found.exception.code,'RESEARCH_LIBRARY_ROOT_OVERLAP')
        self.assertFalse((self.destination/'overlap').exists())

    def test_library_link_is_not_a_supported_operator_root(self):
        link=self.root/'library-link';link.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaises(WorkspaceError):
            shared.SharedWorkspace(self.system,research_library_root=link,research_library_hash=self.pin)

    def test_world_writable_library_is_refused_after_prior_success(self):
        self.configure(); self.assertEqual(self.get()[0],200)
        self.destination.chmod(0o777)
        self.assertEqual(self.get()[0],409)


if __name__ == '__main__': unittest.main()
