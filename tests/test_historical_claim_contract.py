import copy
import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from control.historical_claim_contract import (
    CLAIMS_PATH, CONFLICTS_PATH, INITIAL_REQUIRED_SOURCE_CLASSES, MATERIALIZED_REPOSITORY,
    HistoricalClaimContractError, canonical_json, compute_claim_id, content_sha256,
    git_blob_sha, materialize_ledger, validate_claim_semantics, validate_ledger,
    verify_source_binding,
)

ROOT = Path(__file__).resolve().parents[1]
CLAIM_SCHEMA = json.loads((ROOT / "schemas" / "historical-claim.v1.schema.json").read_text(encoding="utf-8"))
CONFLICT_SCHEMA = json.loads((ROOT / "schemas" / "historical-conflicts.v1.schema.json").read_text(encoding="utf-8"))
TASK_CLAIM_SCHEMA = json.loads((ROOT / "schemas" / "claim.v1.schema.json").read_text(encoding="utf-8"))
DELTA_SCHEMA = json.loads((ROOT / "schemas" / "knowledge-delta.v1.schema.json").read_text(encoding="utf-8"))
FC = FormatChecker()
COMMIT = "0123456789abcdef0123456789abcdef01234567"
SOURCE = b"alpha\nlegacy behavior is enabled\nomega\n"


def make_claim(*, subject="feature:x", predicate="behavior", value="enabled", status="supported",
               source_class="changelog", line=2, validity=None):
    claim = {
        "schema": "hwm-historical-claim/v1",
        "claim_id": "hc1-" + "0" * 64,
        "authority": "historical",
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "provenance": {
            "source_class": source_class,
            "repository": "Dsamofalov/hwm_predictor",
            "commit": COMMIT,
            "path": "changelog.md",
            "locator": {"kind": "line_range", "start_line": line, "end_line": line},
            "blob_sha": git_blob_sha(SOURCE),
            "content_sha256": content_sha256(SOURCE),
        },
        "validity": validity or {"valid_from": None, "valid_until": None},
        "status": status,
        "relations": {"supersedes": [], "superseded_by": [], "conflicts_with": []},
    }
    claim["claim_id"] = compute_claim_id(claim)
    return claim


def schema_validate(claim):
    Draft202012Validator(CLAIM_SCHEMA, format_checker=FC).validate(claim)


