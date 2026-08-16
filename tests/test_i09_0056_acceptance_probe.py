import base64, copy, hashlib, json, subprocess, unittest, urllib.parse, urllib.request
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from control import task_context_compiler as tc

CONTROL="Dsamofalov/hwm-control"; CONTEXT="Dsamofalov/hwm-context"; PRODUCT="Dsamofalov/hwm_predictor"
CH="dd1edde8de42f620faa4e3a2d88f870bedaa0678"; XH="202bbf5875dcd429d856c8d13d3946e4fee1329f"; PH="8fd669336b36064e842252d69fb4016cc526a9d4"
COMP="37ea465cf5a81e63fb0840846bb6dfcb5ecdcc97"; CORE="ef80519a4cefb0e2a278d0247f6fd80230a04eed"; RS="c94d7caa0306799231ec276be2107db3c04946ea"; PS="e17296906dbf4a0717a02fc4be8be197ac977e15"
def cj(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def h(b): return hashlib.sha256(b).hexdigest()
def gb(b): return hashlib.sha1(f"blob {len(b)}\0".encode()+b).hexdigest()
class P:
 def get(self,u):
  q=urllib.request.Request(u,method="GET"); q.add_header("Accept","application/vnd.github+json"); q.add_header("X-GitHub-Api-Version","2022-11-28")
  with urllib.request.urlopen(q,timeout=30) as r:return json.loads(r.read())
 def u(self,r,s): assert r in {CONTROL,CONTEXT,PRODUCT}; return f"https://api.github.com/repos/{r}{s}"
 def observe_head(self,r): return self.get(self.u(r,"/git/ref/heads/main"))["object"]["sha"]
 def fetch_issue(self,r,n):
  assert (r,n)==(CONTROL,56); o=self.get(self.u(r,f"/issues/{n}")); return {"title":o["title"],"body":o.get("body") or "","updated_at":o["updated_at"],"state":o["state"],"state_reason":o.get("state_reason"),"labels":[x["name"] for x in o.get("labels",[])],"assignees":[x["login"] for x in o.get("assignees",[])],"milestone_number":(o.get("milestone") or {}).get("number")}
 def fetch_blob(self,r,c,p):
  o=self.get(self.u(r,f"/contents/{urllib.parse.quote(p,safe='/')}?ref={c}")); b=base64.b64decode(o["content"]); assert o["sha"]==gb(b); return tc.ExactBlob(b,o["sha"])
def bind(p,r,c,path):
 b=p.fetch_blob(r,c,path); return {"path":path,"blob_sha":b.blob_sha,"content_sha256":h(b.content)}
class Probe(unittest.TestCase):
 def test_probe(self):
  root=Path(__file__).resolve().parents[1]
  for path,sha in {"control/task_context_compiler.py":COMP,"control/task_context_core.py":CORE,"schemas/task-context-request.v1.schema.json":RS,"schemas/task-context-pack.v1.schema.json":PS}.items(): self.assertEqual(subprocess.check_output(["git","-C",str(root),"hash-object","--",path],text=True).strip(),sha)
  p=P(); self.assertEqual((p.observe_head(CONTROL),p.observe_head(CONTEXT),p.observe_head(PRODUCT)),(CH,XH,PH))
  issue=tc._derive_issue_snapshot(p.fetch_issue(CONTROL,56),CONTROL,56)
  state=bind(p,CONTROL,CH,"state/current.json"); claims=bind(p,CONTEXT,XH,"claims/claims.jsonl"); conflicts=bind(p,CONTEXT,XH,"claims/conflicts.json"); kd=bind(p,CONTROL,CH,"knowledge-deltas/I09-0056.json"); spec=bind(p,PRODUCT,PH,"SPEC.md")
  req={"schema":"hwm-task-context-request/v1","request_id":"tcr1-"+"0"*64,"task":{"task_key":"I09-0056","issue_repository":CONTROL,"issue_number":56},"issue_snapshot":issue,"product":{"repository":PRODUCT,"commit":PH,"head_policy":"must_equal_current","expected_current_head":PH},"project_state":{"schema":"hwm-project-state/v2","repository":CONTROL,"commit":CH,**state},"historical_ledger":{"repository":CONTEXT,"commit":XH,"head_policy":"must_equal_current","claims":claims,"conflicts":conflicts},"knowledge_deltas":{"set_mode":"explicit_exact_set","inputs":[{"task_key":"I09-0056","task_id":56,"repository":CONTROL,"commit":CH,**kd}]},"product_sources":{"set_mode":"explicit_exact_set","inputs":[{"source_id":"product.spec.large-public-acceptance","media_type":"text/markdown","priority":0,"required":True,"truncation_allowed":False,**spec}]},"selection":{"algorithm":"hwm-task-context-selection/v1","authority_order":tc.AUTHORITY_ORDER,"ranking_keys":["required_desc","authority_order","priority_asc","source_id_asc"],"tie_break":"source_id_lexicographic","dedup_identity":"authority_class+media_type+content_sha256","budget_metric":"utf8_content_bytes","overflow_rule":"greedy_ranked_utf8_prefix","budgets":{"total_content_bytes":10000000,"per_source_max_bytes":2000000,"per_authority_bytes":{"authoritative_current_state":10000000,"authoritative_git_github_ci":10000000,"product_source":10000000,"knowledge_delta":10000000,"historical_ledger":10000000}}},"freshness":{"policy":"hwm-exact-bound-freshness/v1","control_main_sha":CH,"context_main_sha":XH,"issue_snapshot_sha256":issue["snapshot_sha256"],"project_state_commit":CH,"historical_ledger_commit":XH,"on_mismatch":"reject","no_implicit_head_substitution":True},"public_data":{"policy":"hwm-public-data/v1","classification":"public-disclosure-safe","forbidden_categories":["api_secrets_tokens","cookies","browser_profiles","account_credentials","private_keys","session_state","personal_data","sensitive_raw_evidence","secret_bearing_environment_or_config"],"on_violation":"reject"}}
  req["request_id"]=tc.expected_request_id(req); tc.validate_request(req); a=tc.compile_task_context(copy.deepcopy(req),p).context_json; b=tc.compile_task_context(copy.deepcopy(req),p).context_json; self.assertEqual(a,b); self.assertGreater(len(a),100000)
  rsha=tc.request_digest(req); csha=h(a); bsha=gb(a); sid=h(cj({"purpose":"i09-0056-large-public-acceptance-v3","source_request_id":req["request_id"],"source_request_sha256":rsha,"context_sha256":csha,"git_blob_sha":bsha}).encode())
  stage={"schema":"hwm-task-context-stage-request/v1","request_id":"tcs1-"+sid,"repository":CONTEXT,"transport_issue":27,"expected_control_main":CH,"expected_context_main":XH,"expected_product_main":PH,"source_request":req,"expectations":{"source_request_id":req["request_id"],"source_request_sha256":rsha,"context_sha256":csha,"git_blob_sha":bsha},"compiler":{"repository":CONTROL,"commit":CH,"module":"control.task_context_compiler","callable":"compile_task_context","compiler_path":"control/task_context_compiler.py","compiler_blob_sha":COMP,"core_path":"control/task_context_core.py","core_blob_sha":CORE,"request_schema_path":"schemas/task-context-request.v1.schema.json","request_schema_blob_sha":RS,"pack_schema_path":"schemas/task-context-pack.v1.schema.json","pack_schema_blob_sha":PS,"serialization_profile":"hwm-canonical-json/v1","pack_schema":"hwm-task-context-pack/v1","max_blob_bytes":4194304}}
  ss=json.loads((root/"schemas/task-context-stage-request.v1.schema.json").read_text()); sr=json.loads((root/"schemas/task-context-request.v1.schema.json").read_text()); reg=Registry().with_resource(sr["$id"],Resource.from_contents(sr)); Draft202012Validator(ss,registry=reg).validate(stage)
  print("I09_0056_STAGE_REQUEST="+cj(stage)); print("I09_0056_SOURCE_REQUEST_ID="+req["request_id"]); print("I09_0056_SOURCE_REQUEST_SHA256="+rsha); print("I09_0056_CONTEXT_SHA256="+csha); print("I09_0056_GIT_BLOB_SHA="+bsha); print("I09_0056_CONTEXT_BYTES="+str(len(a)))
if __name__=="__main__":unittest.main()
