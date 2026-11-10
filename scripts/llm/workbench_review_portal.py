"""Explicitly granted derived human review; never source-body or approval access."""
import csv
from datetime import datetime
import io
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

import workbench_evidence as ev
from workbench_backup import durable_directory, write_new
from workbench_workspace import WorkspaceError, exact, identifier
from workbench_snapshot_brief import reject_credentials

PACKET='ar.human-review-packet.v1'
GRANT='ar.human-review-grant.v1'
CAPABILITIES=['READ_DERIVED_SAMPLE','READ_SOURCE_METADATA','APPEND_OWN_ANNOTATION','READ_TEAM_ANNOTATIONS']
LABELS={'sample_purpose':'WORKFLOW_DEBUG','human_review':'PENDING','source_authenticity':'UNVERIFIED',
    'raw_source_body_allowed':False,'external_model_use_allowed':False,'u4_authority':False,
    'paper_authority':False,'production_authority':False,'trading_authority':False}
STATUSES={'MATCH','ISSUE','NEEDS_SOURCE','OUT_OF_SCOPE'}
SEVERITIES={'NONE','MINOR','MAJOR','BLOCKING'}
HEX=re.compile(r'[a-f0-9]{64}\Z')
FILES={'README.md','RESEARCH_SAMPLE.md','RESEARCH_SAMPLE.pdf','INPUT_MATERIALS.md',
       'FACTS.csv','REVIEW_TEMPLATE.md','REVIEW_ROWS.csv','PROVENANCE.json','VERIFICATION.json','FINAL_CHECKS.json'}


def _hash(value):
    if type(value) is not str or not HEX.fullmatch(value):raise ValueError('REVIEW_HASH_INVALID')
    return value


def _text(value,maximum=200,empty=False):
    if type(value) is not str or len(value)>maximum or (not empty and not value.strip()):
        raise ValueError('REVIEW_TEXT_INVALID')
    if any(ord(ch)<32 and ch not in '\n\t\r' for ch in value):raise ValueError('REVIEW_TEXT_INVALID')
    return value


def _exact(value,keys):
    if type(value) is not dict or set(value)!=set(keys):raise ValueError('REVIEW_FIELDS_INVALID')


def _audience(value):
    if (type(value) is not list or not 1<=len(value)<=2 or value!=sorted(set(value))
            or any(type(v) is not str or v!=v.strip().lower() or not re.fullmatch(r'[a-z0-9_.@+\-]{3,150}',v) for v in value)):
        raise ValueError('REVIEW_AUDIENCE_INVALID')
    return value


def make_grant(manifest_pin,audience,authorization_ref):
    return {'schema':GRANT,'packet_manifest_sha256':_hash(manifest_pin),'audience':_audience(audience),
        'capabilities':CAPABILITIES,'authorization_ref':_text(authorization_ref,2000),
        'raw_source_body_allowed':False,'external_model_use_allowed':False,'research_approval':False}


def _grant(value,pin,manifest_pin):
    _exact(value,{'schema','packet_manifest_sha256','audience','capabilities','authorization_ref',
                 'raw_source_body_allowed','external_model_use_allowed','research_approval'})
    # governance-mutation: REVIEW_GRANT_PIN
    if ev.sealed(value)!=_hash(pin) or ev.canonical(value)!=ev.canonical(make_grant(manifest_pin,value['audience'],value['authorization_ref'])):
        raise ValueError('REVIEW_GRANT_INVALID')
    return value


