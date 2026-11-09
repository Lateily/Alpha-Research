"""Frozen content/basis review tasks; shared outputs contain metadata only."""
from collections import Counter
from pathlib import Path
import os
import uuid

import foundation_materials as materials
import foundation_results as results
import research_basis_evidence as basis
import research_content as content
import workbench_evidence as ev
import workbench_shared_material as material
from foundation_local_store import _destination,_reserve,_copy,_inventory
from workbench_backup import durable_directory,fsync_directory,write_new

SCHEMA='ar.shared-research-card-input.v1'
KIND='research-cards-review'
SCOPE=material.SCOPE
LABELS={**content.LABELS,'content_sharing_allowed':False,'content_status':'RIGHTS_UNVERIFIED_CONTENT_DENIED'}
METADATA=('company','research_date','source_cutoff_at','artifact_generated_at','industry_key',
          'industry_taxonomy','taxonomy_version','pack_hash','content_hash','basis_hash')
PROJECTION=('content_producer','basis_producer','citation_locations','cards')

def _files(roots):
    files={}; size=0
    for prefix,root in roots.items():
        for name,raw in results._tree(root).items():
            size+=len(raw)
            # governance-mutation: SHARED_CARDS_INPUT_BOUND
            if len(files)>=512 or size>256*1024*1024: raise ValueError('SHARED_CARDS_INPUT_LIMIT')
            files[prefix+'/'+name]=ev.sha(raw)
    return files

def _file(root,marker,pin,name,pin_key):
    manifest=ev.parse(ev.read_local(root,marker))
    if manifest.get(pin_key)!=pin or ev.sealed({k:v for k,v in manifest.items() if k!=pin_key})!=pin:
        raise ValueError('SHARED_CARDS_MANIFEST_PIN')
    raw=ev.read_local(root,name)
    if ev.sha(raw)!=manifest['files'].get(name): raise ValueError('SHARED_CARDS_FILE_PIN')
    return ev.parse(raw),manifest['execution_identity']

def _projection(content_root,basis_root,content_hash,basis_hash):
    cards,producer=_file(content_root,'content-manifest.json',content_hash,'cards.json','content_hash')
    financial,basis_producer=_file(basis_root,basis.MARKER,basis_hash,'basis-card.json','basis_hash')
    facts=cards['facts']; daily=financial['daily']; cash=financial['cash']; multiple=financial['multiple']
    if daily.get('eligible') is not False: raise ValueError('SHARED_CARDS_UNREVIEWED_ELIGIBILITY')
    locations=[{'fact_id':row['id'],**{key:row['citation'][key] for key in ('sha256','page','start','end')}}
        for row in facts['observations']]
    assessments=dict(sorted(Counter(row['assessment'] for row in facts['responses']).items()))
    return {'content_producer':producer,'basis_producer':basis_producer,
        'citation_locations':locations,'cards':{
        'facts':{'status':facts['status'],'observation_count':len(facts['observations']),
            'calculation_count':len(facts['calculations']),'assessment_counts':assessments},
        'valuation':{'status':financial['status'],
            'normalized_eps_status':'NOT_ESTABLISHED' if financial['normalized_eps'] is None else 'UNREVIEWED_VALUE_PRESENT',
            'value_band_status':'NOT_ESTABLISHED' if financial['value_band'] is None else 'UNREVIEWED_VALUE_PRESENT',
            'cash_status':cash['status'],'net_cash_status':'NOT_ESTABLISHED' if cash['net_cash_per_share'] is None else 'UNREVIEWED_VALUE_PRESENT',
            'missing_cash_components':cash['missing_components'],
            'fair_multiple_status':'NOT_ESTABLISHED' if multiple['fair_multiple_low'] is None or multiple['fair_multiple_high'] is None else 'UNREVIEWED_VALUE_PRESENT',
            'missing_normalization_assumptions':financial['normalization']['scenario']['missing_assumptions']},
        'daily':{'status':daily['status'],'eligible':False,'reason_codes':daily.get('reason_codes',[]),
            'continuity_status':daily.get('continuity_status','NOT_RECORDED'),
            'vintage_status':daily.get('vintage',{}).get('status','NOT_RECORDED'),
            'source_trade_date':cards['technical'].get('source_trade_date')},
        'execution_feedback':{'status':cards['execution_feedback']['status'],
            'pnl_status':'NOT_SUPPLIED' if cards['execution_feedback']['pnl'] is None else 'LOCAL_EVIDENCE_NOT_HUMAN_VERIFIED'}}}

