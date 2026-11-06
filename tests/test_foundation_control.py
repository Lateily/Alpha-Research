"""Publication ownership and distinct role-version decisions, zero providers."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/llm'))


class ControlTests(unittest.TestCase):
    def request(self):
        return {'expected_versions': {'main':'a'*40, 'production':'b'*40, 'shared':'c'*40},
                'observations': [
                    {'role':'main','code_sha':'a'*40,'dirty':None,'scope':'REMOTE_REF'},
                    {'role':'production','code_sha':'b'*40,'dirty':False,'scope':'LOCAL_DIRECTORY'},
                    {'role':'shared','code_sha':'c'*40,'dirty':False,'scope':'LOCAL_DIRECTORY'}]}

    def test_real_cli_keeps_different_expected_versions_without_claiming_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp).resolve()/'request.json'; path.write_text(json.dumps(self.request()))
            result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/llm/foundation_cli.py'),
                                   'control','--request',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)['result']
        self.assertEqual([r['status'] for r in value['versions']], ['MATCH_METADATA_ONLY']*3)
        self.assertFalse(value['deployment_authority'])
        self.assertEqual(value['runtime_acceptance'],'NOT_ATTESTED')

    def module(self):
        import foundation_control
        return foundation_control

    def test_only_mac_nightly_can_supply_formal_snapshot(self):
        c=self.module()
        self.assertEqual(c.select_publication('mac_nightly','formal_model_snapshot')['pointer'],
                         'public/data/v2/current_run.json')
        for source in ('github_legacy_review','shared_workbench','research_candidate','unknown'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError,'SOURCE_ROLE_REFUSED'):
                c.select_publication(source,'formal_model_snapshot')

    def test_legacy_is_readable_as_review_only_and_not_a_quality_pass(self):
        c=self.module(); row=c.select_publication('github_legacy_review','legacy_review_data')
        self.assertEqual(row['authority'],'REVIEW_ONLY')
        self.assertEqual(row['branch'],'automation/daily-market-data')
        self.assertFalse(row['research_authority'])
        self.assertEqual(row['research_readiness'],'NOT_EVALUATED')

    def test_resealed_policy_cannot_promote_review_or_change_pointer(self):
        c=self.module()
        for key, value in (('authority','FORMAL_MODEL_PUBLICATION'),('artifact_role','formal_model_snapshot')):
            policy=c.load_policy(); policy['sources']['github_legacy_review'][key]=value
            with self.assertRaisesRegex(ValueError,'PUBLICATION_POLICY_INVALID'):
                c.select_publication('github_legacy_review','formal_model_snapshot',policy)
        policy=c.load_policy(); policy['sources']['mac_nightly']['pointer']='public/data/meta.json'
        with self.assertRaisesRegex(ValueError,'PUBLICATION_POLICY_INVALID'):
            c.select_publication('mac_nightly','formal_model_snapshot',policy)

    def test_drift_missing_and_unknown_do_not_disappear_behind_other_matches(self):
        c=self.module(); value=self.request(); value['observations'][1]['code_sha']='d'*40
        value['observations'].pop()
        result=c.reconcile_versions(**value)
        self.assertEqual([r['status'] for r in result['versions']],['MATCH_METADATA_ONLY','CODE_DRIFT','MISSING'])
        self.assertEqual(result['status'],'ACTION_REQUIRED')
        value['observations'][1]['scope']='CALLER_ASSERTED'
        self.assertEqual(c.reconcile_versions(**value)['versions'][1]['status'],'UNATTESTED')

    def test_dirty_and_incomplete_directory_evidence_never_match(self):
        c=self.module()
        for dirty, expected in ((True,'DIRTY_WORKTREE'),(None,'INCOMPLETE')):
            value=self.request(); value['observations'][1]['dirty']=dirty
            self.assertEqual(c.reconcile_versions(**value)['versions'][1]['status'],expected)

    def test_closed_roles_types_and_duplicate_observations(self):
        c=self.module()
        values=[]
        x=self.request(); x['observations'].append(copy.deepcopy(x['observations'][0])); values.append(x)
        x=self.request(); x['observations'][0]['role']='arbitrary'; values.append(x)
        x=self.request(); x['observations'][1]['dirty']=0; values.append(x)
        x=self.request(); x['observations'][0]['code_sha']='not-a-sha'; values.append(x)
        x=self.request(); x['observations'][0]['extra']='approve'; values.append(x)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError): c.reconcile_versions(**value)

    def test_legacy_schema_is_not_silently_reinterpreted_as_new_evidence(self):
        value=self.request(); value['observations'][0]={'role':'main','sha':'a'*40,'status':'PASS'}
        with self.assertRaises(ValueError): self.module().reconcile_versions(**value)

    def test_policy_file_refuses_duplicates_symlinks_and_extras(self):
        c=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'p.json'; original=c.load_policy()
            path.write_text(json.dumps(original)); link=root/'link'; link.symlink_to(path)
            with self.assertRaises(ValueError): c.load_policy(link)
            path.write_text('{"schema":"a","schema":"b"}')
            with self.assertRaises(ValueError): c.load_policy(path)
            original['deployment_authority']=True; path.write_text(json.dumps(original))
            with self.assertRaises(ValueError): c.load_policy(path)


if __name__=='__main__': unittest.main()