def _source(row):
    keep={k:row[k] for k in ('id','title','sha256')}
    _text(keep['id']);_text(keep['title'],1000);_hash(keep['sha256'])
    keep['kind']='SOURCE_METADATA_NOT_AUTHENTICATED'
    keep['rights_status']='UNVERIFIED_PRIVATE_SOURCE_BODY_DENIED'
    for key in ('published_at','captured_at'):
        keep[key]=_text(row[key],100) if key in row else None
    keep['pages']=row.get('pages',[])
    if type(keep['pages']) is not list or len(keep['pages'])>100 or any(type(n) is not int or n<1 for n in keep['pages']):
        raise ValueError('REVIEW_PAGES_INVALID')
    url=row.get('registered_public_url')
    if url is not None:
        parsed=urlsplit(url)
        # governance-mutation: REVIEW_SOURCE_URL
        if (parsed.scheme!='https' or parsed.netloc!='static.cninfo.com.cn' or parsed.query or parsed.fragment
                or not re.fullmatch(r'/finalpage/\d{4}-\d{2}-\d{2}/\d+\.PDF',parsed.path)):
            raise ValueError('REVIEW_SOURCE_URL_INVALID')
    keep['registered_public_url']=url
    keep['url_rechecked']=False
    return keep


def _prepare(root,pin):
    root=Path(root);raw=ev.read_local(root,'MANIFEST.json')
    # governance-mutation: REVIEW_PACKET_MANIFEST
    if ev.sha(raw)!=_hash(pin):raise ValueError('REVIEW_MANIFEST_PIN_MISMATCH')
    manifest=ev.parse(raw)
    names=manifest.get('files')
    if (type(names) is not dict or set(names)-FILES or not {'RESEARCH_SAMPLE.md','PROVENANCE.json','REVIEW_ROWS.csv'}<=set(names)
            or {p.name for p in root.iterdir()}!=set(names)|{'MANIFEST.json'}):
        raise ValueError('REVIEW_INPUT_FILES_INVALID')
    for name,checksum in names.items():
        if ev.sha(ev.read_local(root,name))!=_hash(checksum):raise ValueError('REVIEW_INPUT_CHANGED')
    p=ev.parse(ev.read_local(root,'PROVENANCE.json'))
    sample=ev.read_local(root,'RESEARCH_SAMPLE.md').decode('utf-8');_text(sample,65536)
    if re.search(r'(?:/Users/|/private/|file://|[A-Z]:\\)',sample):raise ValueError('REVIEW_PRIVATE_PATH')
    rows=list(csv.DictReader(io.StringIO(ev.read_local(root,'REVIEW_ROWS.csv').decode('utf-8-sig'))))
    if not 1<=len(rows)<=100:raise ValueError('REVIEW_ITEM_LIMIT')
    items=[{'id':_text(row['编号'],100),'layer':_text(row['归因层'],30),
            'title':_text(row['核对事项'],1000),'prompt':_text(row['提示'],2000)} for row in rows]
    if len({r['id'] for r in items})!=len(items):raise ValueError('REVIEW_ITEM_DUPLICATE')
    sources=[_source(row) for row in p['source_materials']]
    if len(sources)>32:raise ValueError('REVIEW_SOURCE_LIMIT')
    gaps=[{k:_text(row[k],4000) for k in ('id','title','status','reason')} for row in p['rules']] if 'rules' in p else []
    if len(gaps)>32:raise ValueError('REVIEW_GAP_LIMIT')
    value={'schema':PACKET,'packet_id':_text(p['packet_id']),'sample':sample,'items':items,'sources':sources,'gaps':gaps,
        'original_manifest_sha256':pin,'pack_hash':_hash(p['pack_hash']),'content_hash':_hash(p['content_hash']),
        'basis_hash':_hash(p['basis_hash']),'source_cutoff_at':_text(p['source_cutoff_at'],100),
        'daily_source_trade_date':_text(p['daily_source_trade_date'],8),
        'source_draft_generated_at':_text(p['source_draft_generated_at'],100),
        'source_producer':_text(p['source_producer'],40),'original_source_rights':'UNVERIFIED_PRIVATE_NOT_CHANGED',**LABELS}
    if not re.fullmatch(r'[a-f0-9]{40}',value['source_producer']):raise ValueError('REVIEW_PRODUCER_INVALID')
    if len(value['daily_source_trade_date'])!=8:raise ValueError('REVIEW_DATE_INVALID')
    datetime.strptime(value['daily_source_trade_date'],'%Y%m%d')
    if re.search(r'(?:/Users/|/private/|file://|[A-Z]:\\)',ev.canonical(value)):raise ValueError('REVIEW_PRIVATE_PATH')
    reject_credentials(value)
    if len(ev.canonical(value).encode())>256*1024:raise ValueError('REVIEW_PACKET_SIZE_LIMIT')
    # Never adopt a different input during the final copy/read boundary.
    if ev.read_local(root,'MANIFEST.json')!=raw or any(ev.sha(ev.read_local(root,n))!=h for n,h in names.items()):
        raise ValueError('REVIEW_INPUT_CHANGED')
    return value