def snapshot(library_root,pack_root,content_root,basis_root,*,expected_library_hash,
             expected_pack_hash,expected_content_hash,expected_basis_hash):
    base=material.snapshot(library_root,pack_root,expected_library_hash=expected_library_hash,
        expected_pack_hash=expected_pack_hash)
    content.verify(content_root,expected_content_hash,pack_root,expected_pack_hash)
    basis.verify(basis_root,expected_basis_hash,content_root,expected_content_hash,pack_root,expected_pack_hash)
    roots={'library':Path(library_root),'pack':Path(pack_root),'content':Path(content_root),'basis':Path(basis_root)}
    files=_files(roots)
    projection=_projection(Path(content_root),Path(basis_root),expected_content_hash,expected_basis_hash)
    cards,_=_file(Path(content_root),'content-manifest.json',expected_content_hash,'cards.json','content_hash')
    source_map=ev.parse(ev.read_local(pack_root,'source-map.json'))
    classes={tuple(row['material'][key] for key in ('industry_key','industry_taxonomy','taxonomy_version'))
             for row in source_map['documents']}
    classification=next(iter(classes)) if len(classes)==1 else ('UNSPECIFIED',)*3
    value={'schema':'ar.shared-research-card-snapshot.v1','company':base['company'],
        'research_date':cards['research_date'],'source_cutoff_at':base['source_cutoff_at'],
        'artifact_generated_at':cards['generated_at'],
        **dict(zip(('industry_key','industry_taxonomy','taxonomy_version'),classification)),
        'classification_status':'SOURCE_METADATA_NOT_RECLASSIFIED' if len(classes)==1 else 'CONFLICTING_SOURCE_CLASSIFICATION',
        'library_hash':expected_library_hash,'pack_hash':expected_pack_hash,
        'content_hash':expected_content_hash,'basis_hash':expected_basis_hash,'files':files,
        'projection_hash':ev.sealed(projection),**LABELS}
    if _files(roots)!=files:
        raise ValueError('SHARED_CARDS_SOURCE_CHANGED')
    value['frozen_input_hash']=ev.sealed(value)
    return value

def envelope(value):
    keys={'schema','company','research_date','source_cutoff_at','artifact_generated_at','industry_key',
        'industry_taxonomy','taxonomy_version','classification_status','library_hash','pack_hash','content_hash',
        'basis_hash','files','projection_hash','frozen_input_hash',*LABELS}
    materials._exact(value,keys)
    if (value['schema']!='ar.shared-research-card-snapshot.v1'
            or value['frozen_input_hash']!=ev.sealed({k:v for k,v in value.items() if k!='frozen_input_hash'})
            or any(type(value[k]) is not type(v) or value[k]!=v for k,v in LABELS.items())):
        raise ValueError('SHARED_CARDS_ENVELOPE_INVALID')
    for key in ('library_hash','pack_hash','content_hash','basis_hash','projection_hash','frozen_input_hash'): materials._hash(value[key])
    materials._ticker(value['company']); materials._date(value['research_date'])
    checksum=value['frozen_input_hash']
    return {'schema':SCHEMA,'snapshot_id':str(uuid.uuid5(uuid.NAMESPACE_URL,SCHEMA+':'+checksum)),
        'input_hash':checksum,'publication_fingerprint':value['basis_hash'],
        'attempt_fingerprint':value['content_hash'],'source_run_id':None,'source_trade_date':None,
        'validation_scope':SCOPE,'snapshot':value}

def verify_input(root,value):
    envelope(value); root=Path(root)
    # governance-mutation: SHARED_CARDS_INVENTORY
    if {name:ev.sha(raw) for name,raw in results._tree(root).items()}!=value['files']:
        raise ValueError('SHARED_CARDS_INVENTORY_CONFLICT')
    actual=snapshot(*(root/name for name in ('library','pack','content','basis')),
        expected_library_hash=value['library_hash'],expected_pack_hash=value['pack_hash'],
        expected_content_hash=value['content_hash'],expected_basis_hash=value['basis_hash'])
    if actual!=value: raise ValueError('SHARED_CARDS_BINDING_CONFLICT')
    return value

def copy_input(library,pack,content_root,basis_root,target,value):
    sources=[library,pack,content_root,basis_root]; target=_destination(target,sources); _reserve(target)
    for name,path in zip(('library','pack','content','basis'),sources): _copy(path,target/name,_inventory(Path(path)))
    verify_input(target,value)
    # governance-mutation: SHARED_CARDS_COPY_SOURCE
    if snapshot(*sources,expected_library_hash=value['library_hash'],expected_pack_hash=value['pack_hash'],
            expected_content_hash=value['content_hash'],expected_basis_hash=value['basis_hash'])!=value:
        raise ValueError('SHARED_CARDS_SOURCE_CHANGED')

