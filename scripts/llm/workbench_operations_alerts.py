"""Offline observer/outbox state, not a probe, sender or human attestation."""
from contextlib import contextmanager, closing
from pathlib import Path
import re
import sqlite3

import workbench_backup as backup
import workbench_evidence as ev
import workbench_runtime_env as runtime

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z')
FIELDS = {'schema','service','host','sequence','sent_at','code_sha','health'}
HEALTH = {'HEALTHY','SYNC_FAILED','STALE','FENCED','READ_FAILED'}


def name(value):
    if type(value) is not str or not NAME.fullmatch(value): raise ValueError('OBSERVER_NAME_INVALID')
    return value


def timestamp(value):
    if type(value) is not int or not 0 <= value <= 253402300799:
        raise ValueError('OBSERVER_CLOCK_INVALID')
    return value


class Observer:
    def __init__(self, root, *, service, host, observer):
        self.binding = {'service':name(service),'host':name(host),'observer':name(observer)}
        # governance-mutation: OPERATIONS_EXTERNAL_OBSERVER_IDENTITY
        if host == observer: raise ValueError('OBSERVER_HOST_NOT_INDEPENDENT')
        self.root = runtime.safe_path(root); backup.durable_directory(self.root)
        self.path = runtime.safe_path(self.root/'observer.sqlite3')
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT NOT NULL, started INTEGER, checked INTEGER, sequence INTEGER, last_seen INTEGER, sent INTEGER, state TEXT NOT NULL, incident INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS delivery (id TEXT PRIMARY KEY, receipt TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO state VALUES(1,?,NULL,NULL,0,NULL,NULL,'AWAITING_HEARTBEAT',0)", (ev.canonical(self.binding),))
            if db.execute('SELECT binding FROM state').fetchall() != [(ev.canonical(self.binding),)]:
                raise ValueError('OBSERVER_BINDING')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        runtime.safe_path(self.path)
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback(); raise

    def clock(self, db, now):
        timestamp(now)
        before = db.execute('SELECT checked FROM state').fetchone()[0]
        # governance-mutation: OPERATIONS_OBSERVER_CLOCK
        if before is not None and now < before: raise ValueError('OBSERVER_CLOCK_ROLLBACK')
        db.execute('UPDATE state SET started=coalesce(started,?),checked=? WHERE id=1', (now,now))

    def alert(self, db, kind, at, incident):
        if db.execute('SELECT count(*) FROM outbox').fetchone()[0] >= 4096:
            raise ValueError('OBSERVER_OUTBOX_LIMIT')
        body = {'schema':'ar.operations-alert.v1', **self.binding, 'kind':kind, 'at':at,
                'incident':incident, 'evidence_grade':'SYNTHETIC_OR_OPERATOR_RECORDED_NOT_ATTESTED'}
        key = ev.sealed({'binding':self.binding,'kind':kind,'incident':incident})
        db.execute('INSERT OR IGNORE INTO outbox VALUES (?,?)', (key,ev.canonical({**body,'id':key})))

    def accept(self, pulse, *, received_at):
        if (type(pulse) is not dict or set(pulse) != FIELDS
                or pulse['schema'] != 'ar.workbench-heartbeat.v1'
                or pulse['service'] != self.binding['service'] or pulse['host'] != self.binding['host']
                or type(pulse['sequence']) is not int or not 1 <= pulse['sequence'] <= 2**53-1
                or type(pulse['code_sha']) is not str or not re.fullmatch(r'[0-9a-f]{40}',pulse['code_sha'])
                or type(pulse['health']) is not str or pulse['health'] not in HEALTH):
            raise ValueError('OBSERVER_HEARTBEAT_INVALID')
        sent = timestamp(pulse['sent_at']); now = timestamp(received_at)
        # governance-mutation: OPERATIONS_HEARTBEAT_FRESHNESS
        if not 0 <= now-sent <= 60: raise ValueError('OBSERVER_HEARTBEAT_STALE_OR_FUTURE')
        with self.connect() as db:
            self.clock(db, now)
            sequence, previous_sent, previous_state, incident = db.execute('SELECT sequence,sent,state,incident FROM state').fetchone()
            # governance-mutation: OPERATIONS_HEARTBEAT_REPLAY
            if pulse['sequence'] <= sequence or previous_sent is not None and sent < previous_sent:
                raise ValueError('OBSERVER_HEARTBEAT_REPLAY')
            healthy = pulse['health'] == 'HEALTHY'
            current = 'HEALTHY' if healthy else 'SERVICE_DEGRADED'
            if not healthy and previous_state != current:
                incident += 1; self.alert(db,current,now,incident)
            elif healthy and previous_state not in {'HEALTHY','AWAITING_HEARTBEAT'}:
                self.alert(db,'RECOVERED',now,incident)
            db.execute('UPDATE state SET sequence=?,sent=?,last_seen=?,state=?,incident=? WHERE id=1',
                       (pulse['sequence'],sent,now,current,incident))
        return self.check(now)

    def check(self, now):
        with self.connect() as db:
            self.clock(db, now)
            started, last_seen, state, incident = db.execute('SELECT started,last_seen,state,incident FROM state').fetchone()
            last = last_seen if last_seen is not None else started
            # governance-mutation: OPERATIONS_LOSS_TIMEOUT
            if now-last >= 300 and state != 'HOST_LOST':
                incident += 1; state = 'HOST_LOST'; self.alert(db,state,now,incident)
                db.execute('UPDATE state SET state=?,incident=? WHERE id=1', (state,incident))
            outbox = [ev.parse(row[0]) for row in db.execute('SELECT body FROM outbox ORDER BY rowid')]
        return {'status':state,'outbox':outbox,'external_detection':'NOT_ATTESTED',
                'phone_delivery':'NOT_ATTESTED','human_acknowledgement':'PENDING'}

    def record_delivery(self, alert_id, *, channel, receipt_hash, at):
        name(channel); timestamp(at)
        if type(receipt_hash) is not str or not runtime.HEX.fullmatch(receipt_hash):
            raise ValueError('OBSERVER_DELIVERY_INVALID')
        receipt = {'channel':channel,'receipt_hash':receipt_hash,'at':at,'attestation':'NOT_ATTESTED'}
        with self.connect() as db:
            self.clock(db,at)
            if db.execute('SELECT id FROM outbox WHERE id=?',(alert_id,)).fetchone() is None:
                raise ValueError('OBSERVER_ALERT_UNKNOWN')
            previous = db.execute('SELECT receipt FROM delivery WHERE id=?',(alert_id,)).fetchone()
            if previous and previous != (ev.canonical(receipt),): raise ValueError('OBSERVER_DELIVERY_CONFLICT')
            db.execute('INSERT OR IGNORE INTO delivery VALUES(?,?)',(alert_id,ev.canonical(receipt)))
        return {'recorded':True,'phone_delivery':'NOT_ATTESTED','human_acknowledgement':'PENDING'}
