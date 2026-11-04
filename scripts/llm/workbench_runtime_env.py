"""New-root offline venv creation and externally pinned byte inventory."""
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import workbench_evidence as ev
from workbench_backup import write_new

LOCK = {'schema': 'ar.shared-runtime-lock.v1', 'python': '3.12',
        'dependencies': {'pypdf': '6.10.0'}, 'wheels': {
            'pip-25.0.1-py3-none-any.whl': 'c46efd13b6aa8279f33f2864459c8ce587ea6a1a59ee20de055868d8f7688f7f',
            'pypdf-6.10.0-py3-none-any.whl': '90005e959e1596c6e6c84c8b0ad383285b3e17011751cedd17f2ce8fcdfc86de'},
        'network': False, 'system_site_packages': False}
HEX = re.compile(r'[0-9a-f]{64}\Z')


def safe_path(path):
    path = Path(path).absolute()
    if '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('RUNTIME_SYMLINK')
    return path


def file_hash(path):
    path = safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode): raise ValueError('RUNTIME_FILE_TYPE')
        digest = hashlib.sha256()
        while data := stream.read(1024 * 1024): digest.update(data)
        def identity(info):
            return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_mode)
        # governance-mutation: RUNTIME_STABLE_HASH
        if identity(before)!=identity(os.fstat(stream.fileno())) or identity(before)!=identity(path.lstat()):
            raise ValueError('RUNTIME_FILE_CHANGED')
    return digest.hexdigest()


def validate_lock(value):
    if ev.canonical(value) != ev.canonical(LOCK): raise ValueError('RUNTIME_LOCK_INVALID')
    return value


def load_lock():
    root = Path(__file__).resolve().parents[2] / 'config'
    return validate_lock(ev.parse(ev.read_local(root, 'shared-runtime.lock.json')))


def inventory(root):
    root = safe_path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        # CPython venv on Linux creates exactly this internal directory alias.
        if path.is_symlink() and name == 'venv/lib64' and os.readlink(path) == 'lib':
            result[name] = {'alias': 'lib'}
        elif path.is_symlink(): raise ValueError('RUNTIME_SYMLINK')
        elif path.is_file():
            if name != 'runtime.json':
                result[name] = {'sha256': file_hash(path), 'mode': stat.S_IMODE(path.stat().st_mode)}
        elif not path.is_dir(): raise ValueError('RUNTIME_FILE_TYPE')
    return result


def verify_environment(root, expected_hash):
    root = safe_path(root)
    if type(expected_hash) is not str or not HEX.fullmatch(expected_hash): raise ValueError('RUNTIME_PIN_INVALID')
    try: raw = ev.read_local(root, 'runtime.json')
    except OSError: raise ValueError('RUNTIME_MANIFEST_MISSING') from None
    # governance-mutation: RUNTIME_ENV_PIN
    if ev.sha(raw) != expected_hash: raise ValueError('RUNTIME_PIN_MISMATCH')
    value = ev.parse(raw)
    fields = {'schema','lock_hash','python_version','base_executable','base_hash','dependencies','files','scope','production_authority'}
    if (set(value) != fields or value['schema'] != 'ar.isolated-runtime.v1'
            or value['lock_hash'] != ev.sealed(load_lock()) or not value['python_version'].startswith('3.12.')
            or value['dependencies'] != LOCK['dependencies'] or value['scope'] != 'ISOLATED_ONLY'
            or value['production_authority'] is not False): raise ValueError('RUNTIME_MANIFEST_INVALID')
    # governance-mutation: RUNTIME_ENV_FILES
    if inventory(root) != value['files']: raise ValueError('RUNTIME_FILES_CHANGED')
    if file_hash(Path(value['base_executable'])) != value['base_hash']: raise ValueError('RUNTIME_BASE_CHANGED')
    return value


def clean_environment(home):
    return {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'AR_OFFLINE': '1'}


