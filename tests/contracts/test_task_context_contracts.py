import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from task_context_vectors import *  # noqa: F401,F403

class TaskContextContractTests(unittest.TestCase):
    def bad(self, schema, value):
        with self.assertRaises(ValidationError):
            validate_schema(schema, value)

    def test_schema_documents_and_valid_request_pack(self):
        Draft202012Validator.check_schema(REQ_SCHEMA)
        Draft202012Validator.check_schema(PACK_SCHEMA)
        req = base_request()
        pack = base_pack(req)
        validate_request_semantics(req)
        validate_pack_semantics(req, pack)

    def test_unknown_fields_and_unsupported_versions_rejected(self):
        req = base_request()
        req["unexpected"] = True
        self.bad(REQ_SCHEMA, req)
        req = base_request()
        req["schema"] = "hwm-task-context-request/v2"
        self.bad(REQ_SCHEMA, req)
        pack = base_pack()
        pack["token"] = "forbidden"
        self.bad(PACK_SCHEMA, pack)
        pack = base_pack()
        pack["schema"] = "hwm-task-context-pack/v999"
        self.bad(PACK_SCHEMA, pack)

    def test_task_and_issue_identity_are_exact(self):
        req = base_request()
        req["task"]["task_key"] = "I09-0046"
        bind_request_id(req)
        with self.assertRaises(ContractError):
            validate_request_semantics(req)
        req = base_request()
        req["issue_snapshot"]["issue_number"] = 46
        req["issue_snapshot"]["snapshot_sha256"] = issue_snapshot_digest(req["issue_snapshot"])
        bind_request_id(req)
        with self.assertRaises(ContractError):
            validate_request_semantics(req)

    def test_malformed_sha_blob_and_snapshot_provenance_rejected(self):
        req = base_request()
        req["product"]["commit"] = "HEAD"
        self.bad(REQ_SCHEMA, req)
        req = base_request()
        req["historical_ledger"]["claims"]["blob_sha"] = "A" * 40
        self.bad(REQ_SCHEMA, req)
        req = base_request()
        req["issue_snapshot"]["snapshot_sha256"] = H_C
        bind_request_id(req)
        with self.assertRaises(ContractError):
            validate_request_semantics(req)

    def test_stale_or_mismatched_provenance_is_not_a_valid_pack(self):
        req = base_request()
        pack = base_pack(req)
        pack["freshness"]["checks"][0]["observed"] = SHA_D
        with self.assertRaises(ContractError):
            validate_pack_semantics(req, pack)
        pack = base_pack(req)
        pack["product"]["commit"] = SHA_D
        with self.assertRaises(ContractError):
            validate_pack_semantics(req, pack)
        req = base_request()
        req["historical_ledger"]["commit"] = SHA_C
        bind_request_id(req)
        with self.assertRaises(ContractError):
            validate_request_semantics(req)

    def test_request_identity_and_canonical_json_vectors(self):
        req = base_request()
        supplied = req["request_id"]
        identity = copy.deepcopy(req)
        identity.pop("request_id")
        self.assertEqual(supplied, "tcr1-" + sha256(canonical_bytes(identity)))
        a = {"β": "é", "a": [3, 2, 1], "z": {"b": False, "a": None}}
        b = {"z": {"a": None, "b": False}, "a": [3, 2, 1], "β": "é"}
        expected = '{"a":[3,2,1],"z":{"a":null,"b":false},"β":"é"}'.encode("utf-8")
        self.assertEqual(canonical_bytes(a), expected)
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))
        self.assertEqual(canonical_bytes(a, trailing_lf=True), expected + b"\n")
        with self.assertRaises(ValueError):
            canonical_bytes({"n": math.nan})
        self.assertNotEqual(canonical_bytes("é"), canonical_bytes("e\u0301"))

    def test_context_json_is_byte_identical_and_markdown_is_not_v1(self):
        pack = base_pack()
        first = canonical_bytes(pack, trailing_lf=True)
        reordered = dict(reversed(list(pack.items())))
        second = canonical_bytes(reordered, trailing_lf=True)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertFalse(first.endswith(b"\n\n"))
        self.assertEqual(pack["serialization"]["context_markdown"], "not_defined_in_v1")
        contract = (ROOT / "docs" / "I09_TASK_CONTEXT_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("`context.md` is not defined by v1", contract)

    def test_stable_ranking_tie_break_dedup_and_exact_budgets(self):
        budgets = {
            "total_content_bytes": 8,
            "per_source_max_bytes": 4,
            "per_authority_bytes": {
                "authoritative_current_state": 8,
                "authoritative_git_github_ci": 8,
                "product_source": 8,
                "knowledge_delta": 8,
                "historical_ledger": 8,
            },
        }
        candidates = [
            {"source_id": "product.z", "authority_class": "product_source", "media_type": "text/plain", "priority": 5, "required": False, "truncation_allowed": True, "content": "AéBC"},
            {"source_id": "product.a", "authority_class": "product_source", "media_type": "text/plain", "priority": 5, "required": False, "truncation_allowed": True, "content": "1234"},
            {"source_id": "product.dupe", "authority_class": "product_source", "media_type": "text/plain", "priority": 6, "required": False, "truncation_allowed": True, "content": "1234"},
        ]
        out = select_for_budget(candidates, budgets)
        self.assertEqual(out[0][:3], ("product.a", "included", 4))
        self.assertEqual(out[1][0], "product.z")
        self.assertEqual(out[1][1:3], ("truncated", 4))
        self.assertEqual(out[2], ("product.dupe", "omitted", 0, "deduplicated", "product.a"))
        self.assertEqual(sum(x[2] for x in out), 8)
        self.assertEqual(longest_utf8_prefix("AéBC", 4), "AéB")

    def test_dedup_identity_preserves_authority_class(self):
        budgets = {
            "total_content_bytes": 20,
            "per_source_max_bytes": 10,
            "per_authority_bytes": {
                "authoritative_current_state": 10,
                "authoritative_git_github_ci": 10,
                "product_source": 10,
                "knowledge_delta": 10,
                "historical_ledger": 10,
            },
        }
        candidates = [
            {"source_id": "product.same", "authority_class": "product_source", "media_type": "text/plain", "priority": 1, "required": False, "truncation_allowed": True, "content": "same"},
            {"source_id": "history.same", "authority_class": "historical_ledger", "media_type": "text/plain", "priority": 1, "required": False, "truncation_allowed": True, "content": "same"},
        ]
        out = select_for_budget(candidates, budgets)
        self.assertEqual([x[1] for x in out], ["included", "included"])

    def test_omitted_truncated_unknown_error_are_distinct(self):
        req = base_request()
        base = base_pack(req)["sources"][0]
        prov = base["provenance"]
        common = {
            "source_id": "product.optional",
            "authority_class": "product_source",
            "media_type": "text/plain",
            "priority": 20,
            "required": False,
            "truncation_allowed": True,
            "provenance": prov,
        }
        omitted = {**common, "status": "omitted", "original_byte_count": 10, "content_sha256": H_A, "omission_reason": "budget_exhausted"}
        truncated = {**common, "status": "truncated", "original_byte_count": 10, "emitted_byte_count": 3, "content_sha256": H_A,
                     "emitted_sha256": sha256(b"abc"), "content": "abc", "truncation": {"rule": "longest_valid_utf8_prefix", "limit_bytes": 3}}
        unknown = {**common, "status": "unknown", "reason": "Optional source was not deterministically available."}
        err = {**common, "status": "error", "error": {"code": "SOURCE_FETCH_ERROR", "message": "Exact optional source retrieval failed.", "retryable": True}}
        for item in (omitted, truncated, unknown, err):
            pack = base_pack(req)
            pack["sources"] = [item]
            validate_schema(PACK_SCHEMA, pack)
        mixed = copy.deepcopy(unknown)
        mixed["content"] = "guess"
        pack = base_pack(req)
        pack["sources"] = [mixed]
        self.bad(PACK_SCHEMA, pack)

    def test_required_source_cannot_be_unknown_error_or_omitted(self):
        req = base_request()
        pack = base_pack(req)
        source = pack["sources"][0]
        source.clear()
        source.update({
            "source_id": "product.solver",
            "authority_class": "product_source",
            "media_type": "text/x-python",
            "priority": 10,
            "required": True,
            "truncation_allowed": True,
            "provenance": {"kind": "git_blob", "repository": req["product"]["repository"], "commit": req["product"]["commit"],
                           "path": "solver.py", "blob_sha": SHA_D, "content_sha256": H_A},
            "status": "unknown",
            "reason": "Missing exact bytes.",
        })
        pack["selection"]["emitted_content_bytes"] = 0
        with self.assertRaises(ContractError):
            validate_pack_semantics(req, pack)

    def test_authority_classes_are_explicit_and_separated(self):
        pack = base_pack()
        self.assertEqual(pack["authority_model"]["classes"], [
            "authoritative_current_state",
            "authoritative_git_github_ci",
            "historical_ledger",
            "knowledge_delta",
            "product_source",
            "derived_task_context",
            "llm_semantic_output",
        ])
        self.assertTrue(pack["authority_model"]["historical_is_not_current_state"])
        self.assertTrue(pack["authority_model"]["derived_context_is_not_authority"])
        self.assertTrue(pack["authority_model"]["llm_is_not_deterministic_authority"])
        self.assertNotEqual("historical_ledger", "authoritative_current_state")

    def test_public_data_boundary_is_closed_and_declared(self):
        for schema in (REQ_SCHEMA, PACK_SCHEMA):
            self.assertFalse(schema["additionalProperties"])
            props = set()
            stack = [schema]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    props.update((node.get("properties") or {}).keys())
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
            forbidden_field_names = {"token", "cookie", "password", "private_key", "session", "environment", "browser_profile"}
            self.assertTrue(forbidden_field_names.isdisjoint(props))
        req = base_request()
        self.assertEqual(req["public_data"]["on_violation"], "reject")
        self.assertIn("sensitive_raw_evidence", req["public_data"]["forbidden_categories"])

    def test_existing_versioned_schema_bytes_are_unchanged(self):
        for name, expected in EXISTING_SCHEMA_BLOBS.items():
            data = (ROOT / "schemas" / name).read_bytes()
            with self.subTest(name=name):
                self.assertEqual(git_blob_sha(data), expected)

    def test_historical_current_state_contracts_are_not_reinterpreted(self):
        old_claim = json.loads((ROOT / "schemas" / "historical-claim.v1.schema.json").read_text(encoding="utf-8"))
        old_state = json.loads((ROOT / "schemas" / "project-state.v2.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(old_claim["properties"]["authority"]["const"], "historical")
        self.assertEqual(old_state["properties"]["schema"]["const"], "hwm-project-state/v2")
        self.assertEqual(PACK_SCHEMA["$defs"]["authority_model"]["properties"]["historical_is_not_current_state"]["const"], True)


if __name__ == "__main__":
    unittest.main()
