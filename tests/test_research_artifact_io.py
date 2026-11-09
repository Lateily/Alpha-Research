"""Both real CLI creators must keep their exclusively created output root pinned."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock
from contextlib import contextmanager

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO/'scripts/llm'), str(REPO), str(REPO/'tests')]

LAUNCHER = r'''
import importlib, json, os, sys
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0, str(Path.cwd()/'scripts/llm'))
module = importlib.import_module(sys.argv[1]); cfg=json.loads(sys.argv[2]); done=False
def fault():
    global done
    if not done:
        done=True; output=Path(cfg['output']); protected=Path(cfg['protected'])
        if cfg['kind'].startswith('parent'):
            output.parent.rename(cfg['aside'])
            if cfg['kind'].endswith('alias'):
                output.parent.symlink_to(protected, target_is_directory=True)
            else:
                output.parent.mkdir(); output.mkdir(); (output/'unrelated.txt').write_text('keep')
        else:
            output.rename(cfg['aside'])
            if cfg['kind'].endswith('alias'):
                output.symlink_to(protected, target_is_directory=True)
            else:
                output.mkdir(); (output/'unrelated.txt').write_text('keep')
        Path(cfg['signal']).write_text('injected after exclusive creation')
# The injection is after exclusive creation, independent of how files are written.
if hasattr(module, 'artifacts'):
    holder=module.artifacts; original=holder._new_output
    @contextmanager
    def created(output):
        with original(output) as fd:
            fault(); yield fd
    holder._new_output=created
else:
    holder=module.materials; original=holder._create_private_root
    def created(*args, **kwargs):
        result=original(*args, **kwargs); fault(); return result
    holder._create_private_root=created
sys.argv=['creator', *sys.argv[3:]]
module.main()
'''

EARLY_LAUNCHER = r'''
import importlib, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()/'scripts/llm'))
module=importlib.import_module(sys.argv[1]); cfg=json.loads(sys.argv[2])
output=Path(cfg['output']); victim=Path(cfg['victim']); done=False
def fault():
    global done
    if not done:
        done=True; output.rename(cfg['aside']); victim.rename(output)
        Path(cfg['signal']).write_text('public root replaced before payload writes')
if cfg['point']=='first-open':
    original=os.open
    def acquire(path, flags, *args, **kwargs):
        if path==output.name and flags & os.O_DIRECTORY and kwargs.get('dir_fd') is not None and output.exists():
            fault()
        return original(path,flags,*args,**kwargs)
    os.open=acquire
elif hasattr(module.artifacts, '_rename_exclusive'):
    original=module.artifacts._rename_exclusive
    def provision(*args, **kwargs):
        result=original(*args,**kwargs); fault(); return result
    module.artifacts._rename_exclusive=provision
else:
    original=os.mkdir
    def provision(path, *args, **kwargs):
        result=original(path,*args,**kwargs)
        if path==output.name and kwargs.get('dir_fd') is not None: fault()
        return result
    os.mkdir=provision
sys.argv=['creator',*sys.argv[3:]]
module.main()
'''


class ArtifactPublicationTests(unittest.TestCase):
    def fixture(self, kind):
        if kind == 'normalization':
            from test_research_normalization import NormalizationArtifactTests
            f=NormalizationArtifactTests(); f.setUp(); self.addCleanup(f.doCleanups)
            worksheet=f.root/'worksheet.json'; worksheet.write_bytes(f.raw)
            module=importlib.import_module('research_normalization')
            arguments=['create','--content-root',str(f.content_root),'--content-hash',f.receipt['content_hash'],
                       '--pack-root',str(f.root/'pack'),'--pack-hash',f.f.pack['pack_hash'],
                       '--worksheet',str(worksheet),'--worksheet-hash',f.pin]
            return f, module, arguments, f.root/'pack', 'normalization-manifest.json'
        from test_daily_strategy import DailyStrategyTests
        import test_technical_contract as inputs
        f=DailyStrategyTests(); f.setUp(); self.addCleanup(f.doCleanups)
        module=f.module(); f.root=f.f.root
        arguments=['create','--registry',str(f.f.registry),'--registry-hash',inputs.sha(f.f.registry.read_bytes()),'--pack-id','synthetic-1']
        return f, module, arguments, f.f.pack, 'strategy-manifest.json'

    def snapshot(self, root):
        return {str(path.relative_to(root)):path.read_bytes() for path in root.rglob('*') if path.is_file()}

    def race(self, kind):
        import scripts.governance_mutation_gate as gate
        for mode in ('leaf-directory','leaf-alias','parent-directory','parent-alias'):
            with self.subTest(mode=mode):
                f,module,args,protected,marker=self.fixture(kind)
                parent=f.root/'outputs'; parent.mkdir(); output=parent/'artifact'
                before=self.snapshot(protected)
                cfg={'kind':mode,'output':str(output),'protected':str(protected),
                     'aside':str(f.root/'created-root-aside'),'signal':str(f.root/'fault-was-applied')}
                guard=f.root/'child-guard'; gate._write_network_guard(guard)
                child=subprocess.run([sys.executable,'-B','-c',LAUNCHER,module.__name__,json.dumps(cfg),
                                      *args,'--output',str(output)], cwd=REPO,env=gate._subprocess_env(REPO,guard),capture_output=True,timeout=40)
                self.assertTrue(Path(cfg['signal']).exists(), child.stderr.decode())
                self.assertNotEqual(child.returncode,0,'Creator accepted a substituted pre-existing directory')
                self.assertIn('OUTPUT_CHANGED',child.stderr.decode())
                self.assertFalse((output/marker).exists())
                self.assertEqual(self.snapshot(protected),before)
                if mode.endswith('directory'):
                    self.assertEqual(self.snapshot(output),{'unrelated.txt':b'keep'})

    def test_normalization_cli_root_and_parent_substitution_never_write_source(self):
        self.race('normalization')

    def test_daily_cli_root_and_parent_substitution_never_write_source(self):
        self.race('daily')

    def test_cli_initial_public_root_substitution_preserves_both_directories(self):
        import scripts.governance_mutation_gate as gate
        for kind in ('normalization','daily'):
            for point in ('first-open','creation-return'):
                with self.subTest(kind=kind,point=point):
                    f,module,args,_protected,marker=self.fixture(kind)
                    output=f.root/'artifact'; victim=f.root/'empty-existing'; victim.mkdir(mode=0o700)
                    cfg={'point':point,'output':str(output),'victim':str(victim),
                         'aside':str(f.root/'our-created-root'),'signal':str(f.root/'fault-applied')}
                    guard=f.root/'child-guard'; gate._write_network_guard(guard)
                    child=subprocess.run([sys.executable,'-B','-c',EARLY_LAUNCHER,module.__name__,json.dumps(cfg),
                                          *args,'--output',str(output)],cwd=REPO,
                                         env=gate._subprocess_env(REPO,guard),capture_output=True,timeout=40)
                    self.assertTrue(Path(cfg['signal']).exists(),child.stderr.decode())
                    self.assertNotEqual(child.returncode,0,'Creator adopted an existing empty directory')
                    self.assertIn('OUTPUT_CHANGED',child.stderr.decode())
                    self.assertEqual(self.snapshot(output),{})
                    self.assertEqual(self.snapshot(Path(cfg['aside'])),{})
                    self.assertFalse((output/marker).exists())

    def test_initial_public_root_substitution_is_rejected_before_any_payload_write(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve(); output=parent/'output'; victim=parent/'pre-existing'
            victim.mkdir(mode=0o700); original=io.os.open; fired=False
            def acquire(path,flags,*args,**kwargs):
                nonlocal fired
                if not fired and path==output.name and flags & io.os.O_DIRECTORY and kwargs.get('dir_fd') is not None:
                    fired=True; output.rename(parent/'ours'); victim.rename(output)
                return original(path,flags,*args,**kwargs)
            with mock.patch.object(io.os,'open',side_effect=acquire):
                with self.assertRaisesRegex(ValueError,'OUTPUT_CHANGED'):
                    io.publish(output,{'card.json':b'draft'},'commit.json',b'marker',lambda: {})
            self.assertTrue(fired)
            self.assertEqual(self.snapshot(output),{})
            self.assertEqual(self.snapshot(parent/'ours'),{})

    def test_fd_writer_never_writes_a_substituted_root(self):
        import tempfile
        import research_artifact_io as io
        for mode in ('directory','alias'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                parent=Path(tmp).resolve(); output=parent/'output'; protected=parent/'protected'; protected.mkdir()
                (protected/'sentinel.txt').write_bytes(b'original source')
                original=io._new_output
                @contextmanager
                def substituted(root):
                    with original(root) as fd:
                        root.rename(parent/'our-created-root')
                        if mode=='alias': root.symlink_to(protected,target_is_directory=True)
                        else: root.mkdir(); (root/'unrelated.txt').write_bytes(b'keep')
                        yield fd
                with mock.patch.object(io,'_new_output',substituted):
                    with self.assertRaisesRegex(ValueError,'OUTPUT_CHANGED'):
                        io.publish(output,{'card.json':b'draft'},'commit.json',b'marker',lambda: {})
                self.assertEqual(self.snapshot(protected),{'sentinel.txt':b'original source'})
                if mode=='directory': self.assertEqual(self.snapshot(output),{'unrelated.txt':b'keep'})
                self.assertEqual(self.snapshot(parent/'our-created-root'),{})

    def test_exclusive_root_collision_preserves_existing_empty_directory(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()/'output'; root.mkdir(mode=0o700)
            before=root.stat()
            with self.assertRaisesRegex(ValueError,'OUTPUT_EXISTS'):
                io.publish(root,{'card.json':b'draft'},'commit.json',b'marker',lambda: {})
            self.assertEqual(root.stat().st_ino,before.st_ino)
            self.assertEqual(self.snapshot(root),{})

    def test_untrusted_provisioning_ancestry_is_rejected(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve(); unsafe=parent/'unsafe'; unsafe.mkdir(); unsafe.chmod(0o777)
            with mock.patch.object(io,'PROVISION_BASE',unsafe):
                with self.assertRaisesRegex(ValueError,'PROVISION_UNTRUSTED'):
                    io.publish(parent/'output',{'card.json':b'draft'},'commit.json',b'marker',lambda: {})
            self.assertEqual(self.snapshot(parent),{})

    def test_provisioning_parent_substitution_cannot_publish(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve(); trusted=parent/'trusted'; trusted.mkdir(mode=0o700)
            original=io.os.mkdir; injected=False
            def moved(path,*args,**kwargs):
                nonlocal injected
                result=original(path,*args,**kwargs)
                if str(path).startswith('.ar-research-') and not injected:
                    injected=True; trusted.rename(parent/'original-trusted'); trusted.mkdir(mode=0o700)
                return result
            with mock.patch.object(io,'PROVISION_BASE',trusted), mock.patch.object(io.os,'mkdir',side_effect=moved):
                with self.assertRaisesRegex(ValueError,'OUTPUT_CHANGED'):
                    io.publish(parent/'output',{'card.json':b'draft'},'commit.json',b'marker',lambda: {})
            self.assertTrue(injected)
            self.assertFalse((parent/'output').exists())
            self.assertEqual(self.snapshot(parent),{})

    def test_native_exclusive_publication_fails_closed(self):
        import errno
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve()
            for failure in (OSError(errno.EXDEV,'different device'),ValueError('PROVISION_UNSUPPORTED')):
                with self.subTest(failure=str(failure)), mock.patch.object(io,'_rename_exclusive',side_effect=failure):
                    with self.assertRaisesRegex(ValueError,'PROVISION_|UNSAFE_PATH'):
                        io.publish(parent/'output',{'card.json':b'draft'},'commit.json',b'marker',lambda: {})
                    self.assertFalse((parent/'output').exists())
            with mock.patch.object(io.ctypes,'CDLL',return_value=object()):
                with self.assertRaisesRegex(ValueError,'PROVISION_UNSUPPORTED'):
                    io._rename_exclusive(0,'stage',0,'output')

    def test_linux_acl_grants_and_unknown_platform_are_refused(self):
        import research_artifact_io as io
        with mock.patch.object(io.sys,'platform','linux'), mock.patch.object(io.os,'listxattr',return_value=['system.posix_acl_access'],create=True):
            with self.assertRaisesRegex(ValueError,'PROVISION_UNTRUSTED'): io._no_acl(0)
        with mock.patch.object(io.sys,'platform','unsupported'):
            with self.assertRaisesRegex(ValueError,'PROVISION_UNSUPPORTED'): io._no_acl(0)

    @unittest.skipUnless(sys.platform=='darwin','actual macOS ACL refusal')
    def test_macos_acl_provisioning_directory_is_refused(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp).resolve(); trusted=parent/'with-acl'; trusted.mkdir(mode=0o700)
            subprocess.run(['/bin/chmod','+a','everyone allow write',str(trusted)],check=True,capture_output=True)
            with mock.patch.object(io,'PROVISION_BASE',trusted):
                with self.assertRaisesRegex(ValueError,'PROVISION_UNTRUSTED'):
                    io.publish(parent/'output',{'card.json':b'draft'},'commit.json',b'marker',lambda: {})
            self.assertFalse((parent/'output').exists())
            self.assertEqual(self.snapshot(parent),{})

    def test_native_rename_uses_platform_exclusive_flags(self):
        import research_artifact_io as io
        for platform,name,flag in (('darwin','renameatx_np',4),('linux','renameat2',1)):
            with self.subTest(platform=platform):
                operation=mock.Mock(return_value=0); library=mock.Mock(spec=[name])
                setattr(library,name,operation)
                with mock.patch.object(io.sys,'platform',platform), mock.patch.object(io.ctypes,'CDLL',return_value=library):
                    io._rename_exclusive(1,'stage',2,'output')
                operation.assert_called_once_with(1,b'stage',2,b'output',flag)

    def test_failed_postpublication_check_retracts_only_new_commit(self):
        for kind in ('normalization','daily'):
            with self.subTest(kind=kind):
                f,module,_args,_protected,marker=self.fixture(kind)
                output=f.root/'artifact'; original=module.verify
                def corrupt(*args, **kwargs):
                    result=original(*args,**kwargs)
                    (output/'unexpected.txt').write_text('retain failed evidence')
                    return result
                with mock.patch.object(module,'verify',side_effect=corrupt), mock.patch.object(
                        module,'_execution_identity',return_value={'code_sha':'a'*40,'source_tree_hash':'b'*64}):
                    with self.assertRaises(ValueError):
                        if kind=='normalization': module.create(f.raw,f.pin,*f.args(),output)
                        else: module.create(f.f.registry, __import__('test_technical_contract').sha(f.f.registry.read_bytes()),'synthetic-1',output)
                self.assertTrue((output/'unexpected.txt').exists())
                self.assertFalse((output/marker).exists())
                self.assertGreater(len(list(output.iterdir())),1)

    def test_read_holds_root_and_payload_fingerprints_across_derivation(self):
        import tempfile
        import research_artifact_io as io
        for mode in ('payload','root'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                parent=Path(tmp).resolve(); root=parent/'output'; root.mkdir()
                (root/'card.json').write_bytes(b'original')
                with self.assertRaisesRegex(ValueError,'OUTPUT_CHANGED'):
                    with io.read(root, {'card.json'}) as saved:
                        self.assertEqual(saved['card.json'],b'original')
                        if mode=='payload': (root/'card.json').write_bytes(b'modified')
                        else:
                            root.rename(parent/'aside'); root.mkdir()
                            (root/'card.json').write_bytes(b'original')

    def test_exclusive_commit_never_overwrites_an_injected_marker(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()/'output'; original=io.os.link
            def inject(source, target, *args, **kwargs):
                (root/target).write_bytes(b'foreign-marker')
                return original(source,target,*args,**kwargs)
            with mock.patch.object(io.os,'link',side_effect=inject):
                with self.assertRaises(ValueError): io.publish(root,{'card.json':b'draft'},'commit.json',b'new-marker',lambda: {})
            self.assertEqual((root/'commit.json').read_bytes(),b'foreign-marker')
            self.assertEqual((root/'card.json').read_bytes(),b'draft')

    def test_rollback_does_not_unlink_a_foreign_replacement_marker(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()/'output'
            def replaced():
                (root/'commit.json').rename(root/'our-marker-aside')
                (root/'commit.json').write_bytes(b'foreign-marker')
                return {}
            with self.assertRaises(ValueError): io.publish(root,{'card.json':b'draft'},'commit.json',b'new-marker',replaced)
            self.assertEqual((root/'commit.json').read_bytes(),b'foreign-marker')
            self.assertEqual((root/'our-marker-aside').read_bytes(),b'new-marker')

    def test_read_enforces_the_existing_file_cap_before_returning_bytes(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); target=root/'card.json'
            with mock.patch.object(io.ev,'MAX_FILE',8):
                target.write_bytes(b'12345678')
                with io.read(root,{'card.json'}) as saved:
                    self.assertEqual(saved['card.json'],b'12345678')
                target.write_bytes(b'123456789')
                with mock.patch.object(io.os,'read',wraps=io.os.read) as reader:
                    with self.assertRaisesRegex(ValueError,'OUTPUT_SIZE'):
                        with io.read(root,{'card.json'}): pass
                    self.assertEqual(reader.call_count,0)

    def test_read_growth_stops_at_the_same_limit(self):
        import tempfile
        import research_artifact_io as io
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); target=root/'card.json'; target.write_bytes(b'12345678')
            original=io.os.read; requests=[]
            def grows(fd, count):
                requests.append(count)
                if len(requests)==1: target.write_bytes(b'123456789')
                return original(fd,count)
            with mock.patch.object(io.ev,'MAX_FILE',8), mock.patch.object(io.os,'read',side_effect=grows):
                with self.assertRaisesRegex(ValueError,'OUTPUT_SIZE'):
                    with io.read(root,{'card.json'}): pass
            self.assertTrue(requests)
            self.assertLessEqual(max(requests),9)


if __name__=='__main__':
    unittest.main()
