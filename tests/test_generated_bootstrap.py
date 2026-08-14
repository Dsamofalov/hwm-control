import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from control.generated_bootstrap import GeneratedBootstrapError, generate_bootstrap
from control.knowledge_delta_gate import validate_repository_knowledge_deltas

INFRA='a'*40
STATE_COMMIT='b'*40
PRODUCT='c'*40
CORE='d'*40

def git_blob(payload):
    return hashlib.sha1(f"blob {len(payload)}\0".encode()+payload).hexdigest()

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()

def lifecycle_known(sha,kind='baseline'):
    return {'status':'known','sha':sha,'provenance':[{'kind':kind,'repo':'Dsamofalov/hwm_predictor','sha':sha,'reference':'fixture'}]}

def state(tasks=None):
    return {
      'schema':'hwm-project-state/v2','generated_at':'2026-08-14T18:00:00Z',
      'provenance':[{'kind':'baseline','repo':'Dsamofalov/hwm-control','sha':STATE_COMMIT,'reference':'state/current.json'}],
      'product':{
        'repo':'Dsamofalov/hwm_predictor',
        'head':lifecycle_known(PRODUCT,'git_ref'),
        'last_core_green':lifecycle_known(CORE,'github_actions_run'),
        'last_full_green':{'status':'unknown','reason':'full checkpoint unavailable'},
        'last_post_merge_green':{'status':'error','error':{'code':'SOURCE_UNAVAILABLE','message':'post-merge source unavailable','retryable':True}},
        'last_live_evidenced':{'status':'unknown','reason':'live evidence not yet materialized'},
      },
      'requirements':{},
      'tasks': tasks or {'ready':[10],'claimed':[],'blocked':[]},
      'knowledge':{'status':'unknown','reason':'knowledge compiler not implemented'},
      'graph':{'status':'unknown','reason':'Graphify not implemented'},
    }

def issue(number=10,label='ready',updated='2026-08-14T18:18:25Z',milestone='I07 Generated bootstrap'):
    return {'number':number,'title':'I07: Generate minimal bootstrap from state and tasks','html_url':f'https://github.com/Dsamofalov/hwm-control/issues/{number}','updated_at':updated,'state':'open','state_reason':None,'labels':[{'name':'infrastructure'},{'name':label}],'milestone':{'title':milestone,'state':'closed'}}



def valid_delta(task_id=10):
    return {
      'schema':'hwm-knowledge-delta/v1','task_id':task_id,'goal':'Generate deterministic bootstrap.',
      'verified_facts':[{'statement':'I07 bootstrap is exact-source generated.','provenance':[{'kind':'issue','reference':'https://github.com/Dsamofalov/hwm-control/issues/10'}]}],
      'decisions':[{'decision':'Use exact deterministic inputs.','rationale':'Fail closed instead of guessing.'}],
      'rejected_alternatives':[],
      'changed_components':['control/generated_bootstrap.py'],
      'tests':[{'name':'generated bootstrap deterministic tests','status':'pass'}],
      'evidence':[],'followups':[],'unresolved':[]
    }

def knowledge_gate_fixture():
    temp=Path(tempfile.mkdtemp())
    (temp/'schemas').mkdir(); (temp/'knowledge-deltas').mkdir()
    shutil.copy2(ROOT/'schemas'/'knowledge-delta.v1.schema.json',temp/'schemas'/'knowledge-delta.v1.schema.json')
    status={'completed_task_ids':['I00','I01','I02','I06-0009'],'active_task_ids':['I07-0010']}
    (temp/'BUILD_STATUS.json').write_text(json.dumps(status),encoding='utf-8')
    for name,issue_no in [('I06-0009',9),('I07-0010',10)]:
        data=valid_delta(issue_no)
        (temp/'knowledge-deltas'/f'{name}.json').write_text(json.dumps(data),encoding='utf-8')
    return temp

def kwargs(project=None,issues=None):
    project=project or state()
    payload=canonical(project)
    return dict(
      project_state=project,
      project_state_source={'repo':'Dsamofalov/hwm-context','path':'state/current.json','commit_sha':STATE_COMMIT,'blob_sha':git_blob(payload)},
      expected_project_state_commit_sha=STATE_COMMIT,
      task_issues=issues if issues is not None else [issue()],
      expected_task_updated_at={10:'2026-08-14T18:18:25Z'} if issues is None else {i['number']:i['updated_at'] for i in issues},
      infrastructure_head=INFRA,expected_infrastructure_head=INFRA,
    )

