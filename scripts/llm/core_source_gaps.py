"""Append-only finite source-gap observations; never a provider dispatcher."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import argparse
import fcntl
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.data_governance.endpoint_calls import read_endpoint_receipts
import workbench_evidence as ev
from workbench_backup import durable_directory, write_new
from workbench_runtime_env import safe_path

ZERO='0'*64
CORE={'daily':{'ts_code','trade_date','close'},'moneyflow_dc':{'ts_code','trade_date','net_amount'}}
LABELS={'sample_purpose':'WORKFLOW_DEBUG','research_readiness':'NOT_EVALUATED','rights':'UNVERIFIED',
        'automatic_retry':False,'production_authority':False,'prospective_sample_eligible':False}
META={'schema':'ar.core-gap-ledger.v1','max_events':256,'max_observed_attempts_for_proposal':2,
      'proposal_delay_minutes':15,**LABELS}
EVENT_FIELDS={'schema','sequence','previous_hash','recorded_at','evidence_hash','event_hash',*LABELS}


def _hash(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value): raise ValueError('GAPS_HASH_INVALID')
    return value


def _time(value):
    if type(value) is not str: raise ValueError('GAPS_TIME_INVALID')
    try: result=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError: raise ValueError('GAPS_TIME_INVALID') from None
    if result.tzinfo is None or result.utcoffset() is None: raise ValueError('GAPS_TIME_INVALID')
    return result.astimezone(timezone.utc)


def _stamp(value): return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')


def _inventory(root):
    files={}; size=0
    for count,path in enumerate(root.rglob('*'),1):
        # governance-mutation: CORE_GAPS_INVENTORY_BOUND
        if count>512: raise ValueError('GAPS_EVIDENCE_LIMIT')
        safe_path(path)
        if path.is_dir(): continue
        if not path.is_file() or len(files)>=128: raise ValueError('GAPS_EVIDENCE_LIMIT')
        name=path.relative_to(root).as_posix(); raw=ev.read_local(root,name)
        size+=len(raw)
        if size>16*1024*1024: raise ValueError('GAPS_EVIDENCE_LIMIT')
        files[name]=ev.sha(raw)
    return files


def evidence(root):
    root=safe_path(root); files=_inventory(root)
    calls=read_endpoint_receipts(root)
    if not 1<=len(calls)<=32: raise ValueError('GAPS_FINITE_EVIDENCE_REQUIRED')
    for row in calls:
        start=row['start']; params=start['params']; api=start['api_name']
        # governance-mutation: CORE_GAPS_EXACT_SCOPE
        if (api not in CORE or set(start['fields'].split(','))!=CORE[api] or set(params)!={'ts_code','trade_date'}
                or params['trade_date']!=start['target_trade_date']):
            raise ValueError('GAPS_OUT_OF_SCOPE')
        for name in ('calls/'+start['logical_call_id']+'/start.json',
                     'catalogs/'+start['catalog_hash']+'.json'):
            if name not in files: raise ValueError('GAPS_EVIDENCE_CHANGED')
    after=_inventory(root)
    if after!=files: raise ValueError('GAPS_EVIDENCE_CHANGED')
    return {'evidence_hash':ev.sealed(files),'files':files,'calls':calls}


def _scope(row):
    start=row['start']
    return {'api_name':start['api_name'],'ts_code':start['params']['ts_code'],
            'trade_date':start['target_trade_date'],'fields':start['fields']}


def _binding(row, files):
    start=row['start']; prefix='calls/'+start['logical_call_id']+'/'
    return ev.sealed({'row':row,'start':files[prefix+'start.json'],
        'terminal':files.get(prefix+'terminal.json'),'catalog':files['catalogs/'+start['catalog_hash']+'.json']})


def _root(root):
    root=safe_path(root)
    # governance-mutation: CORE_GAPS_REPOSITORY_ROOT
    if any((p/'.git').exists() for p in (root,*root.parents)): raise ValueError('GAPS_ROOT_INSIDE_REPOSITORY')
    if root.exists():
        if not root.is_dir() or root.stat().st_uid!=os.getuid() or root.stat().st_mode & 0o077:
            raise ValueError('GAPS_PRIVATE_ROOT_REQUIRED')
        if any(p.name not in {'metadata.json','ledger.lock','events','sources','write-evidence'} for p in root.iterdir()):
            raise ValueError('GAPS_ROOT_CONTENT_INVALID')
    return root


def _read(root):
    root=_root(root)
    if not root.exists(): return [],ZERO,[]
    if ev.canonical(ev.parse(ev.read_local(root,'metadata.json')))!=ev.canonical(META):
        raise ValueError('GAPS_METADATA_INVALID')
    events=safe_path(root/'events'); paths=sorted(events.iterdir()) if events.exists() else []
    if len(paths)>256: raise ValueError('GAPS_CAPACITY')
    result=[]; head=ZERO; known={}; calls=[]; last_time=None
    for index,path in enumerate(paths,1):
        value=ev.parse(ev.read_local(events,path.name))
        if (type(value) is not dict or set(value)!=EVENT_FIELDS or value['schema']!='ar.core-gap-event.v1'
                or type(value['sequence']) is not int or value['sequence']!=index
                or value['previous_hash']!=head or any(type(value[k]) is not type(v) or value[k]!=v for k,v in LABELS.items())
                or ev.sealed({k:v for k,v in value.items() if k!='event_hash'})!=value['event_hash']
                or path.name!=f'{index:06d}-'+value['event_hash']+'.json'):
            raise ValueError('GAPS_CHAIN_INVALID')
        captured=_time(value['recorded_at'])
        if last_time is not None and captured<last_time: raise ValueError('GAPS_CLOCK_REVERSED')
        last_time=captured; _hash(value['evidence_hash'])
        frozen=evidence(root/'sources'/value['evidence_hash'])
        # governance-mutation: CORE_GAPS_FROZEN_PIN
        if frozen['evidence_hash']!=value['evidence_hash']: raise ValueError('GAPS_EVIDENCE_PIN_MISMATCH')
        for row in frozen['calls']:
            call=row['start']['logical_call_id']; binding=_binding(row,frozen['files'])
            if call in known:
                if known[call]!=binding: raise ValueError('GAPS_CALL_EVIDENCE_CHANGED')
                continue
            known[call]=binding
            calls.append({'row':row,'evidence_hash':value['evidence_hash'],'recorded_at':value['recorded_at']})
        result.append(value); head=value['event_hash']
    return result,head,calls


@contextmanager
def _lock(root):
    path=safe_path(root/'ledger.lock')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('GAPS_LEDGER_BUSY') from None
        yield
    finally: os.close(fd)


def ingest(root,source_root,*,expected_evidence_hash,expected_head):
    _hash(expected_evidence_hash); _hash(expected_head)
    source=safe_path(source_root); root=_root(root)
    if source==root or source in root.parents or root in source.parents: raise ValueError('GAPS_ROOT_OVERLAP')
    frozen=evidence(source)
    # governance-mutation: CORE_GAPS_EXTERNAL_PIN
    if frozen['evidence_hash']!=expected_evidence_hash: raise ValueError('GAPS_EVIDENCE_PIN_MISMATCH')
    if not root.exists():
        if expected_head!=ZERO: raise ValueError('GAPS_HEAD_CONFLICT')
        durable_directory(root)
    with _lock(root):
        if not (root/'metadata.json').exists():
            if set(p.name for p in root.iterdir())!={'ledger.lock'}: raise ValueError('GAPS_ROOT_UNBOUND')
            write_new(root/'metadata.json',ev.canonical(META).encode(),evidence_root=root/'write-evidence')
        events,head,calls=_read(root)
        # governance-mutation: CORE_GAPS_HEAD_CAS
        if head!=expected_head: raise ValueError('GAPS_HEAD_CONFLICT')
        if any(event['evidence_hash']==expected_evidence_hash for event in events):
            return {'head_hash':head,'disposition':'IDEMPOTENT',**LABELS}
        if len(events)>=256: raise ValueError('GAPS_CAPACITY')
        known={item['row']['start']['logical_call_id']:_binding(item['row'],evidence(
            root/'sources'/item['evidence_hash'])['files']) for item in calls}
        for row in frozen['calls']:
            call=row['start']['logical_call_id']
            if call in known and known[call]!=_binding(row,frozen['files']):
                raise ValueError('GAPS_CALL_EVIDENCE_CHANGED')
        target=safe_path(root/'sources'/expected_evidence_hash)
        if target.exists():
            try: prior=evidence(target)
            except (ValueError,OSError): raise ValueError('GAPS_SOURCE_RECONCILIATION_REQUIRED') from None
            if prior['evidence_hash']!=expected_evidence_hash: raise ValueError('GAPS_SOURCE_RECONCILIATION_REQUIRED')
        else:
            durable_directory(target)
            for name,pin in sorted(frozen['files'].items()):
                raw=ev.read_local(source,name)
                if ev.sha(raw)!=pin: raise ValueError('GAPS_EVIDENCE_CHANGED')
                write_new(target/name,raw,evidence_root=root/'write-evidence')
        if evidence(target)['evidence_hash']!=expected_evidence_hash or evidence(source)!=frozen:
            raise ValueError('GAPS_EVIDENCE_CHANGED')
        now=_stamp(datetime.now(timezone.utc))
        if events and _time(now)<_time(events[-1]['recorded_at']): raise ValueError('GAPS_CLOCK_REVERSED')
        event={'schema':'ar.core-gap-event.v1','sequence':len(events)+1,'previous_hash':head,
               'recorded_at':now,'evidence_hash':expected_evidence_hash,**LABELS}
        event['event_hash']=ev.sealed(event)
        write_new(root/'events'/(f'{len(events)+1:06d}-'+event['event_hash']+'.json'),
                  ev.canonical(event).encode(),evidence_root=root/'write-evidence')
        return {'head_hash':event['event_hash'],'disposition':'APPENDED',**LABELS}


def view(root,*,expected_head,observed_at):
    _hash(expected_head); when=_time(observed_at)
    events,head,calls=_read(root)
    if head!=expected_head: raise ValueError('GAPS_HEAD_CONFLICT')
    scopes={}
    for item in calls:
        row=item['row']; start=row['start']; result=row['result']
        stamp=result['completed_at'] or start['invoked_at']
        # Ingestion is the earliest local knowledge, not the old requested day.
        if _time(item['recorded_at'])>when or _time(stamp)>when: continue
        scope=_scope(row); key=ev.sealed(scope)
        group=scopes.setdefault(key,{'gap_id':key,**scope,'history':[]})
        group['history'].append({'logical_call_id':start['logical_call_id'],'evidence_hash':item['evidence_hash'],
            'observation_time':stamp,'ingested_at':item['recorded_at'],'request_status':result['request_status'],
            'dataset_quality':result['dataset_quality'],'reasons':result['gaps'],'error_code':result['error_code'],
            'completed_at':result['completed_at'],'response_hash':result['response_hash']})
    for row in scopes.values():
        history=row['history']; history.sort(key=lambda x:(_time(x['observation_time']),x['logical_call_id']))
        latest=history[-1]; latest_time=_time(latest['observation_time'])
        same=[h for h in history if _time(h['observation_time'])==latest_time]
        valid=latest['dataset_quality']=='OBSERVED_SCOPE_VALID'
        # governance-mutation: CORE_GAPS_RESPONSE_CONFLICT
        contradictory=len({(h['request_status'],h['dataset_quality'],tuple(h['reasons']),h['response_hash']) for h in same})>1
        had_gap=any(h['dataset_quality']!='OBSERVED_SCOPE_VALID' for h in history)
        reasons=set(latest['reasons']); next_at=None
        if contradictory: status='CONFLICTING_TIME_EVIDENCE'; plan='BLOCKED_RECONCILIATION'
        elif valid: status='RECOVERED_SCOPE_OBSERVED' if had_gap else 'VALID_SCOPE_OBSERVED'; plan='NO_RECHECK_NEEDED'
        else:
            status='DATA_BLOCKED'
            if 'PERMISSION_DENIED' in reasons: plan='BLOCKED_PERMISSION'
            elif reasons & {'CALL_INTERRUPTED','CALL_RECORDING_INCOMPLETE'}: plan='BLOCKED_RECONCILIATION'
            elif len(history)>=2: plan='EXHAUSTED'
            elif reasons and reasons<={'SOURCE_DOWN','STALE','EMPTY_REQUIRED','TARGET_DATE_MISSING','DATE_OUTSIDE_REQUEST'}:
                if latest['completed_at'] is None: plan='BLOCKED_RECONCILIATION'
                else:
                    next_at=_stamp(_time(latest['completed_at'])+timedelta(minutes=15))
                    plan='PROPOSED_HUMAN_REVIEW_ONLY' if when>=_time(next_at) else 'WAIT_ELIGIBLE_TIME'
            else: plan='BLOCKED_EVIDENCE'
        row.update(status=status,recheck_status=plan,next_eligible_at=next_at,attempts_seen=len(history),max_attempts=2,
            dispatch_allowed=False,same_logical_call_replay_allowed=False,rights='UNVERIFIED',research_readiness='NOT_EVALUATED')
    return {'schema':'ar.core-gap-view.v1','head_hash':head,'observed_at':_stamp(when),
            'scopes':[scopes[k] for k in sorted(scopes)],'observation_authority':'LOCAL_RECEIPTS_NOT_PROVIDER_AUTHENTICATED',
            'outside_coverage':'NOT_INSTRUMENTED','human_review':'PENDING',**LABELS}


def coverage(root,expected_scopes,*,expected_scope_hash,expected_head,observed_at):
    _hash(expected_scope_hash)
    if type(expected_scopes) is not list or not 1<=len(expected_scopes)<=64:
        raise ValueError('GAPS_EXPECTATION_LIMIT')
    expected={}; held=[]
    for index,scope in enumerate(expected_scopes):
        if index>=64: raise ValueError('GAPS_EXPECTATION_LIMIT')
        if type(scope) is not dict or set(scope)!={'api_name','ts_code','trade_date','fields'}:
            raise ValueError('GAPS_EXPECTATION_FIELDS')
        scope=dict(scope)
        api=scope['api_name']; fields=scope['fields']; day=scope['trade_date']; symbol=scope['ts_code']
        if (type(api) is not str or api not in CORE or type(fields) is not str
                or len(fields)>128 or len(fields.split(','))!=3 or set(fields.split(','))!=CORE[api]
                or type(symbol) is not str or re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)',symbol) is None
                or type(day) is not str or re.fullmatch(r'[0-9]{8}',day) is None):
            raise ValueError('GAPS_EXPECTATION_SCOPE')
        try: datetime.strptime(day,'%Y%m%d')
        except ValueError: raise ValueError('GAPS_EXPECTATION_DATE') from None
        held.append(scope)
        scope={**scope,'fields':','.join(sorted(fields.split(',')))}
        key=ev.sealed(scope)
        if key in expected: raise ValueError('GAPS_EXPECTATION_DUPLICATE')
        expected[key]=scope
    # governance-mutation: CORE_GAPS_EXPECTATION_PIN
    if ev.sealed(held)!=expected_scope_hash:
        raise ValueError('GAPS_EXPECTATION_PIN_MISMATCH')
    observed=view(root,expected_head=expected_head,observed_at=observed_at)
    available={row['gap_id']:row for row in observed['scopes']}
    rows=[]
    # Every required scope must survive projection, including never-invoked ones.
    # governance-mutation: CORE_GAPS_EXPECTED_COVERAGE
    for key in sorted(expected):
        match=available.get(key)
        if match is None:
            rows.append({'gap_id':key,**expected[key],'status':'DATA_BLOCKED','reason':'NO_CALL_EVIDENCE',
                'history':[],'attempts_seen':0,'recheck_status':'BLOCKED_NO_OBSERVATION',
                'next_eligible_at':None,'dispatch_allowed':False,'rights':'UNVERIFIED',
                'research_readiness':'NOT_EVALUATED'})
        else: rows.append(match)
    observed_count=sum(bool(row['history']) for row in rows)
    valid=sum(row['status'] in {'VALID_SCOPE_OBSERVED','RECOVERED_SCOPE_OBSERVED'} for row in rows)
    return {'schema':'ar.core-source-coverage.v1','expectation_hash':expected_scope_hash,
        'head_hash':observed['head_hash'],'observed_at':observed['observed_at'],
        'status':'OBSERVED_SCOPE_VALID' if valid==len(expected) else 'DATA_BLOCKED',
        'counts':{'expected':len(expected),'observed':observed_count,'valid':valid,'missing':len(expected)-observed_count},
        'scopes':rows,'outside_expected_scope_count':len(set(available)-set(expected)),
        'observation_authority':observed['observation_authority'],'human_review':'PENDING',**LABELS}


def verify_retained(root):
    events,head,calls=_read(root)
    # governance-mutation: CORE_GAPS_RETAINED_HISTORY
    if not events: raise ValueError('GAPS_RETAINED_HISTORY_REQUIRED')
    return {'schema':'ar.core-gap-retained.v1','head_hash':head,'event_count':len(events),
        'source_count':len({row['evidence_hash'] for row in events}),'logical_call_count':len(calls),
        'observation_authority':'LOCAL_RECEIPTS_NOT_PROVIDER_AUTHENTICATED','human_review':'PENDING',**LABELS}


def main():
    parser=argparse.ArgumentParser(description=__doc__); commands=parser.add_subparsers(dest='command',required=True)
    inspect=commands.add_parser('evidence'); inspect.add_argument('--source',type=Path,required=True)
    add=commands.add_parser('ingest'); add.add_argument('--root',type=Path,required=True); add.add_argument('--source',type=Path,required=True)
    add.add_argument('--source-pin',required=True); add.add_argument('--head',required=True)
    show=commands.add_parser('view'); show.add_argument('--root',type=Path,required=True)
    show.add_argument('--head',required=True); show.add_argument('--observed-at',required=True)
    required=commands.add_parser('coverage'); required.add_argument('--root',type=Path,required=True)
    required.add_argument('--expectations',type=Path,required=True); required.add_argument('--scope-pin',required=True)
    required.add_argument('--head',required=True); required.add_argument('--observed-at',required=True)
    args=parser.parse_args()
    if args.command=='evidence': result=evidence(args.source)
    elif args.command=='ingest': result=ingest(args.root,args.source,expected_evidence_hash=args.source_pin,expected_head=args.head)
    elif args.command=='view': result=view(args.root,expected_head=args.head,observed_at=args.observed_at)
    else:
        source=safe_path(args.expectations)
        request=ev.parse(ev.read_local(source.parent,source.name))
        # governance-mutation: CORE_GAPS_CLI_ENVELOPE
        if set(request)!={'schema','scopes'} or request['schema']!='ar.core-source-expectations.v1':
            raise ValueError('GAPS_EXPECTATION_ENVELOPE_INVALID')
        result=coverage(args.root,request['scopes'],expected_scope_hash=args.scope_pin,
                        expected_head=args.head,observed_at=args.observed_at)
    print(ev.canonical(result))


if __name__=='__main__':
    try: main()
    except (ValueError,OSError,KeyError,TypeError):
        print('CORE_SOURCE_GAPS_REFUSED',file=sys.stderr); raise SystemExit(2)
