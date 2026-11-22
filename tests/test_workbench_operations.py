"""Isolated operations controls; no launchctl, real service, or host actions."""
import copy
import importlib.util
from pathlib import Path
import plistlib
import py_compile
import sqlite3
import sys
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/llm'))
import workbench_backup as backup
import workbench_evidence as ev
import nonprod_workbench as wb


class OperationsTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('workbench_operations'),
                             'isolated operations safeguards are missing')
        import workbench_operations
        return workbench_operations

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def capsule(self):
        m = self.module()
        root = self.base / 'capsule'; root.mkdir(mode=0o700)
        profile = root / 'profile.json'; profile.write_text('{}')
        value = {'root': str(root), 'code_root': str(ROOT),
                 'code_identity': {'code_sha': 'a'*40}, 'environment_root': str(self.base/'env')}
        return m, profile, value

    def prepared(self):
        m, profile, value = self.capsule()
        with patch.object(m.recovery, 'verify', return_value=value), \
             patch.object(m.runtime, 'verify_environment', return_value={'base_executable': str(Path(sys.executable).resolve())}), \
             patch.object(m, '_code_sources', return_value=self.source_pins(ROOT), create=True):
            value['environment_hash'] = 'a'*64
            result = m.prepare(self.base/'operations', profile, ev.sha(b'{}'))
        return m, result, profile, value

    def source_pins(self, code):
        names = ('workbench_operations.py','workbench_operations_boot.py','workbench_backup.py',
                 'workbench_backup_chunks.py','workbench_evidence.py','workbench_recovery.py',
                 'workbench_runtime_env.py','workbench_runtime_service.py')
        return {'scripts/llm/'+name: ev.sha((code/'scripts/llm'/name).read_bytes())
                for name in names if (code/'scripts/llm'/name).exists()}

    def test_prepares_not_installed_template_without_service_or_install(self):
        m, result, profile, value = self.prepared()
        self.assertEqual(result['template_status'], 'GENERATED_NOT_INSTALLED')
        template = plistlib.loads((self.base/'operations/launchd.NOT_INSTALLED.plist').read_bytes())
        self.assertTrue(template['RunAtLoad'])
        self.assertEqual(template['KeepAlive'], {'SuccessfulExit': False})
        self.assertEqual(template['ThrottleInterval'], 60)
        self.assertIn('--resident', template['ProgramArguments'])
        self.assertNotIn('UserName', template)
        self.assertEqual(result['physical_host_reboot'], 'NOT_ATTESTED')
        self.assertFalse(result['installed'])
        with patch.object(m.recovery, 'verify', return_value=value):
            self.assertEqual(m.verify(self.base/'operations', result['operations_hash'])['recovery_pin'], ev.sha(b'{}'))

    def test_wrong_external_pin_and_changed_manifest_refuse_before_recovery(self):
        m, result, profile, value = self.prepared()
        with patch.object(m.recovery, 'verify', return_value=value) as verify:
            with self.assertRaisesRegex(ValueError, 'OPERATIONS_PIN'):
                m.verify(self.base/'operations', '0'*64)
            verify.assert_not_called()
        root = self.base/'operations'; manifest = ev.parse((root/'operations.json').read_bytes())
        manifest['max_crashes'] = 99; raw = ev.canonical(manifest).encode()
        (root/'operations.json').write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'OPERATIONS_MANIFEST'):
            m.verify(root, ev.sha(raw))

    def test_rejects_overlapping_existing_or_repository_roots(self):
        m, profile, value = self.capsule()
        with patch.object(m.recovery, 'verify', return_value=value):
            for root in (profile.parent, profile.parent/'nested', ROOT/'unapproved-ops'):
                with self.subTest(root=root), self.assertRaises(ValueError):
                    m.prepare(root, profile, ev.sha(b'{}'))
        self.assertFalse((ROOT/'unapproved-ops').exists())

    def test_crash_budget_survives_journal_reopen_and_is_not_reset_by_clean_exit(self):
        m = self.module(); root = self.base/'journal'
        for number in range(3):
            journal = m.Journal(root, 'b'*64, initialize=number==0)
            token = journal.reserve()
            self.assertEqual(journal.finish(token, -9, planned=False)['crashes'], number+1)
            if number == 0:
                token = journal.reserve()
                self.assertEqual(journal.finish(token, 0, planned=False)['crashes'], 1)
        with self.assertRaisesRegex(ValueError, 'OPERATIONS_FENCED'):
            m.Journal(root, 'b'*64).reserve()
        self.assertEqual(m.Journal(root, 'b'*64).snapshot()['crashes'], 3)

    def test_uncertain_reservation_fences_without_adopting_or_killing_old_pid(self):
        m = self.module(); root = self.base/'journal'
        journal = m.Journal(root, 'b'*64, initialize=True); journal.reserve()
        with self.assertRaisesRegex(ValueError, 'OPERATIONS_UNCERTAIN_START'):
            m.Journal(root, 'b'*64).reserve()
        self.assertEqual(m.Journal(root, 'b'*64).snapshot()['status'], 'FENCED')

    def test_journal_wrong_pin_and_wrong_completion_token_are_rejected(self):
        m = self.module(); journal = m.Journal(self.base/'journal', 'b'*64, initialize=True)
        token = journal.reserve()
        with self.assertRaisesRegex(ValueError, 'OPERATIONS_JOURNAL_BINDING'):
            m.Journal(self.base/'journal', 'c'*64)
        with self.assertRaisesRegex(ValueError, 'OPERATIONS_ATTEMPT_BINDING'):
            journal.finish('not-the-attempt', 0, planned=True)
        self.assertEqual(journal.snapshot()['active'], token)

    def test_planned_stop_does_not_spend_crash_budget(self):
        m = self.module(); journal = m.Journal(self.base/'journal', 'b'*64, initialize=True)
        token = journal.reserve(); result = journal.finish(token, -2, planned=True)
        self.assertEqual(result['crashes'], 0)
        self.assertEqual(result['status'], 'STOPPED')
        self.assertIsNone(result['active'])

    def test_changed_control_row_cannot_clear_a_durable_crash(self):
        m = self.module(); root = self.base/'journal'; journal = m.Journal(root,'b'*64,initialize=True)
        token = journal.reserve(); journal.finish(token,-9,planned=False)
        with sqlite3.connect(root/'operations.sqlite3') as db:
            db.execute('UPDATE control SET crashes=0')
        with self.assertRaisesRegex(ValueError,'OPERATIONS_JOURNAL_DAMAGED'):
            m.Journal(root,'b'*64)

    def test_backup_rehearsal_restores_newest_rows_and_never_replaces_old(self):
        m = self.module(); store = wb.Store(self.base/'state', shared_v1=True)
        with store.connect() as db:
            db.execute('INSERT INTO shared_workspaces VALUES (?,?)', ('owner@example.com', '11111111-1111-4111-8111-111111111111'))
        old = backup.backup_shared(store, self.base/'old')['backup_hash']
        with store.connect() as db:
            db.execute('INSERT INTO shared_workspaces VALUES (?,?)', ('member@example.com', '22222222-2222-4222-8222-222222222222'))
        result = m.rehearse_backup(store, self.base/'newest')
        self.assertNotEqual(result['backup_hash'], old)
        self.assertEqual(result['status'], 'LOCAL_NEWEST_RESTORE_VERIFIED')
        restored = self.base/'newest/restored/shared-workbench.sqlite3'
        with sqlite3.connect(restored) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM shared_workspaces').fetchone()[0], 2)
        self.assertFalse(result['credentials_restored'])
        self.assertEqual(result['other_machine_restore'], 'NOT_ATTESTED')
        before = restored.read_bytes()
        with self.assertRaisesRegex(ValueError, 'OPERATIONS_NEW_ROOT'):
            m.rehearse_backup(store, self.base/'newest')
        self.assertEqual(restored.read_bytes(), before)

    def test_backup_overlap_and_corrupt_archive_refused(self):
        m = self.module(); store = wb.Store(self.base/'state', shared_v1=True)
        with self.assertRaisesRegex(ValueError, 'OPERATIONS_ROOT_OVERLAP'):
            m.rehearse_backup(store, self.base/'state/backup')
        result = m.rehearse_backup(store, self.base/'copy')
        (self.base/'copy/archive/manifest.json').write_text('{}')
        with self.assertRaises(ValueError):
            m.verify_backup_rehearsal(self.base/'copy', result['receipt_hash'])

    def test_resealed_receipt_cannot_substitute_another_generation(self):
        m = self.module(); store = wb.Store(self.base/'state', shared_v1=True)
        m.rehearse_backup(store, self.base/'copy')
        path = self.base/'copy/receipt.json'; receipt = ev.parse(path.read_bytes())
        receipt['backup_hash'] = '0'*64
        raw = ev.canonical(receipt).encode(); path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'OPERATIONS_RESTORE_GENERATION_BINDING'):
            m.verify_backup_rehearsal(self.base/'copy', ev.sha(raw))

    def test_supervisor_stops_after_three_owned_child_crashes(self):
        m, result, profile, value = self.prepared()
        manifest = ev.parse((self.base/'operations/operations.json').read_bytes())
        children = [Mock(returncode=-9) for _ in range(3)]
        for child in children:
            child.poll.return_value = -9; child.wait.return_value = -9
        with patch.object(m, 'verify', return_value=manifest), \
             patch.object(m.recovery, 'verify', return_value=value), \
             patch.object(m.subprocess, 'Popen', side_effect=children) as start:
            final = m.serve(self.base/'operations', result['operations_hash'], seconds=5)
        self.assertEqual(final['status'], 'FENCED')
        self.assertEqual(start.call_count, 3)
        for child in children: child.send_signal.assert_not_called()
        with patch.object(m, 'verify', return_value=manifest), \
             patch.object(m.recovery, 'verify', return_value=value), \
             patch.object(m.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ValueError, 'OPERATIONS_FENCED'):
                m.serve(self.base/'operations', result['operations_hash'], seconds=1)
            start.assert_not_called()

    def test_duplicate_supervisor_and_changed_preflight_never_start_child(self):
        m, result, profile, value = self.prepared()
        manifest = ev.parse((self.base/'operations/operations.json').read_bytes())
        with patch.object(m, 'verify', return_value=manifest), \
             patch.object(m.subprocess, 'Popen') as start, m.service.exclusive_lock(profile.parent):
            with self.assertRaisesRegex(ValueError,'SERVICE_ALREADY_RUNNING'):
                m.serve(self.base/'operations',result['operations_hash'],1)
            start.assert_not_called()
        with patch.object(m, 'verify', side_effect=[manifest, ValueError('CHANGED_SOURCE')]), \
             patch.object(m.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ValueError,'CHANGED_SOURCE'):
                m.serve(self.base/'operations',result['operations_hash'],1)
            start.assert_not_called()

    def test_new_comments_after_old_backup_survive_newest_restore(self):
        from test_workbench_review_portal import ReviewPortalTests
        case = ReviewPortalTests(); self.addCleanup(case.doCleanups)
        with patch.object(tempfile, 'tempdir', str(self.base)): case.setUp()
        portal, record = case.admitted()
        backup.backup_shared(case.store, self.base/'before-comment')
        command = case.command(record)
        added = portal.submit(command, 'member@example.com')['annotation']
        result = self.module().rehearse_backup(case.store, self.base/'after-comment')
        manifest, data = backup.read_shared(self.base/'after-comment/archive')
        self.assertEqual(result['backup_hash'], manifest['backup_hash'])
        with sqlite3.connect(self.base/'after-comment/restored/shared-workbench.sqlite3') as db:
            events = [ev.parse(row[0]) for row in db.execute('SELECT body FROM workspace_events ORDER BY seq')]
        self.assertTrue(any({**event['data'], 'at':event['at'], 'event_hash':event['event_hash']} == added
                            for event in events if event['kind'] == 'REVIEW_ANNOTATION'))

    def alternate_root(self, exhausted):
        m, result, profile, value = self.prepared()
        journal = m.Journal(self.base/'operations',result['operations_hash'])
        if exhausted:
            for _ in range(3): journal.finish(journal.reserve(),-9,planned=False)
        else: journal.reserve()
        before = journal.snapshot()
        with patch.object(m.recovery,'verify',return_value=value), \
             patch.object(m.runtime,'verify_environment',return_value={'base_executable':str(Path(sys.executable).resolve())}), \
             patch.object(m,'_code_sources',return_value=self.source_pins(ROOT),create=True):
            with self.assertRaisesRegex(ValueError,'OPERATIONS_CAPSULE_ALREADY_BOUND'):
                m.prepare(self.base/'replacement',profile,ev.sha(b'{}'))
        self.assertFalse((self.base/'replacement').exists())
        self.assertEqual(journal.snapshot(),before)

    def test_alternate_root_cannot_reset_uncertain_reservation(self): self.alternate_root(False)
    def test_alternate_root_cannot_reset_exhausted_budget(self): self.alternate_root(True)

    def test_resealed_alternate_root_does_not_gain_capsule_authority(self):
        m,result,profile,value = self.prepared()
        replacement = self.base/'replacement'; replacement.mkdir(mode=0o700)
        body = ev.parse((self.base/'operations/operations.json').read_bytes())
        body['root'] = str(replacement); raw = ev.canonical(body).encode()
        (replacement/'operations.json').write_bytes(raw)
        with patch.object(m.recovery,'verify',return_value=value):
            with self.assertRaisesRegex(ValueError,'OPERATIONS_CAPSULE_BINDING'):
                m.verify(replacement,ev.sha(raw))

    def test_generated_boot_refuses_changed_helper_and_ignored_sourceless_before_execution(self):
        m = self.module()
        for kind in ('helper','sourceless','entry'):
            with self.subTest(kind=kind):
                base = self.base/kind; base.mkdir()
                code = base/'code'; sources = code/'scripts/llm'; sources.mkdir(parents=True)
                for name in self.source_pins(ROOT):
                    shutil.copyfile(ROOT/name,code/name)
                capsule = base/'capsule'; capsule.mkdir(mode=0o700)
                environment = base/'environment'; (environment/'venv/bin').mkdir(parents=True)
                (environment/'venv/bin/python3').write_bytes(b'not executed before full verification')
                (code/'config').mkdir()
                shutil.copyfile(ROOT/'config/shared-runtime.lock.json',code/'config/shared-runtime.lock.json')
                executable = str(Path(sys.executable).resolve())
                env_raw = ev.canonical({'schema':'ar.isolated-runtime.v1','lock_hash':ev.sealed(m.runtime.LOCK),
                    'python_version':'3.12.14','base_executable':executable,'base_hash':m.runtime.file_hash(executable),
                    'dependencies':m.runtime.LOCK['dependencies'],'files':m.runtime.inventory(environment),
                    'scope':'ISOLATED_ONLY','production_authority':False}).encode()
                (environment/'runtime.json').write_bytes(env_raw)
                profile = capsule/'profile.json'
                profile.write_text(ev.canonical({'environment_root':str(environment),'environment_hash':ev.sha(env_raw)}))
                value = {'root':str(capsule),'code_root':str(code),'environment_root':str(base/'environment'),
                         'environment_hash':'a'*64,'code_identity':{'code_sha':'a'*40}}
                with patch.object(m.recovery,'verify',return_value=value), \
                     patch.object(m.runtime,'verify_environment',return_value={'base_executable':str(Path(sys.executable).resolve())}), \
                     patch.object(m,'_code_sources',return_value=self.source_pins(code),create=True):
                    receipt = m.prepare(base/'operations',profile,ev.sha(profile.read_bytes()))
                argv = plistlib.loads((base/'operations/launchd.NOT_INSTALLED.plist').read_bytes())['ProgramArguments']
                control = subprocess.run(argv,env=m.runtime.clean_environment(base),capture_output=True,timeout=15)
                self.assertIn(b'ISOLATED_OPERATIONS_REFUSED',control.stderr)
                marker = base/'unverified-import-executed'
                payload = 'from pathlib import Path\nPath(%r).write_text("executed")\n' % str(marker)
                if kind == 'helper': (sources/'workbench_backup.py').write_text(payload)
                elif kind == 'entry': (sources/'workbench_operations_boot.py').write_text(payload)
                else:
                    path = base/'payload.py'; path.write_text(payload)
                    py_compile.compile(str(path),cfile=str(sources/'fcntl.pyc'),doraise=True)
                result = subprocess.run(argv,env=m.runtime.clean_environment(base),capture_output=True,timeout=15)
                self.assertFalse(marker.exists(),result.stderr.decode())
                self.assertNotEqual(result.returncode,0)

    def test_template_does_not_repin_boot_changed_after_validation(self):
        m = self.module(); base = self.base; code = base/'code'; sources = code/'scripts/llm'
        sources.mkdir(parents=True)
        for name in self.source_pins(ROOT): shutil.copyfile(ROOT/name,code/name)
        capsule = base/'capsule'; capsule.mkdir(mode=0o700)
        profile = capsule/'profile.json'; profile.write_text('{}')
        value = {'root':str(capsule),'code_root':str(code),'environment_root':str(base/'environment'),
                 'environment_hash':'a'*64,'code_identity':{'code_sha':'a'*40}}
        pins = self.source_pins(code); original = m.runtime.file_hash; changed = []
        marker = base/'repinned-boot-executed'
        def alter_after_check(path):
            digest = original(path)
            if Path(path).name == 'workbench_operations_boot.py' and not changed:
                changed.append(True)
                Path(path).write_text('from pathlib import Path\nPath(%r).write_text("executed")\n' % str(marker))
            return digest
        with patch.object(m.recovery,'verify',return_value=value), \
             patch.object(m.runtime,'verify_environment',return_value={'base_executable':str(Path(sys.executable).resolve())}), \
             patch.object(m,'_code_sources',return_value=pins), patch.object(m.runtime,'file_hash',side_effect=alter_after_check):
            result = m.prepare(base/'operations',profile,ev.sha(b'{}'))
        argv = plistlib.loads((base/'operations/launchd.NOT_INSTALLED.plist').read_bytes())['ProgramArguments']
        completed = subprocess.run(argv,capture_output=True,env=m.runtime.clean_environment(base),timeout=15)
        self.assertFalse(marker.exists(),completed.stderr.decode())
        self.assertNotEqual(completed.returncode,0)

    def test_boot_refuses_changed_environment_before_project_import(self):
        m = self.module(); base = self.base; code = base/'code'; sources = code/'scripts/llm'
        sources.mkdir(parents=True)
        for name in self.source_pins(ROOT): shutil.copyfile(ROOT/name,code/name)
        marker = base/'project-imported-before-environment-check'
        helper = sources/'workbench_backup.py'
        helper.write_text('from pathlib import Path\nPath(%r).write_text("executed")\n' % str(marker) + helper.read_text())
        environment = base/'environment'; (environment/'venv/bin').mkdir(parents=True)
        (environment/'venv/bin/python3').write_bytes(b'not executed')
        runtime = {'files':{'venv/bin/python3':{'sha256':ev.sha(b'not executed')}}}
        raw = ev.canonical(runtime).encode(); (environment/'runtime.json').write_bytes(raw)
        capsule = base/'capsule'; capsule.mkdir(mode=0o700); profile = capsule/'profile.json'
        profile.write_text(ev.canonical({'environment_root':str(environment),'environment_hash':ev.sha(raw)}))
        value = {'root':str(capsule),'code_root':str(code),'environment_root':str(environment),
                 'environment_hash':ev.sha(raw),'code_identity':{'code_sha':'a'*40}}
        with patch.object(m.recovery,'verify',return_value=value), \
             patch.object(m.runtime,'verify_environment',return_value={'base_executable':str(Path(sys.executable).resolve())}), \
             patch.object(m,'_code_sources',return_value=self.source_pins(code)):
            m.prepare(base/'operations',profile,ev.sha(profile.read_bytes()))
        (environment/'runtime.json').write_text(ev.canonical({**runtime,'changed':True}))
        argv = plistlib.loads((base/'operations/launchd.NOT_INSTALLED.plist').read_bytes())['ProgramArguments']
        result = subprocess.run(argv,capture_output=True,env=m.runtime.clean_environment(base),timeout=15)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(marker.exists(),result.stderr.decode())

    def test_boot_checks_full_environment_before_entering_recovery(self):
        m = self.module(); base = self.base; code = base/'code'; sources = code/'scripts/llm'
        sources.mkdir(parents=True)
        for name in self.source_pins(ROOT): shutil.copyfile(ROOT/name,code/name)
        marker = base/'recovery-entered-before-environment-verification'
        (sources/'workbench_recovery.py').write_text(
            'from pathlib import Path\ndef verify(*args):\n    Path(%r).write_text("entered")\n    raise ValueError("RECOVERY_TEST_STOP")\n' % str(marker))
        environment = base/'environment'; (environment/'venv/bin').mkdir(parents=True)
        (environment/'venv/bin/python3').write_bytes(b'not executed')
        (code/'config').mkdir(); shutil.copyfile(ROOT/'config/shared-runtime.lock.json',code/'config/shared-runtime.lock.json')
        executable = str(Path(sys.executable).resolve())
        raw = ev.canonical({'schema':'ar.isolated-runtime.v1','lock_hash':ev.sealed(m.runtime.LOCK),
            'python_version':'3.12.14','base_executable':executable,'base_hash':m.runtime.file_hash(executable),
            'dependencies':m.runtime.LOCK['dependencies'],'files':m.runtime.inventory(environment),
            'scope':'ISOLATED_ONLY','production_authority':False}).encode()
        (environment/'runtime.json').write_bytes(raw)
        capsule = base/'capsule'; capsule.mkdir(mode=0o700); profile = capsule/'profile.json'
        profile.write_text(ev.canonical({'environment_root':str(environment),'environment_hash':ev.sha(raw)}))
        value = {'root':str(capsule),'code_root':str(code),'environment_root':str(environment),
                 'environment_hash':ev.sha(raw),'code_identity':{'code_sha':'a'*40}}
        with patch.object(m.recovery,'verify',return_value=value), \
             patch.object(m.runtime,'verify_environment',return_value={'base_executable':executable}), \
             patch.object(m,'_code_sources',return_value=self.source_pins(code)):
            m.prepare(base/'operations',profile,ev.sha(profile.read_bytes()))
        (environment/'unexpected-package.py').write_text('CHANGED = True\n')
        argv = plistlib.loads((base/'operations/launchd.NOT_INSTALLED.plist').read_bytes())['ProgramArguments']
        result = subprocess.run(argv,capture_output=True,env=m.runtime.clean_environment(base),timeout=15)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(marker.exists(),result.stderr.decode())

    def test_worker_hash_stream_does_not_relax_json_artifact_limit(self):
        import workbench_operations_boot as boot
        self.assertTrue(hasattr(boot,'file_digest'),'worker binaries need bounded streaming verification')
        path = self.base/'worker-binary'; raw = b'x'*(12*1024*1024+1); path.write_bytes(raw)
        self.assertEqual(boot.file_digest(path),ev.sha(raw))
        with self.assertRaisesRegex(ValueError,'OPERATIONS_BOOT_FILE'): boot.read(path)
        with path.open('wb') as stream: stream.truncate(128*1024*1024+1)
        original = boot.os.fdopen
        class NoRead:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self,*args): return self.stream.__exit__(*args)
            def fileno(self): return self.stream.fileno()
            def read(self,*args): raise AssertionError('initially oversized binary was read')
        with patch.object(boot.os,'fdopen',side_effect=lambda *a,**k:NoRead(original(*a,**k))):
            with self.assertRaisesRegex(ValueError,'OPERATIONS_BOOT_BINARY_LIMIT'): boot.file_digest(path)

    def test_missing_bound_journal_refuses_without_recreating_a_budget(self):
        m,result,_,_ = self.prepared(); root = self.base/'operations'
        (root/'operations.sqlite3').unlink()
        with self.assertRaisesRegex(ValueError,'OPERATIONS_JOURNAL_REQUIRED'):
            m.Journal(root,result['operations_hash'])
        self.assertFalse((root/'operations.sqlite3').exists())

    def test_empty_or_incomplete_journal_refuses_without_schema_repair(self):
        m,result,_,_ = self.prepared(); root = self.base/'operations'
        path = root/'operations.sqlite3'; path.write_bytes(b'')
        with self.assertRaisesRegex(ValueError,'OPERATIONS_JOURNAL_REQUIRED'):
            m.Journal(root,result['operations_hash'])
        self.assertEqual(path.read_bytes(),b'')
        with sqlite3.connect(path) as db: db.execute('CREATE TABLE partial(value TEXT)')
        with self.assertRaisesRegex(ValueError,'OPERATIONS_JOURNAL_SCHEMA'):
            m.Journal(root,result['operations_hash'])
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('partial',)])

    def test_streaming_binary_growth_stops_at_cap_plus_one_byte(self):
        import workbench_operations_boot as boot
        path = self.base/'growing'; path.write_bytes(b''); original = boot.os.fdopen
        counted = [0]; maximum = 128*1024*1024
        class GrowingStream:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self,*args): return self.stream.__exit__(*args)
            def fileno(self): return self.stream.fileno()
            def read(self,size):
                amount = min(size,maximum+1024*1024-counted[0])
                counted[0] += amount
                return b'x'*amount
        with patch.object(boot.os,'fdopen',side_effect=lambda *a,**k:GrowingStream(original(*a,**k))):
            with self.assertRaisesRegex(ValueError,'OPERATIONS_BOOT_BINARY_LIMIT'): boot.file_digest(path)
        self.assertLessEqual(counted[0],maximum+1)


if __name__ == '__main__': unittest.main()
