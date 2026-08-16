import base64
import copy
import hashlib
import json
import subprocess
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

from control import task_context_compiler as tc

CONTROL = "Dsamofalov/hwm-control"
CONTEXT = "Dsamofalov/hwm-context"
PRODUCT = "Dsamofalov/hwm_predictor"
ISSUE = 56
TASK_KEY = "I09-0056"
TRANSPORT_ISSUE = 27
SPEC_PATH = "SPEC.md"
KD_PATH = "knowledge-deltas/I09-0056.json"

COMPILER_BLOBS = {
    "compiler_blob_sha": "37ea465cf5a81e63fb0840846bb6dfcb5ecdcc97",
    "core_blob_sha": "ef80519a4cefb0e2a278d0247f6fd80230a04eed",
    "request_schema_blob_sha": "c94d7caa0306799231ec276be2107db3c04946ea",
    "pack_schema_blob_sha": "e17296906dbf4a0717a02fc4be8be197ac977e15",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


class PublicProvider:
    api = "https://api.github.com"

    def get(self, url):
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def repo_url(self, repository, suffix):
        if repository not in {CONTROL, CONTEXT, PRODUCT}:
            raise AssertionError(repository)
        return f"{self.api}/repos/{repository}{suffix}"

    def observe_head(self, repository):
        obj = self.get(self.repo_url(repository, "/git/ref/heads/main"))
        return obj["object"]["sha"]

    def fetch_issue(self, repository, issue_number):
        if repository != CONTROL or issue_number != ISSUE:
            raise AssertionError((repository, issue_number))
        obj = self.get(self.repo_url(repository, f"/issues/{issue_number}"))
        return {
            "title": obj["title"],
            "body": obj.get("body") or "",
            "updated_at": obj["updated_at"],
            "state": obj["state"],
            "state_reason": obj.get("state_reason"),
            "labels": [x["name"] for x in obj.get("labels", [])],
            "assignees": [x["login"] for x in obj.get("assignees", [])],
            "milestone_number": (obj.get("milestone") or {}).get("number"),
        }

    def fetch_blob(self, repository, commit, path):
        path_q = urllib.parse.quote(path, safe="/")
        ref_q = urllib.parse.quote(commit, safe="")
        obj = self.get(self.repo_url(repository, f"/contents/{path_q}?ref={ref_q}"))
        if obj.get("type") != "file" or obj.get("encoding") != "base64":
            raise AssertionError((repository, commit, path, obj.get("type"), obj.get("encoding")))
        data = base64.b64decode(obj["content"], validate=False)
        if obj["sha"] != git_blob_sha(data):
            raise AssertionError("GitHub blob identity mismatch")
        return tc.ExactBlob(data, obj["sha"])


def binding(provider, repository, commit, path):
    blob = provider.fetch_blob(repository, commit, path)
    return blob, {"path": path, "blob_sha": blob.blob_sha, "content_sha256": sha256(blob.content)}


class I090056LargePackAcceptanceProbe(unittest.TestCase):
    def test_emit_small_stage_request_for_large_public_pack(self):
        root = Path(__file__).resolve().parents[1]
        expected_local = {
            "control/task_context_compiler.py": COMPILER_BLOBS["compiler_blob_sha"],
            "control/task_context_core.py": COMPILER_BLOBS["core_blob_sha"],
            "schemas/task-context-request.v1.schema.json": COMPILER_BLOBS["request_schema_blob_sha"],
            "schemas/task-context-pack.v1.schema.json": COMPILER_BLOBS["pack_schema_blob_sha"],
        }
        for path, expected in expected_local.items():
            actual = subprocess.check_output(["git", "-C", str(root), "hash-object", "--", path], text=True).strip()
            self.assertEqual(actual, expected)

        provider = PublicProvider()
        control_head = provider.observe_head(CONTROL)
        context_head = provider.observe_head(CONTEXT)
        product_head = provider.observe_head(PRODUCT)
        self.assertEqual(control_head, "71ddad3c8882d154bc013bf06a41f4d94309ec78")
        self.assertEqual(context_head, "202bbf5875dcd429d856c8d13d3946e4fee1329f")
        self.assertEqual(product_head, "8fd669336b36064e842252d69fb4016cc526a9d4")

        raw_issue = provider.fetch_issue(CONTROL, ISSUE)
        issue_snapshot = tc._derive_issue_snapshot(raw_issue, CONTROL, ISSUE)

        _, state = binding(provider, CONTROL, control_head, "state/current.json")
        _, claims = binding(provider, CONTEXT, context_head, "claims/claims.jsonl")
        _, conflicts = binding(provider, CONTEXT, context_head, "claims/conflicts.json")
        _, kd = binding(provider, CONTROL, control_head, KD_PATH)
        _, spec = binding(provider, PRODUCT, product_head, SPEC_PATH)

        request = {
            "schema": "hwm-task-context-request/v1",
            "request_id": "tcr1-" + "0" * 64,
            "task": {"task_key": TASK_KEY, "issue_repository": CONTROL, "issue_number": ISSUE},
            "issue_snapshot": issue_snapshot,
            "product": {
                "repository": PRODUCT,
                "commit": product_head,
                "head_policy": "must_equal_current",
                "expected_current_head": product_head,
            },
            "project_state": {
                "schema": "hwm-project-state/v2",
                "repository": CONTROL,
                "commit": control_head,
                **state,
            },
            "historical_ledger": {
                "repository": CONTEXT,
                "commit": context_head,
                "head_policy": "must_equal_current",
                "claims": claims,
                "conflicts": conflicts,
            },
            "knowledge_deltas": {
                "set_mode": "explicit_exact_set",
                "inputs": [{
                    "task_key": TASK_KEY,
                    "task_id": ISSUE,
                    "repository": CONTROL,
                    "commit": control_head,
                    **kd,
                }],
            },
            "product_sources": {
                "set_mode": "explicit_exact_set",
                "inputs": [{
                    "source_id": "product.spec.large-public-acceptance",
                    **spec,
                    "media_type": "text/markdown",
                    "priority": 0,
                    "required": True,
                    "truncation_allowed": False,
                }],
            },
            "selection": {
                "algorithm": "hwm-task-context-selection/v1",
                "authority_order": tc.AUTHORITY_ORDER,
                "ranking_keys": ["required_desc", "authority_order", "priority_asc", "source_id_asc"],
                "tie_break": "source_id_lexicographic",
                "dedup_identity": "authority_class+media_type+content_sha256",
                "budget_metric": "utf8_content_bytes",
                "overflow_rule": "greedy_ranked_utf8_prefix",
                "budgets": {
                    "total_content_bytes": 10000000,
                    "per_source_max_bytes": 2000000,
                    "per_authority_bytes": {
                        "authoritative_current_state": 10000000,
                        "authoritative_git_github_ci": 10000000,
                        "product_source": 10000000,
                        "knowledge_delta": 10000000,
                        "historical_ledger": 10000000,
                    },
                },
            },
            "freshness": {
                "policy": "hwm-exact-bound-freshness/v1",
                "control_main_sha": control_head,
                "context_main_sha": context_head,
                "issue_snapshot_sha256": issue_snapshot["snapshot_sha256"],
                "project_state_commit": control_head,
                "historical_ledger_commit": context_head,
                "on_mismatch": "reject",
                "no_implicit_head_substitution": True,
            },
            "public_data": {
                "policy": "hwm-public-data/v1",
                "classification": "public-disclosure-safe",
                "forbidden_categories": [
                    "api_secrets_tokens",
                    "cookies",
                    "browser_profiles",
                    "account_credentials",
                    "private_keys",
                    "session_state",
                    "personal_data",
                    "sensitive_raw_evidence",
                    "secret_bearing_environment_or_config",
                ],
                "on_violation": "reject",
            },
        }
        request["request_id"] = tc.expected_request_id(request)
        tc.validate_request(request)

        first = tc.compile_task_context(copy.deepcopy(request), provider).context_json
        second = tc.compile_task_context(copy.deepcopy(request), provider).context_json
        self.assertEqual(first, second)
        self.assertGreater(len(first), 100000)

        context_sha = sha256(first)
        blob_sha = git_blob_sha(first)
        request_sha = tc.request_digest(request)
        stage_identity = sha256(canonical({
            "purpose": "i09-0056-large-public-acceptance-v2",
            "source_request_id": request["request_id"],
            "source_request_sha256": request_sha,
            "context_sha256": context_sha,
            "git_blob_sha": blob_sha,
        }).encode("utf-8"))
        stage_request = {
            "schema": "hwm-task-context-stage-request/v1",
            "request_id": "tcs1-" + stage_identity,
            "repository": CONTEXT,
            "transport_issue": TRANSPORT_ISSUE,
            "expected_control_main": control_head,
            "expected_context_main": context_head,
            "expected_product_main": product_head,
            "source_request": request,
            "expectations": {
                "source_request_id": request["request_id"],
                "source_request_sha256": request_sha,
                "context_sha256": context_sha,
                "git_blob_sha": blob_sha,
            },
            "compiler": {
                "repository": CONTROL,
                "commit": control_head,
                "module": "control.task_context_compiler",
                "callable": "compile_task_context",
                "compiler_path": "control/task_context_compiler.py",
                "compiler_blob_sha": COMPILER_BLOBS["compiler_blob_sha"],
                "core_path": "control/task_context_core.py",
                "core_blob_sha": COMPILER_BLOBS["core_blob_sha"],
                "request_schema_path": "schemas/task-context-request.v1.schema.json",
                "request_schema_blob_sha": COMPILER_BLOBS["request_schema_blob_sha"],
                "pack_schema_path": "schemas/task-context-pack.v1.schema.json",
                "pack_schema_blob_sha": COMPILER_BLOBS["pack_schema_blob_sha"],
                "serialization_profile": "hwm-canonical-json/v1",
                "pack_schema": "hwm-task-context-pack/v1",
                "max_blob_bytes": 4194304,
            },
        }
        print("I09_0056_STAGE_REQUEST=" + canonical(stage_request))
        print("I09_0056_SOURCE_REQUEST_ID=" + request["request_id"])
        print("I09_0056_SOURCE_REQUEST_SHA256=" + request_sha)
        print("I09_0056_CONTEXT_SHA256=" + context_sha)
        print("I09_0056_GIT_BLOB_SHA=" + blob_sha)
        print("I09_0056_CONTEXT_BYTES=" + str(len(first)))


if __name__ == "__main__":
    unittest.main()