def register(view,packet_root,manifest_pin,grant,grant_pin):
    if not view.review_enabled:raise ValueError('REVIEW_DISABLED')
    value=_prepare(packet_root,manifest_pin);_grant(grant,grant_pin,manifest_pin)
    raw=ev.canonical(value).encode();checksum=ev.sha(raw)
    grant_raw=ev.canonical(grant).encode()
    record={'packet_hash':checksum,'grant_hash':ev.sha(grant_raw),'manifest_sha256':manifest_pin,
            'packet_id':value['packet_id']}
    base=view.store.path.parent/'review-packets';target=base/checksum
    with view.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');events=view.system.events(db)
        prior=[e for e in events if e['kind']=='REVIEW_PACKET_REGISTERED' and e['data']['packet_hash']==checksum]
        if prior:
            if prior[0]['data']!=record:raise ValueError('REVIEW_REGISTRATION_CONFLICT')
            _retained(view.store.path.parent,record)
            return record
        if sum(e['kind']=='REVIEW_PACKET_REGISTERED' for e in events)>=20:raise ValueError('REVIEW_PACKET_CAPACITY')
        durable_directory(target)
        evidence=view.store.path.parent/'input-write-evidence'/('review-'+checksum)
        for name,body in (('packet.json',raw),('grant.json',grant_raw)):
            if (target/name).exists():
                if ev.read_local(target,name)!=body:raise ValueError('REVIEW_REGISTRATION_CONFLICT')
            else:write_new(target/name,body,evidence_root=evidence)
        _retained(view.store.path.parent,record)
        view.system.append(db,events,'review-register-'+checksum,ev.sealed(record),'REVIEW_PACKET_REGISTERED',record)
    return record


def _retained(root,record):
    _exact(record,{'packet_hash','grant_hash','manifest_sha256','packet_id'})
    for key in ('packet_hash','grant_hash','manifest_sha256'):_hash(record[key])
    base=Path(root)/'review-packets'/record['packet_hash']
    if {p.name for p in base.iterdir()}!={'packet.json','grant.json'}:raise ValueError('REVIEW_STORED_FILES_INVALID')
    raw=ev.read_local(base,'packet.json');grant_raw=ev.read_local(base,'grant.json')
    # governance-mutation: REVIEW_RETAINED_PINS
    if ev.sha(raw)!=record['packet_hash'] or ev.sha(grant_raw)!=record['grant_hash']:
        raise ValueError('REVIEW_RETAINED_PIN_MISMATCH')
    value=ev.parse(raw);grant=ev.parse(grant_raw)
    _grant(grant,record['grant_hash'],record['manifest_sha256'])
    if (value.get('schema')!=PACKET or value.get('packet_id')!=record['packet_id']
            or value.get('original_manifest_sha256')!=record['manifest_sha256']
            or any(value.get(k)!=v or type(value.get(k)) is not type(v) for k,v in LABELS.items())):
        raise ValueError('REVIEW_STORED_LABELS_INVALID')
    return value,grant


