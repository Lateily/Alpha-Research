"""Isolated, pinned operations rehearsal. No installer or live takeover API."""
import argparse
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import plistlib
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

sys.dont_write_bytecode = True
sys.pycache_prefix = '/dev/null'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import workbench_backup as backup
import workbench_evidence as ev
import workbench_recovery as recovery
import workbench_runtime_env as runtime
import workbench_runtime_service as service

FIELDS = {'schema', 'root', 'recovery_profile', 'recovery_pin', 'code_sha',
          'max_crashes', 'scope', 'production_authority'}


def _disjoint(*paths):
    paths = [runtime.safe_path(p) for p in paths]
    if any(a == b or a in b.parents or b in a.parents
           for i, a in enumerate(paths) for b in paths[i+1:]):
        raise ValueError('OPERATIONS_ROOT_OVERLAP')


def prepare(root, profile, pin):
    root, profile = runtime.safe_path(root), runtime.safe_path(profile)
    value = recovery.verify(profile, pin)
    _disjoint(root, profile.parent, value['code_root'], value['environment_root'])
    if root.exists(): raise ValueError('OPERATIONS_NEW_ROOT_REQUIRED')
    if any((p/'.git').exists() for p in (root, *root.parents)):
        raise ValueError('OPERATIONS_ROOT_INSIDE_REPOSITORY')
    environment = runtime.verify_environment(Path(value['environment_root']), value['environment_hash'])
    body = {'schema': 'ar.workbench-operations.v1', 'root': str(root),
            'recovery_profile': str(profile), 'recovery_pin': pin,
            'code_sha': value['code_identity']['code_sha'], 'max_crashes': 3,
            'scope': 'ISOLATED_ONLY', 'production_authority': False}
    raw = ev.canonical(body).encode(); digest = ev.sha(raw)
    root.mkdir(mode=0o700)
    backup.write_new(root/'operations.json', raw)
    script = Path(value['code_root'])/'scripts/llm/workbench_operations.py'
    # Pin the entry bytes before the interpreter executes application code.
    bootstrap = ('import hashlib,pathlib,sys; p=pathlib.Path(sys.argv.pop(1)); '
                 'h=sys.argv.pop(1); b=p.read_bytes(); '
                 'assert hashlib.sha256(b).hexdigest()==h; '
                 'exec(compile(b,str(p),"exec"),{"__name__":"__main__","__file__":str(p)})')
    command = [environment['base_executable'], '-I', '-B', '-S', '-c', bootstrap,
               str(script), runtime.file_hash(script), 'serve', '--root', str(root),
               '--pin', digest, '--resident']
    template = {'Label': 'com.ar.isolated-operations.'+digest[:12], 'RunAtLoad': True,
                'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 60,
                'LimitLoadToSessionType': 'Aqua', 'ProgramArguments': command,
                'WorkingDirectory': str(root), 'EnvironmentVariables': runtime.clean_environment(root),
                'StandardOutPath': str(root/'supervisor.stdout'),
                'StandardErrorPath': str(root/'supervisor.stderr')}
    backup.write_new(root/'launchd.NOT_INSTALLED.plist', plistlib.dumps(template))
    return {'operations_hash': digest, 'root': str(root), 'installed': False,
            'template_status': 'GENERATED_NOT_INSTALLED', 'physical_host_reboot': 'NOT_ATTESTED'}


def verify(root, pin):
    root = runtime.safe_path(root)
    raw = ev.read_local(root, 'operations.json')
    # governance-mutation: OPERATIONS_EXTERNAL_PIN
    if type(pin) is not str or not runtime.HEX.fullmatch(pin) or ev.sha(raw) != pin:
        raise ValueError('OPERATIONS_PIN_MISMATCH')
    value = ev.parse(raw)
    if (type(value) is not dict or set(value) != FIELDS
            or value['schema'] != 'ar.workbench-operations.v1' or value['root'] != str(root)
            or type(value['max_crashes']) is not int or value['max_crashes'] != 3
            or value['scope'] != 'ISOLATED_ONLY' or value['production_authority'] is not False):
        raise ValueError('OPERATIONS_MANIFEST_INVALID')
    profile = runtime.safe_path(value['recovery_profile'])
    retained = recovery.verify(profile, value['recovery_pin'])
    _disjoint(root, profile.parent, retained['code_root'], retained['environment_root'])
    if retained['code_identity']['code_sha'] != value['code_sha']:
        raise ValueError('OPERATIONS_CODE_BINDING')
    return value


