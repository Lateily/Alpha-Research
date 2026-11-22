"""Stdlib-only pinned bootstrap. Capture sources before exposing project imports."""
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys


def read(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('OPERATIONS_BOOT_PATH')
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 12*1024*1024:
            raise ValueError('OPERATIONS_BOOT_FILE')
        raw = stream.read(12*1024*1024+1)
        identity = lambda s: (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode)
        if identity(before) != identity(os.fstat(stream.fileno())) or identity(before) != identity(path.lstat()):
            raise ValueError('OPERATIONS_BOOT_CHANGED')
        return raw


def file_digest(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('OPERATIONS_BOOT_PATH')
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        before = os.fstat(stream.fileno())
        # governance-mutation: OPERATIONS_BOOT_BINARY_LIMIT
        if not stat.S_ISREG(before.st_mode) or before.st_size > 128*1024*1024:
            raise ValueError('OPERATIONS_BOOT_BINARY_LIMIT')
        digest = hashlib.sha256(); total = 0
        while True:
            # governance-mutation: OPERATIONS_BOOT_GROWTH_BUDGET
            chunk = stream.read(min(1024*1024,128*1024*1024+1-total))
            if not chunk: break
            total += len(chunk)
            if total > 128*1024*1024: raise ValueError('OPERATIONS_BOOT_BINARY_LIMIT')
            digest.update(chunk)
        identity = lambda s: (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode)
        if identity(before) != identity(os.fstat(stream.fileno())) or identity(before) != identity(path.lstat()):
            raise ValueError('OPERATIONS_BOOT_CHANGED')
        return digest.hexdigest()


class BufferedLoader(importlib.abc.Loader):
    def __init__(self, origin, raw): self.origin,self.raw = origin,raw
    def create_module(self, spec): return None
    def exec_module(self, module):
        module.__file__ = self.origin
        exec(compile(self.raw,self.origin,'exec'),module.__dict__)


class SourceBarrier(importlib.abc.MetaPathFinder):
    def __init__(self, code, held): self.code,self.held = code,held
    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname,path)
        if spec is None: return None
        # governance-mutation: OPERATIONS_BOOT_SOURCELESS
        if isinstance(spec.loader,importlib.machinery.SourcelessFileLoader):
            raise ImportError('OPERATIONS_BOOT_SOURCELESS_REFUSED')
        if spec.origin is None: return None
        origin = Path(spec.origin)
        if self.code not in origin.parents: return None
        if str(origin) not in self.held: raise ImportError('OPERATIONS_BOOT_UNPINNED_IMPORT')
        result = importlib.util.spec_from_loader(fullname,BufferedLoader(str(origin),self.held[str(origin)]),
                                                 origin=str(origin),is_package=spec.submodule_search_locations is not None)
        if spec.submodule_search_locations is not None: result.submodule_search_locations = [str(origin.parent)]
        return result


def main():
    if not __debug__ or not sys.flags.isolated or not sys.flags.no_site:
        raise ValueError('OPERATIONS_BOOT_ISOLATION_REQUIRED')
    root,pin,*duration = sys.argv[1:]
    root = Path(root); raw = read(root/'operations.json')
    if not re.fullmatch(r'[0-9a-f]{64}',pin) or hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError('OPERATIONS_BOOT_PIN')
    value = json.loads(raw)
    if (value.get('schema') != 'ar.workbench-operations.v1' or value.get('root') != str(root)
            or value.get('scope') != 'ISOLATED_ONLY' or value.get('production_authority') is not False):
        raise ValueError('OPERATIONS_BOOT_SCOPE')
    code = Path(value['code_root']); sources = value['source_files']
    if type(sources) is not dict or not 1 <= len(sources) <= 10000:
        raise ValueError('OPERATIONS_BOOT_SOURCE_LIMIT')
    held = {}; total = 0
    for name,digest in sources.items():
        relative = Path(name)
        if relative.is_absolute() or relative.as_posix() != name or '..' in relative.parts or relative.suffix != '.py':
            raise ValueError('OPERATIONS_BOOT_SOURCE_PATH')
        data = read(code/relative); total += len(data)
        # governance-mutation: OPERATIONS_BOOT_SOURCE_PIN
        if hashlib.sha256(data).hexdigest() != digest: raise ValueError('OPERATIONS_BOOT_SOURCE_PIN')
        if total > 256*1024*1024: raise ValueError('OPERATIONS_BOOT_SOURCE_LIMIT')
        held[str(code/relative)] = data
    profile = Path(value['recovery_profile'])
    profile_raw = read(profile)
    if hashlib.sha256(profile_raw).hexdigest() != value['recovery_pin']:
        raise ValueError('OPERATIONS_BOOT_RECOVERY_PIN')
    retained = json.loads(profile_raw)
    environment = Path(retained['environment_root'])
    runtime_raw = read(environment/'runtime.json')
    # governance-mutation: OPERATIONS_BOOT_ENVIRONMENT_PIN
    if hashlib.sha256(runtime_raw).hexdigest() != retained['environment_hash']:
        raise ValueError('OPERATIONS_BOOT_ENVIRONMENT_PIN')
    runtime = json.loads(runtime_raw)
    worker = environment/'venv/bin/python3'
    if file_digest(worker) != runtime['files']['venv/bin/python3']['sha256']:
        raise ValueError('OPERATIONS_BOOT_WORKER_PIN')
    binding = json.loads(read(profile.parent/'operations-binding.json'))
    if binding != {'operations_root':str(root),'operations_hash':pin,'recovery_pin':value['recovery_pin']}:
        raise ValueError('OPERATIONS_BOOT_CAPSULE_BINDING')
    entry = str(code/'scripts/llm/workbench_operations.py')
    if entry not in held: raise ValueError('OPERATIONS_BOOT_ENTRY')
    sys.pycache_prefix = '/dev/null'; sys.dont_write_bytecode = True
    sys.meta_path.insert(0,SourceBarrier(code,held))
    sys.path.insert(0,str(code/'scripts/llm'))
    # Archive verification can already launch bounded PDF workers, so validate
    # the complete environment before entering recovery, not after its archive read.
    import workbench_runtime_env as verified_runtime
    verified_runtime.verify_environment(environment,retained['environment_hash'])
    sys.executable = str(worker)
    sys.argv = [entry,'serve','--root',str(root),'--pin',pin,*duration]
    exec(compile(held[entry],entry,'exec'),{'__name__':'__main__','__file__':entry})


if __name__ == '__main__': main()
