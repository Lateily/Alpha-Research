"""Pinned retained-state recovery; never touches the installed service."""
import copy
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import plistlib
import shutil
import sys
import subprocess
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/llm'))
import nonprod_workbench as wb
import workbench_backup as backup
import workbench_evidence as ev


class RecoveryTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('workbench_recovery'),
                             'pinned retained-state recovery is not implemented')
        import workbench_recovery
        return workbench_recovery

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        code=self.base/'code/scripts/llm'; code.mkdir(parents=True)
        (code/'workbench_recovery.py').write_bytes(Path(__file__).resolve().parents[1].joinpath(
            'scripts/llm/workbench_recovery.py').read_bytes() if importlib.util.find_spec('workbench_recovery') else b'')
        self.archive = self.base / 'archive'
        store = wb.Store(self.base / 'old-state', shared_v1=True)
        self.pin = backup.backup_shared(store, self.archive)['backup_hash']

    def prepare(self, **kwargs):
        m = self.module()
        with self.checks():
            return m.prepare(kwargs.pop('root',self.base/'capsule'), self.archive,
                             kwargs.pop('backup_hash',self.pin), self.base/'code',
                             self.base/'environment','a'*64,kwargs.pop('port',18341),**kwargs)

    @contextmanager
    def checks(self):
        m=self.module()
        with patch.object(m.service, 'code_identity', return_value={'code_sha':'b'*40,'source_tree_hash':'c'*64}), \
             patch.object(m.service, 'asset_inventory', return_value={'index.html':'d'*64}), \
             patch.object(m.service, 'runtime_inventory', return_value={'x':'e'*64}), \
             patch.object(m.runtime, 'verify_environment', return_value={'base_executable':str(Path(sys.executable).resolve())}):
            yield

    def test_restores_new_state_without_credentials_or_live_install(self):
        value = self.prepare(); root = Path(value['root'])
        self.assertEqual(value['status'],'ISOLATED_RECOVERY_PREPARED_NOT_STARTED')
        self.assertEqual(value['backup_hash'],self.pin)
        self.assertTrue((root/'state/shared-workbench.sqlite3').is_file())
        self.assertFalse((root/'state/allowlist.json').exists())
        profile = ev.parse((root/'profile.json').read_bytes())
        self.assertEqual(profile['scope'],'ISOLATED_ONLY')
        self.assertFalse(profile['production_authority'])
        self.assertEqual(profile['origin'],'https://runtime-isolated.fixture.ts.net:8443')
        self.assertEqual(profile['owner'],'owner@example.com')
        self.assertTrue((root/'launchd.NOT_INSTALLED.plist').is_file())
        argv=plistlib.loads((root/'launchd.NOT_INSTALLED.plist').read_bytes())['ProgramArguments']
        self.assertIn('-S',argv); self.assertIn('recovery-serve',argv)

    def test_wrong_external_backup_pin_refuses_before_destination_creation(self):
        with self.assertRaisesRegex(ValueError,'RECOVERY_BACKUP_PIN'):
            self.prepare(backup_hash='0'*64)
        self.assertFalse((self.base/'capsule').exists())

    def test_existing_and_overlapping_roots_are_not_overwritten(self):
        self.prepare()
        before=(self.base/'capsule/profile.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'RECOVERY_NEW_ROOT'):
            self.prepare()
        self.assertEqual((self.base/'capsule/profile.json').read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'RECOVERY_ROOT_OVERLAP'):
            self.prepare(root=self.archive/'nested')
        with self.assertRaisesRegex(ValueError,'RECOVERY_PORT'):
            self.prepare(root=self.base/'bad-port',port=8777)

    def test_source_inventory_is_pinned_and_symlinks_refused(self):
        source=self.base/'source'; source.mkdir(); (source/'payload.json').write_text('{}')
        self.prepare(source_root=source)
        profile=ev.parse((self.base/'capsule/profile.json').read_bytes())
        self.assertEqual(profile['resources']['source']['files']['payload.json'],ev.sha(b'{}'))
        (source/'alias').symlink_to(self.archive,target_is_directory=True)
        with self.assertRaises(ValueError): self.prepare(root=self.base/'other',source_root=source)
        self.assertFalse((self.base/'other').exists())

    def test_profile_external_pin_precedes_any_environment_execution(self):
        m=self.module(); self.prepare()
        with self.checks(), patch.object(m.runtime,'verify_environment') as checked:
            with self.assertRaisesRegex(ValueError,'RECOVERY_PROFILE_PIN'):
                m.verify(self.base/'capsule/profile.json','0'*64)
            checked.assert_not_called()

    def test_unknown_flags_real_identities_and_resealed_restore_are_refused(self):
        m=self.module(); self.prepare(); root=self.base/'capsule'
        original=ev.parse((root/'profile.json').read_bytes())
        for key,bad in [('command',['sh','-c','anything']),('owner','junyan.liu789@gmail.com'),
                        ('port',8777),('max_restarts',99),('scope','PRODUCTION')]:
            altered=copy.deepcopy(original); altered[key]=bad
            raw=ev.canonical(altered).encode(); (root/'profile.json').write_bytes(raw)
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.verify(root/'profile.json',ev.sha(raw))
        (root/'profile.json').write_bytes(ev.canonical(original).encode())
        (root/'restore.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'RECOVERY_RESTORE_CHANGED$'):
            m.verify(root/'profile.json',ev.sha(ev.canonical(original).encode()))

    def test_trusted_cli_exposes_recovery_without_loosening_old_commands(self):
        script=Path(__file__).resolve().parents[1]/'scripts/llm/workbench_runtime.py'
        result=subprocess.run([sys.executable,'-I','-B','-S',str(script),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('recovery-prepare',result.stdout)
        self.assertIn('recovery-serve',result.stdout)
        self.assertIn('prepare',result.stdout)

    def test_changed_frozen_source_is_refused_after_restore(self):
        m=self.module(); source=self.base/'source'; source.mkdir()
        (source/'payload.json').write_text('{}')
        prepared=self.prepare(source_root=source)
        with self.checks():
            value=m.verify(self.base/'capsule/profile.json',prepared['profile_hash'])
            self.assertIn('--read-only-auto-sync',m.arguments(value))
            self.assertIn('--shared-materials-v1',m.arguments(value))
            (source/'payload.json').write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'RECOVERY_RESOURCE_CHANGED'):
                m.verify(self.base/'capsule/profile.json',prepared['profile_hash'])

    def test_unknown_database_tables_and_corrupt_bytes_fail_closed(self):
        m=self.module(); prepared=self.prepare(); root=self.base/'capsule'
        database=root/'state/shared-workbench.sqlite3'
        with sqlite3.connect(database) as db: db.execute('CREATE TABLE unknown_side_channel (value TEXT)')
        with self.checks(), self.assertRaisesRegex(ValueError,'RECOVERY_DATABASE_TABLES'):
            m.verify(root/'profile.json',prepared['profile_hash'])
        database.write_bytes(b'not a database')
        with self.checks(), self.assertRaisesRegex(ValueError,'RECOVERY_DATABASE_INVALID'):
            m.verify(root/'profile.json',prepared['profile_hash'])

    def test_library_pair_and_resource_root_overlap_fail_before_creation(self):
        with self.assertRaisesRegex(ValueError,'RECOVERY_LIBRARY_PIN'):
            self.prepare(library_hash='a'*64)
        self.assertFalse((self.base/'capsule').exists())
        with self.assertRaisesRegex(ValueError,'RECOVERY_ROOT_OVERLAP'):
            self.prepare(source_root=self.base/'code')
        self.assertFalse((self.base/'capsule').exists())

    def test_legitimate_state_evolves_without_losing_restore_provenance(self):
        m=self.module(); prepared=self.prepare(); root=self.base/'capsule'
        with sqlite3.connect(root/'state/shared-workbench.sqlite3') as db:
            db.execute('INSERT INTO shared_workspaces VALUES (?,?)',('owner@example.com','11111111-1111-4111-8111-111111111111'))
        with self.checks():
            value=m.verify(root/'profile.json',prepared['profile_hash'])
        self.assertEqual(value['backup_hash'],self.pin)

    def test_duration_parent_and_duplicate_supervisor_boundaries(self):
        m=self.module(); prepared=self.prepare(); path=self.base/'capsule/profile.json'
        for seconds in (0,301,True):
            with self.assertRaisesRegex(ValueError,'RECOVERY_DURATION'):
                m.serve(path,prepared['profile_hash'],seconds)
        with self.assertRaisesRegex(ValueError,'RECOVERY_PARENT'):
            m.run_child(path,prepared['profile_hash'],0)
        with m.service.exclusive_lock(path.parent), self.checks():
            with self.assertRaisesRegex(ValueError,'SERVICE_ALREADY_RUNNING'):
                m.serve(path,prepared['profile_hash'],1)

    def test_restart_rechecks_code_assets_environment_and_allowlist(self):
        m=self.module(); prepared=self.prepare(); root=self.base/'capsule'
        with self.checks():
            with patch.object(m.service,'code_identity',return_value={'code_sha':'f'*40}):
                with self.assertRaisesRegex(ValueError,'RECOVERY_CODE_CHANGED'):
                    m.verify(root/'profile.json',prepared['profile_hash'])
            with patch.object(m.service,'asset_inventory',return_value={'index.html':'f'*64}):
                with self.assertRaisesRegex(ValueError,'RECOVERY_ASSETS_CHANGED'):
                    m.verify(root/'profile.json',prepared['profile_hash'])
            with patch.object(m.runtime,'verify_environment',side_effect=ValueError('RUNTIME_FILES_CHANGED')):
                with self.assertRaisesRegex(ValueError,'RUNTIME_FILES_CHANGED'):
                    m.verify(root/'profile.json',prepared['profile_hash'])
            (root/'allowlist.json').write_text('{"members":["another@example.com"]}')
            with self.assertRaisesRegex(ValueError,'RECOVERY_ALLOWLIST_CHANGED'):
                m.verify(root/'profile.json',prepared['profile_hash'])

    def test_original_pin_cannot_accept_replaced_empty_database_or_missing_migration(self):
        m=self.module(); prepared=self.prepare(); root=self.base/'capsule'
        empty=wb.Store(self.base/'empty-state',shared_v1=True)
        shutil.copyfile(empty.path,root/'state/shared-workbench.sqlite3')
        with self.checks(), self.assertRaisesRegex(ValueError,'RECOVERY_MIGRATION_BINDING'):
            m.verify(root/'profile.json',prepared['profile_hash'])

    def test_original_history_must_remain_even_if_migration_anchor_is_preserved(self):
        m=self.module()
        with sqlite3.connect(self.base/'old-state/shared-workbench.sqlite3') as db:
            db.execute('INSERT INTO shared_workspaces VALUES (?,?)',('original@example.com','11111111-1111-4111-8111-111111111111'))
        self.archive=self.base/'history-archive'
        self.pin=backup.backup_shared(wb.Store(self.base/'old-state',shared_v1=True),self.archive)['backup_hash']
        prepared=self.prepare(); root=self.base/'capsule'
        with sqlite3.connect(root/'state/shared-workbench.sqlite3') as db:
            db.execute('DROP TRIGGER shared_workspaces_delete')
            db.execute('DELETE FROM shared_workspaces')
        with self.checks(), self.assertRaisesRegex(ValueError,'RECOVERY_HISTORY_CHANGED'):
            m.verify(root/'profile.json',prepared['profile_hash'])

    def test_final_validation_failure_never_publishes_startable_profile(self):
        m=self.module(); count=[0]
        def environment(*args):
            count[0]+=1
            if count[0]==2: raise ValueError('INJECTED_FINAL_ENVIRONMENT_FAILURE')
            return {'base_executable':str(Path(sys.executable).resolve())}
        with self.checks(), patch.object(m.runtime,'verify_environment',side_effect=environment):
            with self.assertRaisesRegex(ValueError,'INJECTED_FINAL_ENVIRONMENT_FAILURE'):
                m.prepare(self.base/'capsule',self.archive,self.pin,self.base/'code',
                          self.base/'environment','a'*64,18341)
        root=self.base/'capsule'
        self.assertFalse((root/'profile.json').exists())
        self.assertFalse((root/'READY.json').exists())

    def test_completion_marker_is_required_and_exact(self):
        m=self.module(); prepared=self.prepare(); root=self.base/'capsule'
        marker=root/'READY.json'
        self.assertTrue(marker.is_file(),'accepted recovery needs a final commit marker')
        marker.write_text('{}')
        with self.checks(), self.assertRaisesRegex(ValueError,'RECOVERY_NOT_READY'):
            m.verify(root/'profile.json',prepared['profile_hash'])


if __name__ == '__main__': unittest.main()
