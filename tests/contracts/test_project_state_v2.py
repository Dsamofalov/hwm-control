import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[2]
V1 = json.loads((ROOT / "schemas" / "project-state.v1.schema.json").read_text(encoding="utf-8"))
V2 = json.loads((ROOT / "schemas" / "project-state.v2.schema.json").read_text(encoding="utf-8"))
FC = FormatChecker()
SHA = "0123456789abcdef0123456789abcdef01234567"
PROVENANCE = [{"kind": "git_ref", "repo": "Dsamofalov/hwm_predictor", "sha": SHA, "reference": "refs/heads/main"}]
UNKNOWN_CHECKPOINT = {"status": "unknown", "reason": "No authoritative evidence is available."}


def v2_state(head):
    return {
        "schema": "hwm-project-state/v2",
        "generated_at": "2026-08-14T12:40:00Z",
        "provenance": [{"kind": "git_ref", "repo": "Dsamofalov/hwm-control", "sha": SHA}],
        "product": {
            "repo": "Dsamofalov/hwm_predictor",
            "head": head,
            "last_core_green": copy.deepcopy(UNKNOWN_CHECKPOINT),
            "last_full_green": copy.deepcopy(UNKNOWN_CHECKPOINT),
            "last_post_merge_green": copy.deepcopy(UNKNOWN_CHECKPOINT),
            "last_live_evidenced": copy.deepcopy(UNKNOWN_CHECKPOINT),
        },
        "requirements": {},
        "tasks": {"ready": [], "claimed": [], "blocked": []},
        "knowledge": {"status": "unknown", "reason": "Knowledge materialization not built."},
        "graph": {"status": "unknown", "reason": "Graph materialization not built."},
    }


def v1_state():
    obj = v2_state(SHA)
    obj["schema"] = "hwm-project-state/v1"
    obj["product"]["head"] = SHA
    return obj


def validate(schema, obj):
    Draft202012Validator(schema, format_checker=FC).validate(obj)


class ProjectStateV2Contracts(unittest.TestCase):
    def bad_v2(self, obj):
        with self.assertRaises(ValidationError):
            validate(V2, obj)

    def test_schema_documents_and_unchanged_checkpoint_semantics(self):
        Draft202012Validator.check_schema(V1)
        Draft202012Validator.check_schema(V2)
        for definition in ("error", "provenance", "checkpoint", "health"):
            with self.subTest(definition=definition):
                self.assertEqual(V1["$defs"][definition], V2["$defs"][definition])

    def test_valid_known_product_head(self):
        validate(V2, v2_state({"status": "known", "sha": SHA, "provenance": PROVENANCE}))

    def test_valid_unknown_product_head(self):
        validate(V2, v2_state({"status": "unknown", "reason": "Exact refs/heads/main is unavailable."}))

    def test_valid_error_product_head(self):
        validate(V2, v2_state({"status": "error", "error": {"code": "PROVIDER_UNAVAILABLE", "message": "Provider unavailable.", "retryable": True}}))

    def test_known_without_provenance_fails(self):
        self.bad_v2(v2_state({"status": "known", "sha": SHA}))

    def test_known_with_reason_or_error_fails(self):
        for extra in ({"reason": "ambiguous"}, {"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Provider unavailable.", "retryable": True}}):
            with self.subTest(extra=extra):
                self.bad_v2(v2_state({"status": "known", "sha": SHA, "provenance": PROVENANCE, **extra}))

    def test_unknown_with_sha_provenance_or_error_fails(self):
        extras = ({"sha": SHA}, {"provenance": PROVENANCE}, {"error": {"code": "PROVIDER_UNAVAILABLE", "message": "Provider unavailable.", "retryable": True}})
        for extra in extras:
            with self.subTest(extra=extra):
                self.bad_v2(v2_state({"status": "unknown", "reason": "No exact ref.", **extra}))

    def test_error_with_sha_provenance_or_reason_fails(self):
        extras = ({"sha": SHA}, {"provenance": PROVENANCE}, {"reason": "ambiguous"})
        for extra in extras:
            with self.subTest(extra=extra):
                self.bad_v2(v2_state({"status": "error", "error": {"code": "PROVIDER_UNAVAILABLE", "message": "Provider unavailable.", "retryable": True}, **extra}))

    def test_malformed_sha_fails(self):
        self.bad_v2(v2_state({"status": "known", "sha": "ABC123", "provenance": PROVENANCE}))

    def test_extra_property_fails(self):
        self.bad_v2(v2_state({"status": "unknown", "reason": "No exact ref.", "cached_sha": SHA}))

    def test_unknown_reason_must_be_nonempty_sanitized_single_line(self):
        for reason in ("", "   ", "line one\nline two", "line one\rline two"):
            with self.subTest(reason=repr(reason)):
                self.bad_v2(v2_state({"status": "unknown", "reason": reason}))

    def test_product_and_state_fields_remain_required(self):
        for field in ("repo", "head", "last_core_green", "last_full_green", "last_post_merge_green", "last_live_evidenced"):
            obj = v2_state({"status": "unknown", "reason": "No exact ref."})
            del obj["product"][field]
            with self.subTest(product_field=field):
                self.bad_v2(obj)
        for field in ("provenance", "product", "requirements", "tasks", "knowledge", "graph"):
            obj = v2_state({"status": "unknown", "reason": "No exact ref."})
            del obj[field]
            with self.subTest(state_field=field):
                self.bad_v2(obj)

    def test_core_full_checkpoint_behavior_is_unchanged(self):
        obj = v2_state({"status": "unknown", "reason": "No exact ref."})
        obj["product"]["last_core_green"] = {"status": "known", "sha": SHA}
        self.bad_v2(obj)
        obj = v2_state({"status": "unknown", "reason": "No exact ref."})
        obj["product"]["last_full_green"] = {"status": "unknown", "reason": "No exact gate.", "sha": SHA}
        self.bad_v2(obj)
        obj = v2_state({"status": "unknown", "reason": "No exact ref."})
        obj["product"]["last_full_green"] = {"status": "error", "reason": "Ambiguous"}
        self.bad_v2(obj)

    def test_v1_remains_validatable_separately(self):
        validate(V1, v1_state())

    def test_v1_rejects_v2_head_shape(self):
        obj = v1_state()
        obj["product"]["head"] = {"status": "unknown", "reason": "No exact ref."}
        with self.assertRaises(ValidationError):
            validate(V1, obj)

    def test_exact_marker_selects_version_without_silent_coercion(self):
        obj = v2_state({"status": "unknown", "reason": "No exact ref."})
        obj["schema"] = "hwm-project-state/v1"
        self.bad_v2(obj)


if __name__ == "__main__":
    unittest.main()
