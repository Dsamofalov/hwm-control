import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from task_context_compiler_vectors import *  # noqa: F401,F403

class TaskContextCompilerTests(unittest.TestCase):
    def test_valid_complete_compilation_is_byte_identical_and_context_json_only(self):
        provider = FakeProvider()
        req = base_request(provider)
        one = tc.compile_task_context(req, provider)
        two = tc.compile_task_context(copy.deepcopy(req), provider)
        self.assertEqual(one.context_json, two.context_json)
        self.assertEqual(one.artifact_name, "context.json")
        self.assertEqual(one.pack["serialization"]["context_markdown"], "not_defined_in_v1")
        self.assertNotIn("context.md", one.context_json.decode("utf-8"))
        self.assertTrue(one.context_json.endswith(b"\n"))
        self.assertFalse(one.context_json.endswith(b"\n\n"))
        self.assertFalse(one.context_json.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(json.loads(one.context_json), one.pack)
        self.assertEqual(one.pack["freshness"]["status"], "fresh")

    def test_shuffled_candidate_enumeration_produces_identical_selection(self):
        budgets = {
            "total_content_bytes": 20, "per_source_max_bytes": 10,
            "per_authority_bytes": {name: 20 for name in tc.AUTHORITY_ORDER},
        }
        base = {
            "authority_class": "product_source", "media_type": "text/plain", "priority": 2,
            "required": False, "truncation_allowed": True,
            "provenance": {"kind": "git_blob", "repository": "Dsamofalov/hwm_predictor", "commit": PRODUCT_SHA,
                           "path": "x", "blob_sha": "a" * 40, "content_sha256": "b" * 64},
        }
        a = [{**base, "source_id": "product.z", "content": "zz"}, {**base, "source_id": "product.a", "content": "aa"}]
        self.assertEqual(tc._select_sources(a, budgets), tc._select_sources(list(reversed(a)), budgets))

    def test_malformed_unsupported_request_and_request_id_rejected(self):
        req = base_request()
        req["schema"] = "hwm-task-context-request/v2"
        with self.assertRaises(Exception):
            tc.compile_task_context(req, FakeProvider())
        provider = FakeProvider()
        req = base_request(provider)
        req["request_id"] = "tcr1-" + "f" * 64
        with self.assertRaises(tc.CompilationError):
            tc.compile_task_context(req, provider)

    def test_task_issue_and_issue_snapshot_mismatch_rejected(self):
        provider = FakeProvider()
        req = base_request(provider)
        req["task"]["task_key"] = "I09-0047"
        req["request_id"] = tc.expected_request_id(req)
        with self.assertRaises(tc.CompilationError):
            tc.compile_task_context(req, provider)
        provider = FakeProvider()
        req = base_request(provider)
        provider.issue["body"] += " drift"
        with self.assertRaisesRegex(tc.CompilationError, "Issue snapshot"):
            tc.compile_task_context(req, provider)

    def test_product_exact_revision_is_never_substituted_with_head(self):
        provider = FakeProvider()
        req = base_request(provider)
        tc.compile_task_context(req, provider)
        self.assertNotIn(("head", "Dsamofalov/hwm_predictor"), provider.calls)
        self.assertIn(("blob", "Dsamofalov/hwm_predictor", PRODUCT_SHA, "solver.py"), provider.calls)
        self.assertNotIn(("blob", "Dsamofalov/hwm_predictor", OTHER_SHA, "solver.py"), provider.calls)

    def test_must_equal_current_product_head_is_exact(self):
        provider = FakeProvider()
        provider.heads["Dsamofalov/hwm_predictor"] = PRODUCT_SHA
        req = base_request(provider)
        req["product"] = {"repository": "Dsamofalov/hwm_predictor", "commit": PRODUCT_SHA,
                          "head_policy": "must_equal_current", "expected_current_head": PRODUCT_SHA}
        req["request_id"] = tc.expected_request_id(req)
        tc.compile_task_context(req, provider)
        provider.heads["Dsamofalov/hwm_predictor"] = OTHER_SHA
        with self.assertRaisesRegex(tc.CompilationError, "product current HEAD mismatch"):
            tc.compile_task_context(req, provider)

    def test_project_state_commit_blob_content_and_freshness_mismatch_rejected(self):
        provider = FakeProvider()
        req = base_request(provider)
        provider.heads["Dsamofalov/hwm-control"] = OTHER_SHA
        with self.assertRaisesRegex(tc.CompilationError, "control main"):
            tc.compile_task_context(req, provider)
        provider = FakeProvider()
        req = base_request(provider)
        req["project_state"]["content_sha256"] = "f" * 64
        req["request_id"] = tc.expected_request_id(req)
        with self.assertRaises(tc.ExactSourceMismatch):
            tc.compile_task_context(req, provider)

    def test_historical_ledger_commit_blob_content_mismatch_rejected(self):
        provider = FakeProvider()
        req = base_request(provider)
        provider.heads["Dsamofalov/hwm-context"] = OTHER_SHA
        with self.assertRaisesRegex(tc.CompilationError, "context main"):
            tc.compile_task_context(req, provider)
        provider = FakeProvider()
        req = base_request(provider)
        req["historical_ledger"]["claims"]["blob_sha"] = "f" * 40
        req["request_id"] = tc.expected_request_id(req)
        with self.assertRaises(tc.ExactSourceMismatch):
            tc.compile_task_context(req, provider)

    def test_knowledge_delta_commit_path_blob_content_mismatch_rejected(self):
        provider = FakeProvider()
        req = base_request(provider)
        req["knowledge_deltas"]["inputs"][0]["content_sha256"] = "e" * 64
        req["request_id"] = tc.expected_request_id(req)
        with self.assertRaises(tc.ExactSourceMismatch):
            tc.compile_task_context(req, provider)
        provider = FakeProvider()
        req = base_request(provider)
        req["knowledge_deltas"]["inputs"][0]["path"] = "knowledge-deltas/I09-0044.json"
        req["request_id"] = tc.expected_request_id(req)
        with self.assertRaises(tc.CompilationError):
            tc.compile_task_context(req, provider)

    def test_missing_required_exact_source_fails_closed(self):
        provider = FakeProvider()
        req = base_request(provider, product_required=True)
        key = ("Dsamofalov/hwm_predictor", PRODUCT_SHA, "solver.py")
        provider.unknown.add(key)
        with self.assertRaisesRegex(tc.CompilationError, "required exact source"):
            tc.compile_task_context(req, provider)

    def test_optional_unknown_error_and_validation_error_are_explicit(self):
        provider = FakeProvider()
        req = base_request(provider)
        key = ("Dsamofalov/hwm_predictor", PRODUCT_SHA, "solver.py")
        provider.unknown.add(key)
        out = tc.compile_task_context(req, provider)
        src = next(x for x in out.pack["sources"] if x["source_id"] == "product.solver")
        self.assertEqual(src["status"], "unknown")
        self.assertNotIn("content", src)

        provider = FakeProvider()
        req = base_request(provider)
        provider.errors[key] = tc.SourceFetchError("SOURCE_FETCH_ERROR", "Exact optional retrieval failed.", retryable=True)
        out = tc.compile_task_context(req, provider)
        src = next(x for x in out.pack["sources"] if x["source_id"] == "product.solver")
        self.assertEqual(src["status"], "error")
        self.assertTrue(src["error"]["retryable"])

        provider = FakeProvider()
        req = base_request(provider)
        provider.blobs[key] = tc.ExactBlob(b"different\n")
        out = tc.compile_task_context(req, provider)
        src = next(x for x in out.pack["sources"] if x["source_id"] == "product.solver")
        self.assertEqual(src["status"], "error")
        self.assertEqual(src["error"]["code"], "SOURCE_VALIDATION_ERROR")

    def test_stable_authority_order_source_tie_break_and_authority_preserving_dedup(self):
        budgets = {
            "total_content_bytes": 100, "per_source_max_bytes": 100,
            "per_authority_bytes": {name: 100 for name in tc.AUTHORITY_ORDER},
        }
        def c(sid, auth, content, priority=0):
            return {"source_id": sid, "authority_class": auth, "media_type": "text/plain", "priority": priority,
                    "required": False, "truncation_allowed": True,
                    "provenance": {"kind": "git_blob", "repository": "Dsamofalov/hwm_predictor", "commit": PRODUCT_SHA,
                                   "path": sid, "blob_sha": "a" * 40, "content_sha256": tc.sha256_bytes(content.encode())},
                    "content": content}
        out = tc._select_sources([
            c("product.z", "product_source", "same", 1),
            c("current.a", "authoritative_current_state", "same", 1),
            c("product.a", "product_source", "same", 1),
        ], budgets)
        self.assertEqual([x["source_id"] for x in out], ["current.a", "product.a", "product.z"])
        self.assertEqual(out[0]["status"], "included")
        self.assertEqual(out[1]["status"], "included")
        self.assertEqual(out[2]["status"], "omitted")
        self.assertEqual(out[2]["omission_reason"], "deduplicated")
        self.assertEqual(out[2]["duplicate_of"], "product.a")

    def test_exact_total_authority_source_budgets_and_multibyte_truncation(self):
        prov = {"kind": "git_blob", "repository": "Dsamofalov/hwm_predictor", "commit": PRODUCT_SHA,
                "path": "x", "blob_sha": "a" * 40, "content_sha256": "b" * 64}
        candidates = [{"source_id": "product.a", "authority_class": "product_source", "media_type": "text/plain",
                       "priority": 1, "required": False, "truncation_allowed": True, "provenance": prov,
                       "content": "AéBC"}]
        budgets = {"total_content_bytes": 4, "per_source_max_bytes": 10,
                   "per_authority_bytes": {**{name: 10 for name in tc.AUTHORITY_ORDER}, "product_source": 4}}
        out = tc._select_sources(candidates, budgets)[0]
        self.assertEqual(out["status"], "truncated")
        self.assertEqual(out["content"], "AéB")
        self.assertEqual(out["emitted_byte_count"], 4)
        self.assertEqual(out["truncation"]["limit_bytes"], 4)
        per_source = copy.deepcopy(budgets); per_source["total_content_bytes"] = 10; per_source["per_authority_bytes"]["product_source"] = 10; per_source["per_source_max_bytes"] = 3
        self.assertEqual(tc._select_sources(candidates, per_source)[0]["emitted_byte_count"], 3)
        per_authority = copy.deepcopy(budgets); per_authority["total_content_bytes"] = 10; per_authority["per_authority_bytes"]["product_source"] = 2
        self.assertEqual(tc._select_sources(candidates, per_authority)[0]["emitted_byte_count"], 1)
        self.assertEqual(tc.longest_valid_utf8_prefix("é", 1), "")

    def test_truncation_not_allowed_optional_is_omitted_required_is_rejected(self):
        prov = {"kind": "git_blob", "repository": "Dsamofalov/hwm_predictor", "commit": PRODUCT_SHA,
                "path": "x", "blob_sha": "a" * 40, "content_sha256": "b" * 64}
        base = {"source_id": "product.a", "authority_class": "product_source", "media_type": "text/plain",
                "priority": 1, "truncation_allowed": False, "provenance": prov, "content": "abcdef"}
        budgets = {"total_content_bytes": 3, "per_source_max_bytes": 3,
                   "per_authority_bytes": {name: 3 for name in tc.AUTHORITY_ORDER}}
        optional = tc._select_sources([{**base, "required": False}], budgets)[0]
        self.assertEqual((optional["status"], optional["omission_reason"]), ("omitted", "budget_exhausted"))
        with self.assertRaises(tc.CompilationError):
            tc._select_sources([{**base, "required": True}], budgets)

    def test_public_data_violation_rejected_not_redacted(self):
        provider = FakeProvider(product_content=b"api_key=abcdefghijklmnop\n")
        req = base_request(provider)
        with self.assertRaisesRegex(tc.CompilationError, "public-data policy violation"):
            tc.compile_task_context(req, provider)

    def test_canonical_json_vectors_nonfinite_unicode_and_no_normalization(self):
        value = {"β": "é", "a": [3, 2, 1], "z": {"b": False, "a": None}}
        expected = '{"a":[3,2,1],"z":{"a":null,"b":false},"β":"é"}'.encode("utf-8")
        self.assertEqual(tc.canonical_bytes(value), expected)
        self.assertEqual(tc.canonical_bytes(value, trailing_lf=True), expected + b"\n")
        self.assertNotEqual(tc.canonical_bytes("é"), tc.canonical_bytes("e\u0301"))
        with self.assertRaises(ValueError):
            tc.canonical_bytes({"n": math.nan})

    def test_no_github_writes_openai_llm_wiki_graphify_or_context_markdown_dependency(self):
        source = Path(tc.__file__).read_text(encoding="utf-8")
        lowered = source.lower()
        for forbidden in ("openai", "graphify", "context.md", "requests.post", "github.create", "update_issue", "create_pull"):
            self.assertNotIn(forbidden, lowered)
        self.assertNotIn("import requests", lowered)
        self.assertNotIn("subprocess", lowered)

    def test_i09_p0_schema_blobs_unchanged(self):
        expected = {
            "task-context-request.v1.schema.json": "c94d7caa0306799231ec276be2107db3c04946ea",
            "task-context-pack.v1.schema.json": "e17296906dbf4a0717a02fc4be8be197ac977e15",
        }
        for name, blob_sha in expected.items():
            with self.subTest(name=name):
                self.assertEqual(tc.git_blob_sha((ROOT / "schemas" / name).read_bytes()), blob_sha)


if __name__ == "__main__":
    unittest.main()
