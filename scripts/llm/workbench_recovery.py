"""Pinned retained-state recovery rehearsal; no installation or live takeover."""
from pathlib import Path
from contextlib import closing
import os
import plistlib
import signal
import sqlite3
import subprocess
import threading
import time
import uuid

import workbench_backup as backup
import workbench_evidence as ev
import workbench_runtime_env as runtime
import workbench_runtime_service as service

SCHEMA = 'ar.isolated-recovery.v1'
SCHEMA_V2 = 'ar.isolated-recovery.v2'
SCHEMA_V3 = 'ar.isolated-recovery.v3'
EXTRA = {'backup_root','backup_hash','restore_hash','migration_hash','resources'}


def _archive(root, pin):
    if type(pin) is not str or not runtime.HEX.fullmatch(pin):
        raise ValueError('RECOVERY_BACKUP_PIN_INVALID')
    manifest, data = backup.read_shared(runtime.safe_path(root))
    # governance-mutation: RECOVERY_BACKUP_PIN
    if manifest.get('backup_hash') != pin:
        raise ValueError('RECOVERY_BACKUP_PIN_MISMATCH')
    return manifest, data


def _resource(root):
    if root is None:
        return None
    root = runtime.safe_path(root)
    if not root.is_dir(): raise ValueError('RECOVERY_RESOURCE_MISSING')
    files = {}; total = 0
    paths=[]
    for path in root.rglob('*'):
        paths.append(path)
        if len(paths)>2048: raise ValueError('RECOVERY_RESOURCE_LIMIT')
    for path in sorted(paths):
        runtime.safe_path(path)
        if path.is_dir(): continue
        if not path.is_file(): raise ValueError('RECOVERY_RESOURCE_TYPE')
        raw = ev.read_local(root,path.relative_to(root).as_posix())
        total += len(raw)
        if total>128*1024*1024: raise ValueError('RECOVERY_RESOURCE_LIMIT')
        files[path.relative_to(root).as_posix()] = ev.sha(raw)
    return {'root':str(root),'files':files}


def _roots(root, code, environment, archive, resources):
    paths = [runtime.safe_path(p) for p in (root,code,environment,archive)]
    paths += [runtime.safe_path(v['root']) for v in resources.values() if v is not None]
    if any(a==b or a in b.parents or b in a.parents for i,a in enumerate(paths) for b in paths[i+1:]):
        raise ValueError('RECOVERY_ROOT_OVERLAP')
    if any((p/'.git').exists() for p in (root,*root.parents)):
        raise ValueError('RECOVERY_ROOT_INSIDE_REPOSITORY')


def _runtime_sources(code):
    return {**service.runtime_inventory(code),
            'scripts/llm/workbench_recovery.py':runtime.file_hash(code/'scripts/llm/workbench_recovery.py')}


def _validate(value, root):
    v2=type(value) is dict and value.get('schema')==SCHEMA_V2
    v3=type(value) is dict and value.get('schema')==SCHEMA_V3
    if (type(value) is not dict or set(value)!=service.FIELDS|EXTRA|({'features'} if v2 or v3 else set()) or value.get('schema') not in {SCHEMA,SCHEMA_V2,SCHEMA_V3}
            or type(value.get('resources')) is not dict or set(value['resources'])!={'source','library','library_hash'}):
        raise ValueError('RECOVERY_PROFILE_INVALID')
    if v2 and (type(value['features']) is not dict or set(value['features'])!={'research_cards_enabled'}
            or type(value['features']['research_cards_enabled']) is not bool):
        raise ValueError('RECOVERY_FEATURES_INVALID')
    if v3 and (type(value['features']) is not dict or set(value['features'])!={'research_cards_enabled','human_review_enabled'}
            or any(type(flag) is not bool for flag in value['features'].values())):
        raise ValueError('RECOVERY_FEATURES_INVALID')
    core = {k:v for k,v in value.items() if k in service.FIELDS}
    core['schema']='ar.isolated-service.v1'
    service.validate_profile(core,root)
    resources=value['resources']
    for name in ('source','library'):
        item=resources[name]
        if item is not None and (type(item) is not dict or set(item)!={'root','files'}
                                 or type(item['root']) is not str or type(item['files']) is not dict):
            raise ValueError('RECOVERY_RESOURCE_INVALID')
    if (resources['library'] is None)!=(resources['library_hash'] is None):
        raise ValueError('RECOVERY_LIBRARY_PIN_REQUIRED')
    if resources['library_hash'] is not None and (type(resources['library_hash']) is not str
                                                 or not runtime.HEX.fullmatch(resources['library_hash'])):
        raise ValueError('RECOVERY_LIBRARY_PIN_REQUIRED')
    for key in ('backup_hash','restore_hash','migration_hash'):
        if type(value[key]) is not str or not runtime.HEX.fullmatch(value[key]):
            raise ValueError('RECOVERY_PROFILE_INVALID')
    _roots(root,Path(value['code_root']),Path(value['environment_root']),Path(value['backup_root']),
           {k:resources[k] for k in ('source','library')})


