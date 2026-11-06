"""Operator-only, pinned isolated service lifecycle. Never targets an existing PID."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import plistlib
import signal
import stat
import subprocess
import threading
import time
import uuid

import workbench_evidence as ev
from workbench_backup import write_new
import workbench_runtime_env as runtime

ORIGIN = 'https://runtime-isolated.fixture.ts.net:8443'
OWNER, MEMBER = 'owner@example.com', 'member@example.com'
RUNTIME_FILES = ('scripts/llm/workbench_runtime.py', 'scripts/llm/workbench_runtime_env.py',
                 'scripts/llm/workbench_runtime_service.py', 'scripts/llm/foundation_control.py',
                 'config/publication-authority.v1.json', 'config/shared-runtime.lock.json')
FIELDS = {'schema','root','code_root','environment_root','environment_hash','code_identity',
          'assets','runtime_sources','port','origin','owner','member','max_restarts','scope','production_authority'}


def code_identity(root):
    root = runtime.safe_path(root)
    def git(*args, raw=False, input_data=None):
        result = subprocess.run(['/usr/bin/git','-c','core.fsmonitor=false','-C',str(root),*args],
                                env={**runtime.clean_environment(root),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'},
                                input=input_data, capture_output=True, timeout=30, check=True)
        return result.stdout if raw else result.stdout.decode().strip()
    if Path(git('rev-parse','--show-toplevel')).resolve() != root: raise ValueError('SERVICE_CODE_ROOT')
    sha = git('rev-parse','HEAD')
    # governance-mutation: RUNTIME_SERVICE_CLEAN_CODE
    if git('status','--porcelain','--untracked-files=normal'): raise ValueError('SERVICE_CODE_DIRTY')
    # Read the HEAD tree, not the index's visibility flags or a hand-maintained
    # import list. Do not import application helpers before verifying their bytes.
    entries=[]
    for record in git('ls-tree','-r','-z',sha,raw=True).split(b'\0'):
        if not record: continue
        try:
            metadata,name=record.split(b'\t',1); mode,kind,oid=metadata.split(b' ')
            if mode not in {b'100644',b'100755'} or kind!=b'blob': raise ValueError
            entries.append((name.decode('utf-8'),oid))
        except (ValueError,UnicodeError): raise ValueError('SERVICE_TREE_ENTRY_INVALID') from None
    if not entries or len(entries)>10000: raise ValueError('SERVICE_TREE_SIZE_LIMIT')
    objects=git('cat-file','--batch',raw=True,input_data=b''.join(oid+b'\n' for _,oid in entries))
    if len(objects)>256*1024*1024: raise ValueError('SERVICE_TREE_SIZE_LIMIT')
    offset=0; expected={}; hashes={}
    for name,oid in entries:
        end=objects.find(b'\n',offset)
        header=objects[offset:end].split(b' ')
        if end<0 or len(header)!=3 or header[:2]!=[oid,b'blob'] or not header[2].isdigit():
            raise ValueError('SERVICE_GIT_OBJECT_INVALID')
        size=int(header[2]); start=end+1; offset=start+size+1
        if objects[start+size:offset]!=b'\n': raise ValueError('SERVICE_GIT_OBJECT_INVALID')
        expected[name]=ev.sha(objects[start:start+size]); hashes[name]=runtime.file_hash(root/name)
    if offset!=len(objects): raise ValueError('SERVICE_GIT_OBJECT_INVALID')
    # governance-mutation: RUNTIME_COMMITTED_BYTES
    if hashes!=expected:
        raise ValueError('SERVICE_SOURCE_NOT_COMMITTED')
    if git('rev-parse','HEAD') != sha: raise ValueError('SERVICE_CODE_CHANGED')
    return {'code_sha':sha,'source_tree_hash':ev.sealed(hashes)}


def runtime_inventory(root):
    return {name:runtime.file_hash(root/name) for name in RUNTIME_FILES}


def asset_inventory(root):
    directory = runtime.safe_path(root/'tools/nonprod_workbench/dist')
    paths = list(directory.rglob('*'))
    if len(paths)>1000 or not (directory/'index.html').is_file(): raise ValueError('SERVICE_ASSETS_MISSING')
    if any(p.is_symlink() for p in paths): raise ValueError('SERVICE_ASSETS_SYMLINK')
    return {p.relative_to(directory).as_posix():runtime.file_hash(p) for p in paths if not p.is_dir()}


def validate_profile(value, root):
    root = runtime.safe_path(root)
    if any((p/'.git').exists() for p in (root,*root.parents)):
        raise ValueError('SERVICE_ROOT_INSIDE_REPOSITORY')
    if (type(value) is not dict or set(value)!=FIELDS or value['schema']!='ar.isolated-service.v1'
            or value['root']!=str(root) or value['scope']!='ISOLATED_ONLY' or value['production_authority'] is not False
            or value['origin']!=ORIGIN or value['owner']!=OWNER or value['member']!=MEMBER
            or type(value['port']) is not int or not 18000<=value['port']<=18999
            or type(value['max_restarts']) is not int or value['max_restarts']!=2):
        raise ValueError('SERVICE_PROFILE_INVALID')
    info = root.stat()
    if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700: raise ValueError('SERVICE_ROOT_PERMISSIONS')
    paths = [root,runtime.safe_path(value['code_root']),runtime.safe_path(value['environment_root'])]
    if any(a==b or a in b.parents or b in a.parents for i,a in enumerate(paths) for b in paths[i+1:]):
        raise ValueError('SERVICE_ROOT_OVERLAP')
    return value


def verify_profile(path, expected_hash):
    path = runtime.safe_path(path)
    if path.name!='profile.json': raise ValueError('SERVICE_PROFILE_PATH')
    if type(expected_hash) is not str or not runtime.HEX.fullmatch(expected_hash): raise ValueError('SERVICE_PIN_INVALID')
    raw = ev.read_local(path.parent,path.name)
    # governance-mutation: RUNTIME_SERVICE_PIN
    if ev.sha(raw)!=expected_hash: raise ValueError('SERVICE_PIN_MISMATCH')
    value = validate_profile(ev.parse(raw),path.parent)
    code = Path(value['code_root'])
    runtime.verify_environment(Path(value['environment_root']),value['environment_hash'])
    if code_identity(code)!=value['code_identity'] or runtime_inventory(code)!=value['runtime_sources']:
        raise ValueError('SERVICE_CODE_CHANGED')
    # governance-mutation: RUNTIME_SERVICE_ASSETS
    if asset_inventory(code)!=value['assets']: raise ValueError('SERVICE_ASSETS_CHANGED')
    allowlist = path.parent/'allowlist.json'
    if stat.S_IMODE(allowlist.stat().st_mode)!=0o600 or ev.parse(ev.read_local(path.parent,'allowlist.json'))!={'members':[MEMBER]}:
        raise ValueError('SERVICE_ALLOWLIST_CHANGED')
    return value


def server_arguments(value):
    root = Path(value['root'])
    return ['--host','127.0.0.1','--port',str(value['port']),'--state-root',str(root/'state'),
            '--private-origin',ORIGIN,'--owner-login',OWNER,'--private-allowlist',str(root/'allowlist.json'),
            '--shared-workspace-v1']


def prepare_profile(root, code_root, environment_root, environment_hash, port):
    root = runtime.safe_path(root); code_root = runtime.safe_path(code_root)
    environment_root = runtime.safe_path(environment_root)
    if root.exists(): raise ValueError('SERVICE_NEW_ROOT_REQUIRED')
    if any((p/'.git').exists() for p in root.parents): raise ValueError('SERVICE_ROOT_INSIDE_REPOSITORY')
    if any(root==p or root in p.parents or p in root.parents for p in (code_root,environment_root)):
        raise ValueError('SERVICE_ROOT_OVERLAP')
    if type(port) is not int or not 18000<=port<=18999: raise ValueError('SERVICE_PORT_INVALID')
    environment_info=runtime.verify_environment(environment_root,environment_hash)
    identity=code_identity(code_root); assets=asset_inventory(code_root)
    root.mkdir(mode=0o700)
    value={'schema':'ar.isolated-service.v1','root':str(root),'code_root':str(code_root),
           'environment_root':str(environment_root),'environment_hash':environment_hash,'code_identity':identity,
           'assets':assets,'runtime_sources':runtime_inventory(code_root),'port':port,'origin':ORIGIN,
           'owner':OWNER,'member':MEMBER,'max_restarts':2,'scope':'ISOLATED_ONLY','production_authority':False}
    validate_profile(value,root)
    write_new(root/'allowlist.json',ev.canonical({'members':[MEMBER]}).encode())
    raw=ev.canonical(value).encode(); write_new(root/'profile.json',raw); pin=ev.sha(raw)
    # governance-mutation: RUNTIME_TRUSTED_BOOTSTRAP
    command=[environment_info['base_executable'],'-I','-B','-S',str(code_root/'scripts/llm/workbench_runtime.py'),
             'serve','--profile',str(root/'profile.json'),'--pin',pin,'--seconds','300']
    template={'Label':'com.ar.isolated-runtime.'+pin[:12],'ProgramArguments':command,'RunAtLoad':True,
              'WorkingDirectory':str(root),'EnvironmentVariables':runtime.clean_environment(root),
              'StandardOutPath':str(root/'launchd.stdout'),'StandardErrorPath':str(root/'launchd.stderr')}
    write_new(root/'launchd.NOT_INSTALLED.plist',plistlib.dumps(template))
    verify_profile(root/'profile.json',pin)
    return {'profile':str(root/'profile.json'),'profile_hash':pin,'code_sha':identity['code_sha'],
            'template_status':'GENERATED_NOT_INSTALLED','production_authority':False}


@contextmanager
def exclusive_lock(root):
    path=runtime.safe_path(Path(root)/'supervisor.lock')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('SERVICE_ALREADY_RUNNING') from None
        yield
    finally: os.close(fd)


def should_restart(exit_code, restarts, stopping):
    # governance-mutation: RUNTIME_SERVICE_RESTART_LIMIT
    return not stopping and exit_code!=0 and restarts<2


def stop_owned(child):
    if child is None or child.poll() is not None: return
    child.send_signal(signal.SIGINT)
    try: child.wait(timeout=135)
    except subprocess.TimeoutExpired:
        child.kill(); child.wait(timeout=10)


def serve_profile(path, pin, seconds=300):
    if type(seconds) is not int or not 1<=seconds<=300: raise ValueError('SERVICE_DURATION_INVALID')
    value=verify_profile(path,pin); root=Path(value['root'])
    stopping=threading.Event(); old={}
    child=None; restarts=0; deadline=time.monotonic()+seconds
    def record(kind, **data):
        events=root/'events'
        if events.exists() and len(list(events.iterdir()))>=256: raise ValueError('SERVICE_EVENT_LIMIT')
        body={'kind':kind,'profile_hash':pin,'time_ns':time.time_ns(),'scope':'ISOLATED_ONLY',**data}
        write_new(events/(str(time.time_ns())+'-'+uuid.uuid4().hex+'.json'),ev.canonical(body).encode())
    with exclusive_lock(root):
        for sig in (signal.SIGINT,signal.SIGTERM): old[sig]=signal.signal(sig,lambda *_:stopping.set())
        try:
            while not stopping.is_set() and time.monotonic()<deadline:
                value=verify_profile(path,pin)
                log=root/('child-'+uuid.uuid4().hex+'.log')
                argv=[str(Path(value['environment_root'])/'venv/bin/python3'),'-I','-B',
                      str(Path(value['code_root'])/'scripts/llm/workbench_runtime.py'),'child',
                      '--profile',str(path),'--pin',pin,'--parent',str(os.getpid())]
                with log.open('xb') as stream:
                    child=subprocess.Popen(argv,env=runtime.clean_environment(root),cwd=root,stdin=subprocess.DEVNULL,
                                           stdout=stream,stderr=subprocess.STDOUT,close_fds=True,start_new_session=True)
                    record('CHILD_STARTED',pid=child.pid,restart_number=restarts)
                    while child.poll() is None and not stopping.wait(.2) and time.monotonic()<deadline: pass
                    if child.poll() is None: stop_owned(child)
                code=child.wait(); record('CHILD_EXITED',pid=child.pid,exit_code=code,log_hash=runtime.file_hash(log))
                if not should_restart(code,restarts,stopping.is_set() or time.monotonic()>=deadline): break
                restarts+=1; stopping.wait(.5)
            record('SUPERVISOR_STOPPED',restarts=restarts,child_exit=child.returncode if child else None)
            return {'status':'FAILED' if child is not None and child.returncode not in (0,None) and not stopping.is_set() else 'STOPPED',
                    'unexpected_restarts':restarts,'child_exit':child.returncode if child else None,
                    'scope':'ISOLATED_ONLY','production_authority':False}
        finally:
            stop_owned(child)
            for sig, handler in old.items(): signal.signal(sig,handler)


def run_child(path, pin, parent):
    if type(parent) is not int or parent!=os.getppid(): raise ValueError('SERVICE_PARENT_INVALID')
    value=verify_profile(path,pin)
    import _thread
    def watch_parent():
        while os.getppid()==parent: time.sleep(.5)
        _thread.interrupt_main()
    threading.Thread(target=watch_parent,daemon=True).start()
    import nonprod_workbench
    return nonprod_workbench.main(server_arguments(value))