class Journal:
    """Each reservation is committed before creating a child, never cleared on boot."""
    def __init__(self, root, pin):
        self.root = runtime.safe_path(root)
        if type(pin) is not str or not runtime.HEX.fullmatch(pin): raise ValueError('OPERATIONS_PIN_INVALID')
        backup.durable_directory(self.root)
        self.path = runtime.safe_path(self.root/'operations.sqlite3')
        self.pin = pin
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY CHECK(id=1), pin TEXT NOT NULL, crashes INTEGER NOT NULL, active TEXT, status TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO control VALUES (1,?,0,NULL,'STOPPED')", (pin,))
            if db.execute('SELECT pin FROM control').fetchall() != [(pin,)]:
                raise ValueError('OPERATIONS_JOURNAL_BINDING')
            self.audit(db)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        runtime.safe_path(self.path)
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback(); raise

    def event(self, db, kind, **fields):
        rows = db.execute('SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        seq, previous = (rows[0]+1, rows[1]) if rows else (1, None)
        if seq > 8192: raise ValueError('OPERATIONS_EVENT_LIMIT')
        body = {'kind': kind, 'previous': previous, 'pin': self.pin, **fields}
        db.execute('INSERT INTO events VALUES (?,?,?)', (seq, ev.canonical(body), ev.sealed(body)))

    def audit(self, db):
        active = None; crashes = 0; status = 'STOPPED'; previous = None
        for expected, (seq, raw, digest) in enumerate(db.execute('SELECT seq,body,hash FROM events ORDER BY seq'), 1):
            body = ev.parse(raw)
            if (seq != expected or expected > 8192 or ev.sealed(body) != digest
                    or body.get('previous') != previous or body.get('pin') != self.pin):
                raise ValueError('OPERATIONS_JOURNAL_DAMAGED')
            kind = body.get('kind')
            if kind == 'START_RESERVED' and active is None and status != 'FENCED' and crashes < 3:
                active = body['attempt']; status = 'STARTING'
            elif kind == 'UNCERTAIN_START_FENCED' and active is not None:
                crashes += 1; status = 'FENCED'
            elif kind == 'CHILD_STOPPED' and active is not None and body['attempt'] == active:
                crashes += int(not body['planned'] and body['exit_code'] != 0)
                active = None; status = 'FENCED' if crashes >= 3 else 'STOPPED'
            else: raise ValueError('OPERATIONS_JOURNAL_DAMAGED')
            previous = digest
        # governance-mutation: OPERATIONS_JOURNAL_REPLAY_BINDING
        if db.execute('SELECT pin,crashes,active,status FROM control').fetchall() != [(self.pin,crashes,active,status)]:
            raise ValueError('OPERATIONS_JOURNAL_DAMAGED')

    def snapshot(self):
        with self.connect() as db:
            self.audit(db)
            pin, crashes, active, status = db.execute('SELECT pin,crashes,active,status FROM control').fetchone()
            return {'pin': pin, 'crashes': crashes, 'active': active, 'status': status}

    def reserve(self):
        error = None; token = str(uuid.uuid4())
        with self.connect() as db:
            self.audit(db)
            crashes, active, status = db.execute('SELECT crashes,active,status FROM control').fetchone()
            # governance-mutation: OPERATIONS_PERSISTENT_CRASH_BUDGET
            if status == 'FENCED' or crashes >= 3:
                error = 'OPERATIONS_FENCED'
            # governance-mutation: OPERATIONS_UNCERTAIN_START
            elif active is not None:
                db.execute("UPDATE control SET status='FENCED', crashes=crashes+1 WHERE id=1")
                self.event(db, 'UNCERTAIN_START_FENCED')
                error = 'OPERATIONS_UNCERTAIN_START'
            else:
                db.execute("UPDATE control SET active=?,status='STARTING' WHERE id=1", (token,))
                self.event(db, 'START_RESERVED', attempt=token)
        if error: raise ValueError(error)
        return token

    def finish(self, token, exit_code, *, planned):
        if type(exit_code) is not int or type(planned) is not bool: raise ValueError('OPERATIONS_EXIT_INVALID')
        with self.connect() as db:
            self.audit(db)
            active, crashes = db.execute('SELECT active,crashes FROM control').fetchone()
            if active != token or active is None: raise ValueError('OPERATIONS_ATTEMPT_BINDING')
            crashes += int(not planned and exit_code != 0)
            status = 'FENCED' if crashes >= 3 else 'STOPPED'
            db.execute('UPDATE control SET active=NULL,crashes=?,status=? WHERE id=1', (crashes,status))
            self.event(db, 'CHILD_STOPPED', attempt=token, exit_code=exit_code, planned=planned)
        return self.snapshot()


def serve(root, pin, seconds=300):
    if seconds is not None and (type(seconds) is not int or not 1 <= seconds <= 300):
        raise ValueError('OPERATIONS_DURATION_INVALID')
    value = verify(root, pin)
    profile = Path(value['recovery_profile'])
    stop = threading.Event(); handlers = {}; child = None
    deadline = None if seconds is None else time.monotonic()+seconds
    with service.exclusive_lock(profile.parent):
        journal = Journal(root, pin)
        for sig in (signal.SIGINT, signal.SIGTERM): handlers[sig] = signal.signal(sig, lambda *_: stop.set())
        try:
            while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
                verify(root, pin)
                retained = recovery.verify(profile, value['recovery_pin'])
                token = journal.reserve()
                argv = [str(Path(retained['environment_root'])/'venv/bin/python3'), '-I', '-B',
                        str(Path(retained['code_root'])/'scripts/llm/workbench_runtime.py'),
                        'recovery-child', '--profile', str(profile), '--pin', value['recovery_pin'],
                        '--parent', str(os.getpid())]
                log = Path(root)/('child-'+token+'.log')
                with log.open('xb') as stream:
                    child = subprocess.Popen(argv, cwd=profile.parent, env=runtime.clean_environment(root),
                                             stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                             close_fds=True, start_new_session=True)
                    while child.poll() is None and not stop.wait(.2):
                        if deadline is not None and time.monotonic() >= deadline: break
                    planned = stop.is_set() or deadline is not None and time.monotonic() >= deadline
                    if child.poll() is None: service.stop_owned(child)
                    result = journal.finish(token, child.wait(), planned=planned)
                if result['status'] == 'FENCED' or planned or child.returncode == 0: break
                stop.wait(1)
            return {**journal.snapshot(), 'scope': 'ISOLATED_ONLY', 'physical_host_reboot': 'NOT_ATTESTED'}
        finally:
            service.stop_owned(child)
            for sig, handler in handlers.items(): signal.signal(sig, handler)


def rehearse_backup(store, root):
    root = runtime.safe_path(root)
    _disjoint(root, store.path.parent)
    if root.exists(): raise ValueError('OPERATIONS_NEW_ROOT_REQUIRED')
    root.mkdir(mode=0o700)
    exported = backup.backup_shared(store, root/'archive')
    restored = backup.restore_shared(root/'archive', root/'restored')
    receipt = {'schema': 'ar.operations-restore.v1', 'status': 'LOCAL_NEWEST_RESTORE_VERIFIED',
               'backup_hash': exported['backup_hash'], 'restore': restored,
               'credentials_restored': False, 'other_machine_restore': 'NOT_ATTESTED',
               'writer_stopped_attestation': 'NOT_ATTESTED_CONSISTENT_SNAPSHOT_ONLY'}
    raw = ev.canonical(receipt).encode(); backup.write_new(root/'receipt.json', raw)
    verify_backup_rehearsal(root, ev.sha(raw))
    return {**receipt, 'receipt_hash': ev.sha(raw)}


def verify_backup_rehearsal(root, pin):
    root = runtime.safe_path(root); raw = ev.read_local(root, 'receipt.json')
    if ev.sha(raw) != pin: raise ValueError('OPERATIONS_BACKUP_RECEIPT_PIN')
    receipt = ev.parse(raw); manifest, data = backup.read_shared(root/'archive')
    # governance-mutation: OPERATIONS_RESTORE_GENERATION_BINDING
    if receipt['backup_hash'] != manifest['backup_hash'] or receipt['restore']['backup_hash'] != manifest['backup_hash']:
        raise ValueError('OPERATIONS_RESTORE_GENERATION_BINDING')
    migration = ev.parse(ev.read_local(root/'restored', 'migration-receipt.json'))
    backup.check_restored(root/'restored', manifest, data, migration)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    make = sub.add_parser('prepare')
    make.add_argument('--root', type=Path, required=True); make.add_argument('--profile', type=Path, required=True)
    make.add_argument('--pin', required=True)
    for name in ('verify', 'serve'):
        p = sub.add_parser(name); p.add_argument('--root', type=Path, required=True); p.add_argument('--pin', required=True)
        if name == 'serve':
            duration = p.add_mutually_exclusive_group()
            duration.add_argument('--seconds', type=int, default=300); duration.add_argument('--resident', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare': result = prepare(args.root, args.profile, args.pin)
    elif args.command == 'verify': result = verify(args.root, args.pin)
    else: result = serve(args.root, args.pin, None if args.resident else args.seconds)
    print(json.dumps(result, sort_keys=True))
    return 2 if result.get('status') == 'FENCED' else 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error) as exc:
        print('ISOLATED_OPERATIONS_REFUSED: '+type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