def _check_resources(resources):
    if ((resources['library'] is None)!=(resources['library_hash'] is None)
            or resources['library_hash'] is not None and (type(resources['library_hash']) is not str
                or not runtime.HEX.fullmatch(resources['library_hash']))):
        raise ValueError('RECOVERY_LIBRARY_PIN_REQUIRED')
    for name in ('source','library'):
        item=resources[name]
        # governance-mutation: RECOVERY_RESOURCE_PIN
        if item is not None and _resource(item['root'])!=item:
            raise ValueError('RECOVERY_RESOURCE_CHANGED')
    if resources['library'] is not None:
        from workbench_research_library import ResearchLibrary
        ResearchLibrary(Path(resources['library']['root']),resources['library_hash']).read()


def verify(path, pin):
    path=runtime.safe_path(path)
    if path.name!='profile.json': raise ValueError('RECOVERY_PROFILE_PATH')
    raw=ev.read_local(path.parent,path.name)
    # governance-mutation: RECOVERY_PROFILE_PIN
    if type(pin) is not str or not runtime.HEX.fullmatch(pin) or ev.sha(raw)!=pin:
        raise ValueError('RECOVERY_PROFILE_PIN_MISMATCH')
    value=ev.parse(raw); root=path.parent
    _validate(value,root)
    try: marker=ev.parse(ev.read_local(root,'READY.json'))
    except (ValueError,OSError): raise ValueError('RECOVERY_NOT_READY') from None
    # governance-mutation: RECOVERY_READY_PIN
    if ev.canonical(marker)!=ev.canonical(_completion(value,pin)):
        raise ValueError('RECOVERY_NOT_READY')
    return _verify_value(value,root)


def _completion(value,pin):
    return {'schema':'ar.isolated-recovery-ready.v1','profile_hash':pin,
            'backup_hash':value['backup_hash'],'restore_hash':value['restore_hash'],'production_authority':False}


def _source_history(tables, original):
    for name, rows in original.items():
        current=tables[name]
        if name not in {'shared_jobs','shared_attempts'}:
            # governance-mutation: RECOVERY_HISTORY_PREFIX
            if current[:len(rows)]!=rows:
                raise ValueError('RECOVERY_HISTORY_CHANGED')
            continue
        indexed={row[0]:row for row in current}
        for row in rows:
            actual=indexed.get(row[0])
            if actual is None or actual[:-1]!=row[:-1]: raise ValueError('RECOVERY_HISTORY_CHANGED')
            before,after=ev.parse(row[-1]),ev.parse(actual[-1])
            if name=='shared_attempts' and before['status']=='RUNNING':
                if {k:v for k,v in before.items() if k!='status'}!={k:v for k,v in after.items() if k!='status'}:
                    raise ValueError('RECOVERY_HISTORY_CHANGED')
            elif name=='shared_jobs' and before['status'] in {'QUEUED','RUNNING'}:
                from workbench_shared_worker import BINDING_FIELDS
                if any(before[k]!=after.get(k) for k in (*BINDING_FIELDS,'command_id','submitted_at')):
                    raise ValueError('RECOVERY_HISTORY_CHANGED')
            elif actual!=row:
                raise ValueError('RECOVERY_HISTORY_CHANGED')