class HistoricalClaimContractTests(unittest.TestCase):
    def test_schema_documents(self):
        Draft202012Validator.check_schema(CLAIM_SCHEMA)
        Draft202012Validator.check_schema(CONFLICT_SCHEMA)

    def test_all_four_statuses_schema_valid(self):
        supported = make_claim(status="supported")
        unverified = make_claim(value="unknown source note", status="unverified")
        old = make_claim(value="old", status="superseded")
        newer = make_claim(value="new", status="supported", line=3)
        old["relations"]["superseded_by"] = [newer["claim_id"]]
        newer["relations"]["supersedes"] = [old["claim_id"]]
        a = make_claim(value="yes", status="contradicted")
        b = make_claim(value="no", status="contradicted", line=3)
        a["relations"]["conflicts_with"] = [b["claim_id"]]
        b["relations"]["conflicts_with"] = [a["claim_id"]]
        for claim in (supported, unverified, old, newer, a, b):
            schema_validate(claim)
            validate_claim_semantics(claim)
        validate_ledger([old, newer, a, b, supported, unverified])

    def test_deterministic_claim_id_vector_and_input_order(self):
        claim = make_claim()
        expected = "hc1-" + hashlib.sha256(canonical_json({
            "identity_schema": "hwm-historical-claim-identity/v1",
            "subject": claim["subject"], "predicate": claim["predicate"], "value": claim["value"],
            "source": {k: claim["provenance"][k] for k in ("repository", "commit", "path", "locator", "blob_sha", "content_sha256")},
            "validity": claim["validity"],
        }).encode("utf-8")).hexdigest()
        self.assertEqual(claim["claim_id"], expected)
        reordered = dict(reversed(list(claim.items())))
        self.assertEqual(compute_claim_id(reordered), expected)

    def test_status_does_not_change_identity_but_unverified_not_implicit_supported(self):
        claim = make_claim(status="unverified")
        promoted = copy.deepcopy(claim); promoted["status"] = "supported"
        self.assertEqual(compute_claim_id(claim), compute_claim_id(promoted))
        validate_claim_semantics(claim)
        self.assertEqual(claim["status"], "unverified")
        promoted["claim_id"] = compute_claim_id(promoted)
        with self.assertRaises(HistoricalClaimContractError):
            validate_ledger([claim, promoted])

    def test_exact_source_binding_and_stale_missing_ambiguous(self):
        claim = make_claim()
        verify_source_binding(claim, repository="Dsamofalov/hwm_predictor", commit=COMMIT,
                              path="changelog.md", source_bytes=SOURCE)
        bad = copy.deepcopy(claim); bad["provenance"]["blob_sha"] = "f" * 40; bad["claim_id"] = compute_claim_id(bad)
        with self.assertRaises(HistoricalClaimContractError):
            verify_source_binding(bad, repository="Dsamofalov/hwm_predictor", commit=COMMIT,
                                  path="changelog.md", source_bytes=SOURCE)
        with self.assertRaises(HistoricalClaimContractError):
            verify_source_binding(claim, repository="Dsamofalov/hwm_predictor", commit=COMMIT,
                                  path="changelog.md", source_bytes=None, revision_candidates=0)
        with self.assertRaises(HistoricalClaimContractError):
            verify_source_binding(claim, repository="Dsamofalov/hwm_predictor", commit=COMMIT,
                                  path="changelog.md", source_bytes=SOURCE, revision_candidates=2)
        with self.assertRaises(HistoricalClaimContractError):
            verify_source_binding(claim, repository="Dsamofalov/hwm_predictor", commit="f" * 40,
                                  path="changelog.md", source_bytes=SOURCE)

    def test_symbol_binding_requires_unique_exact_symbol(self):
        claim = make_claim()
        claim["provenance"]["locator"] = {"kind": "symbol", "symbol": "Foo.bar"}
        claim["claim_id"] = compute_claim_id(claim)
        verify_source_binding(claim, repository="Dsamofalov/hwm_predictor", commit=COMMIT,
                              path="changelog.md", source_bytes=SOURCE, resolved_symbols=["Foo.bar"])
        with self.assertRaises(HistoricalClaimContractError):
            verify_source_binding(claim, repository="Dsamofalov/hwm_predictor", commit=COMMIT,
                                  path="changelog.md", source_bytes=SOURCE, resolved_symbols=["Foo.bar", "Foo.bar"])

    def test_malformed_provenance_and_invalid_claim_id(self):
        cases = []
        c = make_claim(); c["provenance"]["repository"] = "guess"; cases.append(c)
        c = make_claim(); c["provenance"]["commit"] = "HEAD"; cases.append(c)
        c = make_claim(); c["provenance"]["path"] = "../x"; cases.append(c)
        c = make_claim(); c["provenance"]["locator"] = {"kind": "line_range", "start_line": 3, "end_line": 2}; cases.append(c)
        c = make_claim(); c["claim_id"] = "hc1-" + "f" * 64; cases.append(c)
        for claim in cases:
            with self.subTest(claim=claim):
                with self.assertRaises((HistoricalClaimContractError, ValidationError)):
                    schema_validate(claim); validate_claim_semantics(claim)

    def test_stable_order_byte_repeat_and_idempotent_duplicate(self):
        a = make_claim(value="A")
        b = make_claim(value="B", line=3)
        first = materialize_ledger([b, a, copy.deepcopy(a)])
        second = materialize_ledger([a, b])
        self.assertEqual(first, second)
        self.assertEqual(set(first), {CLAIMS_PATH, CONFLICTS_PATH})
        lines = first[CLAIMS_PATH].decode().splitlines()
        ids = [json.loads(line)["claim_id"] for line in lines]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(first[CLAIMS_PATH].endswith(b"\n"))
        self.assertTrue(first[CONFLICTS_PATH].endswith(b"\n"))

    def test_inconsistent_duplicate_rejected(self):
        a = make_claim()
        changed = copy.deepcopy(a); changed["provenance"]["source_class"] = "status_doc"
        self.assertEqual(a["claim_id"], changed["claim_id"])
        with self.assertRaises(HistoricalClaimContractError):
            materialize_ledger([a, changed])

    def test_contradiction_preserves_two_claims_and_conflict_pair(self):
        a = make_claim(value="yes", status="contradicted")
        b = make_claim(value="no", status="contradicted", line=3)
        a["relations"]["conflicts_with"] = [b["claim_id"]]
        b["relations"]["conflicts_with"] = [a["claim_id"]]
        out = materialize_ledger([a, b])
        self.assertEqual(len(out[CLAIMS_PATH].decode().splitlines()), 2)
        conflicts = json.loads(out[CONFLICTS_PATH])
        Draft202012Validator(CONFLICT_SCHEMA).validate(conflicts)
        self.assertEqual(len(conflicts["conflicts"]), 1)
        self.assertEqual(conflicts["conflicts"][0]["claim_ids"], sorted([a["claim_id"], b["claim_id"]]))

    def test_contradiction_cannot_be_silently_collapsed(self):
        a = make_claim(value="yes", status="contradicted")
        a["relations"]["conflicts_with"] = ["hc1-" + "f" * 64]
        with self.assertRaises(HistoricalClaimContractError):
            materialize_ledger([a])

    def test_supersession_retains_old_claim_and_rejects_dangling(self):
        old = make_claim(value="old", status="superseded")
        new = make_claim(value="new", line=3)
        old["relations"]["superseded_by"] = [new["claim_id"]]
        new["relations"]["supersedes"] = [old["claim_id"]]
        out = materialize_ledger([new, old])
        self.assertEqual(len(out[CLAIMS_PATH].decode().splitlines()), 2)
        with self.assertRaises(HistoricalClaimContractError):
            materialize_ledger([old])

    def test_current_state_override_attempt_rejected(self):
        for kwargs in ({"predicate": "current.product_head"}, {"subject": "current:state/current.json"}):
            claim = make_claim(**kwargs)
            with self.assertRaises((HistoricalClaimContractError, ValidationError)):
                schema_validate(claim); validate_claim_semantics(claim)

    def test_historical_claim_is_not_task_claim_v1(self):
        claim = make_claim()
        with self.assertRaises(ValidationError):
            Draft202012Validator(TASK_CLAIM_SCHEMA, format_checker=FC).validate(claim)

    def test_storage_and_initial_source_boundary(self):
        self.assertEqual(MATERIALIZED_REPOSITORY, "Dsamofalov/hwm-context")
        self.assertEqual(CLAIMS_PATH, "claims/claims.jsonl")
        self.assertEqual(CONFLICTS_PATH, "claims/conflicts.json")
        self.assertEqual(INITIAL_REQUIRED_SOURCE_CLASSES, {"changelog", "specification_history"})

    def test_i08_knowledge_delta_is_valid(self):
        delta = json.loads((ROOT / "knowledge-deltas" / "I08-0035.json").read_text(encoding="utf-8"))
        Draft202012Validator(DELTA_SCHEMA, format_checker=FC).validate(delta)
        self.assertEqual(delta["task_id"], 35)
        self.assertTrue(delta["verified_facts"] and delta["decisions"] and delta["changed_components"] and delta["tests"])


if __name__ == "__main__":
    unittest.main()