def _annotations(events,record,value,grant):
    rows=[];seen=set()
    for e in events:
        if e['kind']!='REVIEW_ANNOTATION' or e['data'].get('packet_hash')!=record['packet_hash']:continue
        row=e['data']
        _exact(row,{'packet_hash','item_id','actor','workspace_id','code_sha','status','severity','comment',
                    'human_review','research_approval','annotation_id'})
        if (row['actor'] not in grant['audience'] or row['actor']!=e.get('actor')
                or row['annotation_id']!=e['command_id'] or row['annotation_id'] in seen
                or row['item_id'] not in {r['id'] for r in value['items']}
                or row['status'] not in STATUSES or row['severity'] not in SEVERITIES
                or row['research_approval'] is not False or row['human_review']!='PENDING'
                or not re.fullmatch(r'[a-f0-9]{40}',row['code_sha'])
                or str(uuid.UUID(row['workspace_id']))!=row['workspace_id']):
            raise ValueError('REVIEW_ANNOTATION_BINDING_INVALID')
        _text(row['comment'],4000);reject_credentials(row);seen.add(row['annotation_id'])
        payload={'command_id':row['annotation_id'],'packet_hash':row['packet_hash'],'item_id':row['item_id'],
            'expected_workspace_id':row['workspace_id'],'expected_code_sha':row['code_sha'],
            'status':row['status'],'severity':row['severity'],'comment':row['comment']}
        if e['request_hash']!=ev.sealed({'payload':payload,'actor':row['actor']}):raise ValueError('REVIEW_REQUEST_BINDING_INVALID')
        rows.append({**row,'at':e['at'],'event_hash':e['event_hash']})
    if len(rows)>1000:raise ValueError('REVIEW_ANNOTATION_LIMIT')
    return rows


def verify_retained(root,events,identities=None):
    records=[e['data'] for e in events if e['kind']=='REVIEW_PACKET_REGISTERED']
    if len(records)>20 or len({r['packet_hash'] for r in records})!=len(records):raise ValueError('REVIEW_PACKET_CAPACITY')
    for record in records:
        value,grant=_retained(root,record);rows=_annotations(events,record,value,grant)
        if identities is not None and any(identities.get(row['actor'])!=row['workspace_id'] for row in rows):
            raise ValueError('REVIEW_WORKSPACE_BINDING_INVALID')
    admitted={r['packet_hash'] for r in records}
    if any(e['kind']=='REVIEW_ANNOTATION' and e['data'].get('packet_hash') not in admitted for e in events):
        raise ValueError('REVIEW_ANNOTATION_UNBOUND')