def register(inputs,library,pack,content_root,basis_root,*,expected_library_hash,
             expected_pack_hash,expected_content_hash,expected_basis_hash):
    for path in (library,pack,content_root,basis_root): inputs.check_source_root(path)
    value=snapshot(library,pack,content_root,basis_root,expected_library_hash=expected_library_hash,
        expected_pack_hash=expected_pack_hash,expected_content_hash=expected_content_hash,expected_basis_hash=expected_basis_hash)
    entry=envelope(value); sid=entry['snapshot_id']
    from workbench_shared_inputs import _new_or_identical
    with inputs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT input_hash,body FROM shared_inputs WHERE snapshot_id=?',(sid,)).fetchone()
        if prior: return inputs._descriptor(inputs.verify_registered(inputs.base,sid,prior))
        inputs._capacity(db,entry['input_hash'],entry['publication_fingerprint'],entry['attempt_fingerprint'])
        target=inputs.base/'material-packs'/entry['input_hash']; durable_directory(target.parent)
        work=inputs.store.path.parent/'input-write-evidence'/entry['input_hash']; durable_directory(work)
        _new_or_identical(work/'material-intent.json',ev.canonical(entry).encode(),evidence_root=work/'writes')
        if target.exists(): verify_input(target,value)
        else:
            attempts=list(work.glob('material-attempt-*'))
            if len(attempts)>=3: raise ValueError('SHARED_CARDS_REGISTRATION_RECOVERY_REQUIRED')
            staging=work/('material-attempt-'+uuid.uuid4().hex)
            copy_input(library,pack,content_root,basis_root,staging,value)
            os.rename(staging,target); fsync_directory(target.parent); fsync_directory(work)
        _new_or_identical(inputs.base/'envelopes'/(sid+'.json'),ev.canonical(entry).encode(),evidence_root=work/'writes')
        db.execute('INSERT INTO shared_inputs VALUES (?,?,?)',(sid,entry['input_hash'],ev.canonical(entry)))
    return inputs._descriptor(inputs.verify(sid))

def render(root,output,value):
    root=Path(root); output=Path(output); verify_input(root,value)
    projection=_projection(root/'content',root/'basis',value['content_hash'],value['basis_hash'])
    result={'schema':'ar.research-card-review.v1','input_hash':value['frozen_input_hash'],
        **{k:value[k] for k in METADATA},
        **projection,**LABELS}
    raw=ev.canonical(result).encode()
    archive={'schema':'ar.research-card-archive.v1','result_hash':ev.sha(raw),
        'input_hash':value['frozen_input_hash'],'files':{'review.json':ev.sha(raw)},**LABELS}
    archive['archive_hash']=ev.sealed(archive)
    _reserve(output); write_new(output/'review.json',raw)
    verify_input(root,value)
    write_new(output/'archive.json',ev.canonical(archive).encode())
    verify_output(output,value)

def verify_output(output,value):
    envelope(value); files=results._tree(Path(output))
    if set(files)!={'review.json','archive.json'}: raise ValueError('SHARED_CARDS_OUTPUT_FILES')
    archive=ev.parse(files['archive.json']); review=ev.parse(files['review.json'])
    materials._exact(archive,{'schema','result_hash','input_hash','files','archive_hash',*LABELS})
    materials._exact(review,{'schema','input_hash',*METADATA,*PROJECTION,*LABELS})
    # governance-mutation: SHARED_CARDS_OUTPUT_PIN
    if (archive['schema']!='ar.research-card-archive.v1' or review['schema']!='ar.research-card-review.v1'
            or archive.get('archive_hash')!=ev.sealed({k:v for k,v in archive.items() if k!='archive_hash'})
            or archive.get('files')!={'review.json':ev.sha(files['review.json'])}
            or archive.get('result_hash')!=ev.sha(files['review.json'])
            or archive.get('input_hash')!=value['frozen_input_hash']
            or review.get('input_hash')!=value['frozen_input_hash']
            or any(review[k]!=value[k] for k in METADATA)
            or ev.sealed({k:review[k] for k in PROJECTION})!=value['projection_hash']
            or any(type(item.get(k)) is not type(v) or item.get(k)!=v for item in (archive,review) for k,v in LABELS.items())):
        raise ValueError('SHARED_CARDS_OUTPUT_CONFLICT')
    return {'status':'SUCCEEDED','output_hash':archive['archive_hash'],'report_sha256':ev.sha(files['review.json']),
        'archive_library_hash':archive['archive_hash'],'archive_status':'ARCHIVED',
        'human_review':'PENDING','content_sharing_allowed':False}

def detail(output,value,frozen_root):
    checked=verify_output(output,value); verify_input(frozen_root,value)
    review=ev.parse(ev.read_local(output,'review.json'))
    expected=_projection(Path(frozen_root)/'content',Path(frozen_root)/'basis',value['content_hash'],value['basis_hash'])
    # governance-mutation: SHARED_CARDS_DERIVATION
    if any(review.get(key)!=item for key,item in expected.items()): raise ValueError('SHARED_CARDS_DERIVATION')
    return {**checked,**{k:value[k] for k in ('company','research_date','source_cutoff_at','artifact_generated_at',
        'industry_key','industry_taxonomy','taxonomy_version','content_hash','basis_hash','pack_hash')},
        **expected,'steps':['REGISTERED_INPUT_VERIFIED','CONTENT_RECOMPUTED','BASIS_RECOMPUTED','METADATA_ARCHIVED','OUTPUT_SEALED'],
        'content_status':LABELS['content_status'],'sample_purpose':'WORKFLOW_DEBUG'}