class Tests(unittest.TestCase):
    def test_minimal_fresh_generation(self):
        out=generate_bootstrap(**kwargs())
        data=json.loads(out.json_bytes)
        self.assertEqual(set(out.files()),{'bootstrap/current.json','bootstrap/current.md'})
        self.assertEqual(data['infrastructure']['head'],INFRA)
        self.assertEqual(data['ready_tasks'][0]['issue'],10)
        self.assertEqual(data['sources']['project_state']['schema'],'hwm-project-state/v2')
        self.assertIn(b'Generated HWM infrastructure bootstrap',out.markdown_bytes)


    def test_complete_representative_task_projection(self):
        p=state({'ready':[10],'claimed':[11],'blocked':[12]})
        items=[issue(10),issue(11,label='claimed',updated='2026-08-14T18:18:26Z'),issue(12,label='blocked',updated='2026-08-14T18:18:27Z')]
        items[1]['title']='I07 claimed task'; items[2]['title']='I07 blocked task'
        k=kwargs(p,items); k['expected_task_updated_at']={item['number']:item['updated_at'] for item in items}
        data=json.loads(generate_bootstrap(**k).json_bytes)
        self.assertEqual(data['infrastructure_milestone']['tasks'],{'ready':[10],'claimed':[11],'blocked':[12]})
        self.assertEqual([item['issue'] for item in data['ready_tasks']],[10])

    def test_complete_representative_generation_preserves_unknown_error(self):
        data=json.loads(generate_bootstrap(**kwargs()).json_bytes)
        checks=data['product']['validated_checkpoints']
        self.assertEqual(checks['last_full_green']['status'],'unknown')
        self.assertEqual(checks['last_post_merge_green']['status'],'error')
        self.assertEqual(checks['last_live_evidenced']['status'],'unknown')

    def test_repeat_generation_identical(self):
        one=generate_bootstrap(**kwargs())
        two=generate_bootstrap(**kwargs())
        self.assertEqual(one.json_bytes,two.json_bytes)
        self.assertEqual(one.markdown_bytes,two.markdown_bytes)

    def test_task_input_order_does_not_change_output(self):
        p=state({'ready':[10,11],'claimed':[],'blocked':[]})
        a=issue(10); b=issue(11,updated='2026-08-14T18:18:26Z')
        b['title']='I07: second task'
        k=kwargs(p,[a,b]); k['expected_task_updated_at']={10:a['updated_at'],11:b['updated_at']}
        k2=copy.deepcopy(k); k2['task_issues']=[b,a]
        self.assertEqual(generate_bootstrap(**k).json_bytes,generate_bootstrap(**k2).json_bytes)

    def test_source_tags_and_task_binding(self):
        data=json.loads(generate_bootstrap(**kwargs()).json_bytes)
        self.assertEqual(data['sources']['infrastructure']['ref'],'refs/heads/main')
        self.assertEqual(data['sources']['tasks'][0]['state'],'ready')
        self.assertEqual(data['ready_tasks'][0]['context']['url'],'https://github.com/Dsamofalov/hwm-control/issues/10')

    def test_stale_infrastructure_head_rejected(self):
        k=kwargs(); k['expected_infrastructure_head']='f'*40
        with self.assertRaisesRegex(GeneratedBootstrapError,'stale'):
            generate_bootstrap(**k)

    def test_stale_state_commit_rejected(self):
        k=kwargs(); k['expected_project_state_commit_sha']='f'*40
        with self.assertRaisesRegex(GeneratedBootstrapError,'state source commit is stale'):
            generate_bootstrap(**k)

    def test_state_blob_mismatch_rejected(self):
        k=kwargs(); k['project_state_source']['blob_sha']='f'*40
        with self.assertRaisesRegex(GeneratedBootstrapError,'blob_sha mismatch'):
            generate_bootstrap(**k)

    def test_stale_task_revision_rejected(self):
        k=kwargs(); k['expected_task_updated_at'][10]='2026-08-14T18:00:00Z'
        with self.assertRaisesRegex(GeneratedBootstrapError,'source revision is stale'):
            generate_bootstrap(**k)

    def test_malformed_state_rejected(self):
        k=kwargs(); k['project_state']['schema']='hwm-project-state/v1'
        with self.assertRaisesRegex(GeneratedBootstrapError,'schema-invalid'):
            generate_bootstrap(**k)

    def test_missing_task_snapshot_rejected(self):
        k=kwargs(); k['task_issues']=[]
        with self.assertRaisesRegex(GeneratedBootstrapError,'missing task issue snapshots'):
            generate_bootstrap(**k)

    def test_mismatched_task_state_rejected(self):
        k=kwargs(); k['task_issues']=[issue(label='claimed')]
        with self.assertRaisesRegex(GeneratedBootstrapError,'does not match project_state'):
            generate_bootstrap(**k)

    def test_unrelated_task_rejected(self):
        k=kwargs(); extra=issue(99,updated='2026-08-14T18:19:00Z'); k['task_issues'].append(extra); k['expected_task_updated_at'][99]=extra['updated_at']
        with self.assertRaisesRegex(GeneratedBootstrapError,'revisions must cover exactly'):
            generate_bootstrap(**k)


    def test_ambiguous_project_state_source_identity_rejected(self):
        k=kwargs(); k['project_state_source']['repo']='Dsamofalov/hwm-control'
        with self.assertRaisesRegex(GeneratedBootstrapError,'state source identity is ambiguous'):
            generate_bootstrap(**k)

    def test_missing_required_state_input_rejected(self):
        k=kwargs(); del k['project_state']['product']
        with self.assertRaisesRegex(GeneratedBootstrapError,'schema-invalid'):
            generate_bootstrap(**k)

    def test_missing_project_state_provenance_rejected(self):
        k=kwargs(); k['project_state']['provenance']=[]
        with self.assertRaisesRegex(GeneratedBootstrapError,'schema-invalid'):
            generate_bootstrap(**k)

    def test_ambiguous_source_identity_rejected(self):
        k=kwargs(); k['infrastructure_ref']='main'
        with self.assertRaisesRegex(GeneratedBootstrapError,'identity is ambiguous'):
            generate_bootstrap(**k)

    def test_missing_task_provenance_rejected(self):
        k=kwargs(); del k['task_issues'][0]['updated_at']
        k['expected_task_updated_at']={10:'2026-08-14T18:18:25Z'}
        with self.assertRaisesRegex(GeneratedBootstrapError,'updated_at is missing'):
            generate_bootstrap(**k)

    def test_unknown_is_not_guessed(self):
        p=state(); p['product']['head']={'status':'unknown','reason':'product ref unavailable'}
        k=kwargs(p); k['project_state_source']['blob_sha']=git_blob(canonical(p))
        data=json.loads(generate_bootstrap(**k).json_bytes)
        self.assertEqual(data['product']['head'],{'status':'unknown','reason':'product ref unavailable'})
        self.assertNotIn('sha',data['product']['head'])

    def test_manual_volatile_override_is_not_an_input_surface(self):
        k=kwargs(); k['volatile_overrides']={'product_head':'f'*40}
        with self.assertRaises(TypeError):
            generate_bootstrap(**k)

    def test_milestone_open_closed_state_is_irrelevant(self):
        a=kwargs(); b=kwargs(); b['task_issues'][0]['milestone']['state']='open'
        self.assertEqual(generate_bootstrap(**a).json_bytes,generate_bootstrap(**b).json_bytes)

    def test_i07_canonical_knowledge_delta_passes_repository_gate(self):
        temp=knowledge_gate_fixture(); self.addCleanup(lambda: shutil.rmtree(temp,ignore_errors=True))
        self.assertEqual(validate_repository_knowledge_deltas(temp),[])

    def test_missing_i07_knowledge_delta_fails_repository_gate(self):
        temp=knowledge_gate_fixture(); self.addCleanup(lambda: shutil.rmtree(temp,ignore_errors=True))
        (temp/'knowledge-deltas'/'I07-0010.json').unlink()
        errors=validate_repository_knowledge_deltas(temp)
        self.assertTrue(any('missing required Knowledge Delta for I07-0010' in e for e in errors))

    def test_invalid_i07_knowledge_delta_fails_repository_gate(self):
        temp=knowledge_gate_fixture(); self.addCleanup(lambda: shutil.rmtree(temp,ignore_errors=True))
        (temp/'knowledge-deltas'/'I07-0010.json').write_text('{not json',encoding='utf-8')
        errors=validate_repository_knowledge_deltas(temp)
        self.assertTrue(any('invalid Knowledge Delta JSON' in e for e in errors))

if __name__=='__main__': unittest.main()
