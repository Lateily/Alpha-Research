"""Closed publication ownership and role-specific version observations; no writer."""
from pathlib import Path
import re

import workbench_evidence as ev

POLICY = {
    'schema':'ar.publication-authority.v1', 'version':'1.0',
    'sources':{
        'mac_nightly':{'artifact_role':'formal_model_snapshot','authority':'FORMAL_MODEL_PUBLICATION',
                       'pointer':'public/data/v2/current_run.json'},
        'github_legacy_review':{'artifact_role':'legacy_review_data','authority':'REVIEW_ONLY',
                                'branch':'automation/daily-market-data'},
        'shared_workbench':{'artifact_role':'isolated_task_output','authority':'ISOLATED_CONSUMER'},
        'research_candidate':{'artifact_role':'research_draft','authority':'DRAFT_ONLY'}},
    'version_roles':['main','production','shared','candidate','github_legacy'],
    'runtime_acceptance':'NOT_ATTESTED','research_authority':False,'deployment_authority':False}
SHA = re.compile(r'[0-9a-f]{40}\Z')


def validate_policy(value):
    # governance-mutation: CONTROL_PUBLICATION_POLICY
    if ev.canonical(value) != ev.canonical(POLICY):
        raise ValueError('PUBLICATION_POLICY_INVALID')
    return ev.parse(ev.canonical(value).encode())


def load_policy(path=None):
    path=Path(path) if path is not None else Path(__file__).resolve().parents[2]/'config/publication-authority.v1.json'
    try:
        if path.is_symlink(): raise ValueError
        value=ev.parse(ev.read_local(path.parent,path.name))
        return validate_policy(value)
    except (OSError,ValueError,TypeError):
        raise ValueError('PUBLICATION_POLICY_INVALID') from None


def select_publication(source_id, role, policy=None):
    policy=load_policy() if policy is None else validate_policy(policy)
    row=policy['sources'].get(source_id) if type(source_id) is str else None
    # governance-mutation: CONTROL_SOURCE_ROLE
    if row is None or row['artifact_role'] != role:
        raise ValueError('SOURCE_ROLE_REFUSED')
    return {**row,'source_id':source_id,'policy_hash':ev.sealed(policy),
            'research_authority':False,'research_readiness':'NOT_EVALUATED',
            'deployment_authority':False,'runtime_acceptance':'NOT_ATTESTED'}


def reconcile_versions(expected_versions, observations, policy=None):
    policy=load_policy() if policy is None else validate_policy(policy)
    roles=policy['version_roles']
    if (type(expected_versions) is not dict or not 1<=len(expected_versions)<=len(roles)
            or set(expected_versions)-set(roles) or type(observations) is not list
            or len(observations)>len(roles)):
        raise ValueError('VERSION_SELECTION_INVALID')
    if any(type(sha) is not str or not SHA.fullmatch(sha) for sha in expected_versions.values()):
        raise ValueError('VERSION_SHA_INVALID')
    by_role={}
    for row in observations:
        if (type(row) is not dict or set(row)!={'role','code_sha','dirty','scope'}
                or type(row['role']) is not str or row['role'] not in expected_versions
                or row['role'] in by_role or type(row['scope']) is not str
                or row['scope'] not in {'LOCAL_DIRECTORY','REMOTE_REF','CALLER_ASSERTED'}
                or row['code_sha'] is not None and (type(row['code_sha']) is not str or not SHA.fullmatch(row['code_sha']))
                or row['dirty'] is not None and type(row['dirty']) is not bool
                or row['scope']=='REMOTE_REF' and row['dirty'] is not None):
            raise ValueError('VERSION_OBSERVATION_INVALID')
        by_role[row['role']]=row
    result=[]
    for role, expected in expected_versions.items():
        row=by_role.get(role)
        # governance-mutation: CONTROL_MISSING_OBSERVATION
        if row is None: status='MISSING'
        elif row['scope']=='CALLER_ASSERTED': status='UNATTESTED'
        elif row['code_sha'] is None or row['scope']=='LOCAL_DIRECTORY' and row['dirty'] is None: status='INCOMPLETE'
        # governance-mutation: CONTROL_VERSION_DRIFT
        elif row['code_sha']!=expected: status='CODE_DRIFT'
        elif row['dirty'] is True: status='DIRTY_WORKTREE'
        else: status='MATCH_METADATA_ONLY'
        result.append({'role':role,'expected_sha':expected,'observed_sha':row['code_sha'] if row else None,
                       'scope':row['scope'] if row else None,'status':status})
    return {'schema':'ar.control-plane-reconciliation.v1','policy_hash':ev.sealed(policy),
            'status':'METADATA_MATCH_NOT_RELEASE_APPROVAL' if all(x['status']=='MATCH_METADATA_ONLY' for x in result) else 'ACTION_REQUIRED',
            'versions':result,'sources':policy['sources'],'runtime_acceptance':'NOT_ATTESTED',
            'deployment_authority':False,'research_authority':False,'production_write':False,
            'sample_purpose':'WORKFLOW_DEBUG'}