class ReviewPortal:
    def __init__(self,view):self.view=view

    def _load(self,actor,checksum,events=None):
        if not self.view.review_enabled:raise WorkspaceError('REVIEW_DISABLED',403)
        try:
            _hash(checksum)
            if events is None:
                with self.view.store.connect() as db:events=self.view.system.events(db)
            record=next((e['data'] for e in events if e['kind']=='REVIEW_PACKET_REGISTERED' and e['data']['packet_hash']==checksum),None)
            if record is None:raise WorkspaceError('REVIEW_NOT_FOUND',404)
            value,grant=_retained(self.view.store.path.parent,record)
            # governance-mutation: REVIEW_PACKET_AUDIENCE
            if actor not in grant['audience']:raise WorkspaceError('REVIEW_AUDIENCE_DENIED',403)
            rows=_annotations(events,record,value,grant)
            if any(self.view.identity(row['actor'])['workspace_id']!=row['workspace_id'] for row in rows):
                raise ValueError('REVIEW_WORKSPACE_BINDING_INVALID')
            return record,value,grant,events
        except WorkspaceError:raise
        except (ValueError,OSError,KeyError,TypeError):raise WorkspaceError('REVIEW_EVIDENCE_INVALID',409) from None

    def list(self,actor):
        if not self.view.review_enabled:raise WorkspaceError('REVIEW_DISABLED',403)
        with self.view.store.connect() as db:events=self.view.system.events(db)
        rows=[]
        for event in events:
            if event['kind']!='REVIEW_PACKET_REGISTERED':continue
            try:
                record,value,grant,_=self._load(actor,event['data']['packet_hash'],events)
            except WorkspaceError as error:
                if error.code=='REVIEW_AUDIENCE_DENIED':continue
                raise
            rows.append({**record,'source_cutoff_at':value['source_cutoff_at'],'daily_source_trade_date':value['daily_source_trade_date'],
                         'source_draft_generated_at':value['source_draft_generated_at']})
        return {'schema':'ar.human-review-list.v1','packets':rows,'my_workspace':self.view.identity(actor),
                'consumer_code_sha':self.view._execution_identity['code_sha'],**LABELS}

    def detail(self,checksum,actor):
        record,value,grant,events=self._load(actor,checksum)
        try:rows=_annotations(events,record,value,grant)
        except (ValueError,TypeError,KeyError):raise WorkspaceError('REVIEW_EVIDENCE_INVALID',409) from None
        return {'schema':'ar.human-review-detail.v1','packet_hash':checksum,'packet':value,'grant_hash':record['grant_hash'],
            'audience':grant['audience'],'annotations':rows,'my_workspace':self.view.identity(actor),
            'consumer_code_sha':self.view._execution_identity['code_sha'],**LABELS}

    def submit(self,payload,actor):
        try:
            exact(payload,{'command_id','packet_hash','item_id','expected_workspace_id','expected_code_sha','status','severity','comment'})
            identifier(payload['command_id']);_text(payload['comment'],4000);reject_credentials(payload)
            owner=self.view.identity(actor)
            # governance-mutation: REVIEW_COMMENT_CONTEXT
            if payload['expected_workspace_id']!=owner['workspace_id'] or payload['expected_code_sha']!=self.view._execution_identity['code_sha']:
                raise WorkspaceError('REVIEW_CONTEXT_CHANGED',409)
            with self.view.store.connect() as db:
                db.execute('BEGIN IMMEDIATE');events=self.view.system.events(db)
                record,value,grant,_=self._load(actor,payload['packet_hash'],events)
                if payload['item_id'] not in {r['id'] for r in value['items']} or payload['status'] not in STATUSES or payload['severity'] not in SEVERITIES:
                    raise WorkspaceError('REVIEW_COMMENT_INVALID',400)
                bound={'packet_hash':payload['packet_hash'],'item_id':payload['item_id'],'actor':actor,
                    'workspace_id':owner['workspace_id'],'code_sha':payload['expected_code_sha'],
                    'status':payload['status'],'severity':payload['severity'],'comment':payload['comment'],
                    'human_review':'PENDING','research_approval':False,'annotation_id':payload['command_id']}
                request_hash=ev.sealed({'payload':payload,'actor':actor})
                existing=next((e for e in events if e['command_id']==payload['command_id']),None)
                if existing:
                    # governance-mutation: REVIEW_COMMENT_RETRY
                    if existing['kind']!='REVIEW_ANNOTATION' or existing['request_hash']!=request_hash or existing.get('actor')!=actor:
                        raise WorkspaceError('REVIEW_COMMAND_CONFLICT',409)
                    annotation=next(r for r in _annotations(events,record,value,grant) if r['annotation_id']==payload['command_id'])
                    return {'disposition':'IDEMPOTENT','annotation':annotation,**LABELS}
                if len(_annotations(events,record,value,grant))>=1000:raise WorkspaceError('REVIEW_COMMENT_CAPACITY',429)
                event=self.view.system.append(db,events,payload['command_id'],request_hash,'REVIEW_ANNOTATION',bound,actor=actor)
                return {'disposition':'APPENDED','annotation':{**bound,'at':event['at'],'event_hash':event['event_hash']},**LABELS}
        except WorkspaceError:raise
        except (ValueError,OSError,KeyError,TypeError):raise WorkspaceError('REVIEW_COMMENT_INVALID',400) from None
