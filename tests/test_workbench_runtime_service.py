"""Isolated operator profile and ownership guards; no live service access."""
import copy
import os
import py_compile
import plistlib
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/llm'))
import workbench_evidence as ev


class RuntimeServiceTests(unittest.TestCase):
    def module(self):
        import workbench_runtime_service
        return workbench_runtime_service

    def fixture(self, base):
        m = self.module(); root = base / 'profile'; root.mkdir(mode=0o700)
        value = {'schema':'ar.isolated-service.v1','root':str(root), 'code_root':str(base / 'code'),
                 'environment_root':str(base / 'environment'),'environment_hash':'a'*64,
                 'code_identity':{'code_sha':'b'*40,'source_tree_hash':'c'*64}, 'assets':{'index.html':'d'*64},
                 'runtime_sources':{'x':'e'*64}, 'port':18341, 'origin':m.ORIGIN,
                 'owner':m.OWNER,'member':m.MEMBER,'max_restarts':2,'scope':'ISOLATED_ONLY',
                 'production_authority':False}
        (root/'allowlist.json').write_text(ev.canonical({'members':[m.MEMBER]}))
        (root/'allowlist.json').chmod(0o600)
        return root, value

    def test_external_profile_pin_and_resealed_fields(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root, value = self.fixture(Path(tmp).resolve()); raw = ev.canonical(value).encode()
            (root/'profile.json').write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'SERVICE_PIN'):
                m.verify_profile(root/'profile.json','0'*64)
            for key, bad in (('port',8775),('owner','junyan.liu789@gmail.com'),('max_restarts',99),
                             ('scope','PRODUCTION'),('command',['sh','-c','anything'])):
                altered = copy.deepcopy(value); altered[key] = bad
                with self.subTest(key=key), self.assertRaises(ValueError): m.validate_profile(altered, root)

    def test_new_private_disjoint_roots_and_no_production_flags(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root, value = self.fixture(Path(tmp).resolve())
            m.validate_profile(value, root)
            for key in ('code_root','environment_root'):
                bad = copy.deepcopy(value); bad[key] = str(root/'nested')
                with self.assertRaisesRegex(ValueError,'SERVICE_ROOT'): m.validate_profile(bad,root)
            argv = m.server_arguments(value)
            self.assertIn('--shared-workspace-v1',argv)
            self.assertFalse(set(argv)&{'--read-only-source-root','--read-only-auto-sync','--research-library-root'})
            self.assertIn(str(root/'state'),argv)
            root.chmod(0o777)
            with self.assertRaises(ValueError): m.validate_profile(value,root)

    def test_duplicate_supervisor_and_symlink_lock_refused(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            with m.exclusive_lock(root):
                with self.assertRaisesRegex(ValueError,'SERVICE_ALREADY_RUNNING'):
                    with m.exclusive_lock(root): pass
            (root/'supervisor.lock').unlink(); (root/'supervisor.lock').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):
                with m.exclusive_lock(root): pass

    def test_stop_signals_only_owned_child_and_waits(self):
        m = self.module(); child=Mock(); child.poll.return_value=None
        m.stop_owned(child)
        child.send_signal.assert_called_once_with(m.signal.SIGINT)
        child.wait.assert_called_once_with(timeout=135)
        child.kill.assert_not_called()
        child=Mock(); child.poll.return_value=0
        m.stop_owned(child); child.send_signal.assert_not_called()

    def test_restart_budget_and_clean_exit(self):
        m = self.module()
        self.assertTrue(m.should_restart(1,0,False))
        self.assertTrue(m.should_restart(-9,1,False))
        self.assertFalse(m.should_restart(1,2,False))
        self.assertFalse(m.should_restart(0,0,False))
        self.assertFalse(m.should_restart(1,0,True))

    def test_dirty_code_is_not_an_installed_version(self):
        m = self.module(); root=Path(__file__).resolve().parents[1]
        outputs=[str(root).encode(), b'b'*40, b' M source.py', b'b'*40]
        with patch.object(m.subprocess,'run',side_effect=[Mock(stdout=x) for x in outputs]), \
             patch.object(m.runtime,'file_hash',return_value='a'*64):
            with self.assertRaisesRegex(ValueError,'SERVICE_CODE_DIRTY'): m.code_identity(root)

    def test_asset_directory_alias_is_not_silently_skipped(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); assets=root/'tools/nonprod_workbench/dist'
            assets.mkdir(parents=True); (assets/'index.html').write_text('isolated fixture')
            m.asset_inventory(root)
            (assets/'alias').symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'SERVICE_ASSETS_SYMLINK'): m.asset_inventory(root)

    def test_profile_under_repository_is_refused_before_creation(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve(); (base/'.git').mkdir()
            with self.assertRaisesRegex(ValueError,'SERVICE_ROOT_INSIDE_REPOSITORY'):
                m.prepare_profile(base/'new-profile',base/'code',base/'environment','a'*64,18341)
            self.assertFalse((base/'new-profile').exists())

    def test_hidden_index_edits_cannot_claim_the_committed_sha(self):
        m=self.module()
        from workbench_shared_workspace import EXECUTION_FILES
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            def git(*args):
                return subprocess.check_output(['/usr/bin/git','-c','core.hooksPath=/dev/null','-c','user.name=Fixture',
                                                '-c','user.email=fixture@example.com','-C',str(root),*args],stderr=subprocess.DEVNULL)
            names=sorted(set((*EXECUTION_FILES,*m.RUNTIME_FILES)))
            for name in names:
                path=root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('VALUE = 1\n')
            git('init','-q'); git('add','--',*names); git('commit','-qm','Synthetic runtime identity')
            before=m.code_identity(root)
            name='scripts/llm/workbench_runtime.py'; git('update-index','--assume-unchanged',name)
            (root/name).write_text('VALUE = 2\n'); self.assertEqual(git('status','--porcelain'),b'')
            with self.assertRaisesRegex(ValueError,'SERVICE_SOURCE_NOT_COMMITTED'): m.code_identity(root)
            self.assertEqual(len(before['code_sha']),40)

    def test_operator_and_worker_bypass_ignored_bytecode(self):
        repo=Path(__file__).resolve().parents[1]
        for entry in ('workbench_runtime.py','workbench_shared_worker.py'):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); (root/entry).write_bytes((repo/'scripts/llm'/entry).read_bytes())
                if entry=='workbench_runtime.py':
                    name='workbench_runtime_service.py'
                    template="def verify_profile(*a): return {'code_identity':{'code_sha':'%s'}}\n"
                    (root/'workbench_runtime_env.py').write_text('')
                    args=['verify','--profile',str(root/'unused'),'--pin','a'*64]
                else:
                    name='workbench_evidence.py'; template="print('%s')\n"
                    (root/'workbench_snapshot_brief.py').write_text('')
                    (root/'workbench_backup.py').write_text('durable_directory = fsync_directory = write_new = None\n')
                    (root/'workbench_shared_inputs.py').write_text('validate_snapshot = None\n')
                    (root/'workbench_workspace.py').write_text('WorkspaceError = ValueError\n')
                    args=[]
                module=root/name; module.write_text(template%'cached'); os.utime(module,(1700000000,1700000000))
                cache=root/'__pycache__'/(module.stem+'.'+sys.implementation.cache_tag+'.pyc')
                py_compile.compile(str(module),cfile=str(cache),doraise=True,
                                   invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
                module.write_text(template%'source'); os.utime(module,(1700000000,1700000000))
                result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix=',str(root/entry),*args],capture_output=True,text=True)
                self.assertIn('source',result.stdout,result.stderr)
                self.assertNotIn('cached',result.stdout)

    def test_launch_template_uses_trusted_host_before_checking_venv(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve(); host=str(Path(sys.executable).resolve())
            with patch.object(m.runtime,'verify_environment',return_value={'base_executable':host}), \
                 patch.object(m,'code_identity',return_value={'code_sha':'b'*40,'source_tree_hash':'c'*64}), \
                 patch.object(m,'asset_inventory',return_value={'index.html':'d'*64}), \
                 patch.object(m,'runtime_inventory',return_value={'x':'e'*64}):
                m.prepare_profile(base/'profile',base/'code',base/'environment','a'*64,18341)
            command=plistlib.loads((base/'profile/launchd.NOT_INSTALLED.plist').read_bytes())['ProgramArguments']
            self.assertEqual(command[0],host)
            self.assertIn('-S',command)

    def test_operator_and_worker_refuse_sourceless_modules(self):
        repo=Path(__file__).resolve().parents[1]
        for entry in ('workbench_runtime.py','workbench_shared_worker.py'):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); (root/entry).write_bytes((repo/'scripts/llm'/entry).read_bytes())
                payload=root/'payload.py'; payload.write_text("print('UNPINNED_SOURCELESS_EXECUTED')\n")
                py_compile.compile(str(payload),cfile=str(root/'hashlib.pyc'),doraise=True)
                if entry=='workbench_runtime.py':
                    (root/'workbench_runtime_env.py').write_text('import hashlib\n')
                    (root/'workbench_runtime_service.py').write_text('')
                else:
                    (root/'workbench_evidence.py').write_text('import hashlib\n')
                result=subprocess.run([sys.executable,'-I','-B',str(root/entry),'--help'],capture_output=True,text=True)
                self.assertNotIn('UNPINNED_SOURCELESS_EXECUTED',result.stdout)
                self.assertIn('SOURCELESS_MODULE_REFUSED',result.stderr)
                self.assertNotEqual(result.returncode,0)

    def test_code_assets_and_environment_are_rechecked(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root, value=self.fixture(Path(tmp).resolve()); raw=ev.canonical(value).encode()
            (root/'profile.json').write_bytes(raw); pin=ev.sha(raw)
            with patch.object(m,'code_identity',return_value=value['code_identity']), \
                 patch.object(m,'asset_inventory',return_value=value['assets']), \
                 patch.object(m,'runtime_inventory',return_value=value['runtime_sources']), \
                 patch.object(m.runtime,'verify_environment') as check:
                self.assertEqual(m.verify_profile(root/'profile.json',pin),value)
                check.assert_called_once_with(Path(value['environment_root']),value['environment_hash'])
                with patch.object(m,'code_identity',return_value={'code_sha':'f'*40}):
                    with self.assertRaisesRegex(ValueError,'SERVICE_CODE'): m.verify_profile(root/'profile.json',pin)
                with patch.object(m,'asset_inventory',return_value={'index.html':'0'*64}):
                    with self.assertRaisesRegex(ValueError,'SERVICE_ASSETS'): m.verify_profile(root/'profile.json',pin)
                check.side_effect=ValueError('RUNTIME_FILES_CHANGED')
                with self.assertRaises(ValueError): m.verify_profile(root/'profile.json',pin)


if __name__=='__main__': unittest.main()