def build_environment(destination, wheelhouse):
    destination = safe_path(destination); wheelhouse = safe_path(wheelhouse)
    if destination.exists(): raise ValueError('RUNTIME_NEW_ROOT_REQUIRED')
    if destination in wheelhouse.parents or wheelhouse in destination.parents or destination == wheelhouse:
        raise ValueError('RUNTIME_ROOT_OVERLAP')
    lock = load_lock()
    verified_wheels = {}
    for name, expected in lock['wheels'].items():
        try: raw = ev.read_local(wheelhouse, name)
        except (OSError, ValueError): raise ValueError('RUNTIME_WHEEL_MISSING') from None
        # governance-mutation: RUNTIME_WHEEL_PIN
        if ev.sha(raw) != expected: raise ValueError('RUNTIME_WHEEL_HASH')
        verified_wheels[name] = raw
    if sys.version_info[:2] != (3, 12): raise ValueError('RUNTIME_BUILD_REQUIRES_PYTHON_312')
    destination.mkdir(mode=0o700)
    write_new(destination / 'BUILD_STARTED', b'ISOLATED_ONLY\n')
    for name, raw in verified_wheels.items(): write_new(destination / 'wheels' / name, raw)
    wheelhouse = destination / 'wheels'
    env = clean_environment(destination)

    def run(argv, log):
        with (destination / log).open('xb') as stream:
            subprocess.run(argv, env=env, cwd=destination, stdout=stream, stderr=subprocess.STDOUT,
                           timeout=180, check=True)
        if (destination / log).stat().st_size > 1024 * 1024: raise ValueError('RUNTIME_LOG_LIMIT')

    run([sys.executable, '-I', '-B', '-m', 'venv', '--without-pip', '--copies', str(destination / 'venv')], 'venv.log')
    interpreter = destination / 'venv/bin/python3'
    requirement = 'pypdf==6.10.0 --hash=sha256:' + lock['wheels']['pypdf-6.10.0-py3-none-any.whl'] + '\n'
    write_new(destination / 'requirements.txt', requirement.encode())
    pip_wheel = wheelhouse / 'pip-25.0.1-py3-none-any.whl'
    bootstrap = 'import sys;sys.path.insert(0,sys.argv.pop(1));from pip._internal.cli.main import main;raise SystemExit(main())'
    run([str(interpreter), '-I', '-B', '-c', bootstrap, str(pip_wheel), '--isolated', '--disable-pip-version-check',
         '--no-cache-dir', 'install', '--no-index', '--no-deps', '--require-hashes', '--only-binary=:all:',
         '--no-compile', '--find-links', str(wheelhouse), '-r', str(destination / 'requirements.txt')], 'install.log')
    probe = subprocess.run([str(interpreter), '-I', '-B', '-c',
                            'import json,sys,pypdf;print(json.dumps({"python":sys.version.split()[0],"pypdf":pypdf.__version__}))'],
                           capture_output=True, env=env, cwd=destination, timeout=15, check=True)
    versions = ev.parse(probe.stdout)
    if versions != {'python':sys.version.split()[0], 'pypdf':'6.10.0'}: raise ValueError('RUNTIME_PROBE_FAILED')
    base = Path(sys.executable).resolve()
    value = {'schema': 'ar.isolated-runtime.v1', 'lock_hash': ev.sealed(lock), 'python_version': versions['python'],
             'base_executable': str(base), 'base_hash': file_hash(base), 'dependencies': lock['dependencies'],
             'files': inventory(destination), 'scope': 'ISOLATED_ONLY', 'production_authority': False}
    raw = ev.canonical(value).encode(); write_new(destination / 'runtime.json', raw)
    pin = ev.sha(raw)
    verify_environment(destination, pin)
    return {'runtime_hash': pin, 'root': str(destination), 'dependencies': lock['dependencies'],
            'host_stdlib_scope': 'HOST_PREREQUISITE_NOT_BUNDLED', 'production_authority': False}