def _verify_value(value, root):
    _validate(value,root)
    restore=ev.read_local(root,'restore.json')
    migration=ev.read_local(root/'state','migration-receipt.json')
    # governance-mutation: RECOVERY_RESTORE_PIN
    if ev.sha(restore)!=value['restore_hash'] or ev.sha(migration)!=value['migration_hash']:
        raise ValueError('RECOVERY_RESTORE_CHANGED')
    receipt=ev.parse(restore)
    if receipt.get('backup_hash')!=value['backup_hash'] or receipt.get('status')!='LOCAL_SHARED_RESTORE_VERIFIED':
        raise ValueError('RECOVERY_RESTORE_BINDING')
    manifest,data=_archive(value['backup_root'],value['backup_hash'])
    from workbench_shared_state import migration_receipt
    expected=migration_receipt(manifest,data,legacy=ev.parse(migration).get('schema')=='ar.shared-migration.v1')
    if (ev.parse(migration)!=expected or ev.canonical(receipt)!=ev.canonical({**expected,'status':'LOCAL_SHARED_RESTORE_VERIFIED'})):
        raise ValueError('RECOVERY_RESTORE_BINDING')
    code=Path(value['code_root'])
    runtime.verify_environment(Path(value['environment_root']),value['environment_hash'])
    if service.code_identity(code)!=value['code_identity'] or _runtime_sources(code)!=value['runtime_sources']:
        raise ValueError('RECOVERY_CODE_CHANGED')
    if service.asset_inventory(code)!=value['assets']: raise ValueError('RECOVERY_ASSETS_CHANGED')
    _check_resources(value['resources'])
    allowlist=root/'allowlist.json'
    if ((allowlist.stat().st_mode & 0o777)!=0o600
            or ev.parse(ev.read_local(root,'allowlist.json'))!={'members':[service.MEMBER]}):
        raise ValueError('RECOVERY_ALLOWLIST_CHANGED')
    database=runtime.safe_path(root/'state/shared-workbench.sqlite3')
    try:
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
                raise ValueError('RECOVERY_DATABASE_INVALID')
            from workbench_shared_state import ALL_TABLES, STORAGE_SCHEMA
            present={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            # governance-mutation: RECOVERY_DATABASE_TABLES
            if not set(ALL_TABLES).issubset(present) or present-set(ALL_TABLES)-{'shared_metadata','workspace_owner'}:
                raise ValueError('RECOVERY_DATABASE_TABLES')
            if db.execute('SELECT schema FROM shared_metadata WHERE singleton=1').fetchone()!=(STORAGE_SCHEMA,):
                raise ValueError('RECOVERY_DATABASE_SCHEMA')
            tables={name:[list(row) for row in db.execute('SELECT '+', '.join(columns)+' FROM '+name+' ORDER BY rowid')]
                    for name,columns in ALL_TABLES.items()}
            migration_row=db.execute('SELECT receipt FROM shared_migrations WHERE backup_hash=?',(value['backup_hash'],)).fetchone()
            # governance-mutation: RECOVERY_MIGRATION_BINDING
            if migration_row!=(ev.canonical(expected),):
                raise ValueError('RECOVERY_MIGRATION_BINDING')
            _source_history(tables,data['tables'])
            backup._validate_tables(tables)
            backup._verify_completed(root/'state',tables)
    except sqlite3.Error:
        raise ValueError('RECOVERY_DATABASE_INVALID') from None
    return value


def arguments(value):
    args=service.server_arguments(value)
    args+=['--shared-materials-v1','--governance-evidence-v1']
    if value['schema']==SCHEMA_V2 and value['features']['research_cards_enabled']:
        args+=['--shared-research-cards-v1']
    if value['schema']==SCHEMA_V3 and value['features']['research_cards_enabled']:
        args+=['--shared-research-cards-v1']
    # governance-mutation: RECOVERY_REVIEW_OPT_IN
    if value['schema']==SCHEMA_V3 and value['features']['human_review_enabled']:
        args+=['--shared-review-v1']
    source=value['resources']['source']; library=value['resources']['library']
    if source is not None: args+=['--read-only-source-root',source['root'],'--read-only-auto-sync']
    if library is not None:
        args+=['--research-library-root',library['root'],'--research-library-hash',value['resources']['library_hash']]
    return args


def prepare(root, backup_root, backup_hash, code_root, environment_root, environment_hash, port,
            *, source_root=None, library_root=None, library_hash=None,cards_enabled=False,review_enabled=False):
    if type(cards_enabled) is not bool or type(review_enabled) is not bool: raise ValueError('RECOVERY_FEATURES_INVALID')
    root,archive,code,environment=(runtime.safe_path(p) for p in (root,backup_root,code_root,environment_root))
    if (library_root is None)!=(library_hash is None): raise ValueError('RECOVERY_LIBRARY_PIN_REQUIRED')
    _roots(root,code,environment,archive,
           {k:{'root':str(v)} if v is not None else None for k,v in [('source',source_root),('library',library_root)]})
    resources={'source':_resource(source_root),'library':_resource(library_root),'library_hash':library_hash}
    _roots(root,code,environment,archive,{k:resources[k] for k in ('source','library')})
    if root.exists(): raise ValueError('RECOVERY_NEW_ROOT_REQUIRED')
    if type(port) is not int or not 18000<=port<=18999: raise ValueError('RECOVERY_PORT_INVALID')
    manifest,data=_archive(archive,backup_hash)
    _check_resources(resources)
    info=runtime.verify_environment(environment,environment_hash)
    identity=service.code_identity(code); assets=service.asset_inventory(code); sources=_runtime_sources(code)
    root.mkdir(mode=0o700)
    restored=backup.restore_shared(archive,root/'state')
    migration=ev.parse(ev.read_local(root/'state','migration-receipt.json'))
    backup.check_restored(root/'state',manifest,data,migration)
    _archive(archive,backup_hash)
    raw_restore=ev.canonical(restored).encode()
    backup.write_new(root/'restore.json',raw_restore)
    value={'schema':SCHEMA,'root':str(root),'code_root':str(code),'environment_root':str(environment),
        'environment_hash':environment_hash,'code_identity':identity,'assets':assets,'runtime_sources':sources,
        'port':port,'origin':service.ORIGIN,'owner':service.OWNER,'member':service.MEMBER,'max_restarts':2,
        'scope':'ISOLATED_ONLY','production_authority':False,'backup_root':str(archive),'backup_hash':backup_hash,
        'restore_hash':ev.sha(raw_restore),'migration_hash':ev.sha(ev.read_local(root/'state','migration-receipt.json')),
        'resources':resources}
    if cards_enabled:
        value.update(schema=SCHEMA_V2,features={'research_cards_enabled':True})
    if review_enabled:
        value.update(schema=SCHEMA_V3,features={'research_cards_enabled':cards_enabled,'human_review_enabled':True})
    _validate(value,root)
    backup.write_new(root/'allowlist.json',ev.canonical({'members':[service.MEMBER]}).encode())
    raw=ev.canonical(value).encode(); pin=ev.sha(raw)
    backup.write_new(root/'profile.draft.json',raw)
    _verify_value(value,root)
    command=[info['base_executable'],'-I','-B','-S',str(code/'scripts/llm/workbench_runtime.py'),
             'recovery-serve','--profile',str(root/'profile.json'),'--pin',pin,'--seconds','300']
    template={'Label':'com.ar.isolated-recovery.'+pin[:12],'ProgramArguments':command,'RunAtLoad':True,
        'WorkingDirectory':str(root),'EnvironmentVariables':runtime.clean_environment(root),
        'StandardOutPath':str(root/'launchd.stdout'),'StandardErrorPath':str(root/'launchd.stderr')}
    backup.write_new(root/'profile.json',raw)
    backup.write_new(root/'launchd.NOT_INSTALLED.plist',plistlib.dumps(template))
    backup.write_new(root/'READY.json',ev.canonical(_completion(value,pin)).encode())
    return {'status':'ISOLATED_RECOVERY_PREPARED_NOT_STARTED','root':str(root),'profile_hash':pin,
            'backup_hash':backup_hash,'code_sha':identity['code_sha'],'template_status':'GENERATED_NOT_INSTALLED',
            'physical_host_reboot':'NOT_ATTESTED','production_authority':False}


def serve(path, pin, seconds=300):
    if type(seconds) is not int or not 1<=seconds<=300: raise ValueError('RECOVERY_DURATION_INVALID')
    value=verify(path,pin); root=Path(value['root']); stopping=threading.Event()
    child=None; old={}; restarts=0; deadline=time.monotonic()+seconds
    def record(kind,**data):
        events=root/'events'
        if events.exists() and len(list(events.iterdir()))>=256: raise ValueError('RECOVERY_EVENT_LIMIT')
        body={'kind':kind,'profile_hash':pin,'time_ns':time.time_ns(),'scope':'ISOLATED_ONLY',**data}
        backup.write_new(events/(str(time.time_ns())+'-'+uuid.uuid4().hex+'.json'),ev.canonical(body).encode())
    with service.exclusive_lock(root):
        for sig in (signal.SIGINT,signal.SIGTERM): old[sig]=signal.signal(sig,lambda *_:stopping.set())
        try:
            while not stopping.is_set() and time.monotonic()<deadline:
                value=verify(path,pin)
                log=root/('child-'+uuid.uuid4().hex+'.log')
                argv=[str(Path(value['environment_root'])/'venv/bin/python3'),'-I','-B',
                      str(Path(value['code_root'])/'scripts/llm/workbench_runtime.py'),'recovery-child',
                      '--profile',str(path),'--pin',pin,'--parent',str(os.getpid())]
                with log.open('xb') as stream:
                    child=subprocess.Popen(argv,cwd=root,env=runtime.clean_environment(root),stdin=subprocess.DEVNULL,
                        stdout=stream,stderr=subprocess.STDOUT,close_fds=True,start_new_session=True)
                    record('CHILD_STARTED',pid=child.pid,restart_number=restarts)
                    while child.poll() is None and not stopping.wait(.2) and time.monotonic()<deadline: pass
                    if child.poll() is None: service.stop_owned(child)
                code=child.wait(); record('CHILD_EXITED',pid=child.pid,exit_code=code,log_hash=runtime.file_hash(log))
                if not service.should_restart(code,restarts,stopping.is_set() or time.monotonic()>=deadline): break
                restarts+=1; stopping.wait(.5)
            record('SUPERVISOR_STOPPED',restarts=restarts,child_exit=child.returncode if child else None)
            return {'status':'FAILED' if child and child.returncode not in (0,None) and not stopping.is_set() else 'STOPPED',
                'unexpected_restarts':restarts,'child_exit':child.returncode if child else None,'scope':'ISOLATED_ONLY',
                'physical_host_reboot':'NOT_ATTESTED','production_authority':False}
        finally:
            service.stop_owned(child)
            for sig,handler in old.items(): signal.signal(sig,handler)


def run_child(path,pin,parent):
    if type(parent) is not int or parent!=os.getppid(): raise ValueError('RECOVERY_PARENT_INVALID')
    value=verify(path,pin)
    import _thread
    def watch_parent():
        while os.getppid()==parent: time.sleep(.5)
        _thread.interrupt_main()
    threading.Thread(target=watch_parent,daemon=True).start()
    import nonprod_workbench
    return nonprod_workbench.main(arguments(value))
