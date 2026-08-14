import json
import sys
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control.product_head import (  # noqa: E402
    PRODUCT_REF,
    PRODUCT_REPOSITORY,
    ProviderError,
    ProviderNotFound,
    extract_product_head,
)

SHA = "0123456789abcdef0123456789abcdef01234567"


class FakeProvider:
    def __init__(self, repository=None, ref=None):
        self.repository = repository
        self.ref = ref
        self.calls = []

    @staticmethod
    def _resolve(value):
        if isinstance(value, Exception):
            raise value
        return value

    def get_repository(self, repository):
        self.calls.append(("repository", repository))
        return self._resolve(self.repository)

    def get_ref(self, repository, ref):
        self.calls.append(("ref", repository, ref))
        return self._resolve(self.ref)


def good_repo():
    return {"full_name": PRODUCT_REPOSITORY}


def good_ref(sha=SHA):
    return {"ref": PRODUCT_REF, "object": {"type": "commit", "sha": sha}}


class ProductHeadExtractorTests(unittest.TestCase):
    def test_exact_repository_ref_sha_success_with_schema_valid_provenance(self):
        provider = FakeProvider(good_repo(), good_ref())
        result = extract_product_head(provider)
        self.assertEqual(
            (result["status"], result["repository"], result["ref"], result["sha"]),
            ("known", PRODUCT_REPOSITORY, PRODUCT_REF, SHA),
        )
        self.assertEqual(
            provider.calls,
            [("repository", PRODUCT_REPOSITORY), ("ref", PRODUCT_REPOSITORY, PRODUCT_REF)],
        )
        schema = json.loads(
            (ROOT / "schemas" / "project-state.v1.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(schema["$defs"]["provenance"]).validate(
            result["provenance"][0]
        )

    def test_missing_ref_is_explicit_unknown_without_sha_or_fallback(self):
        result = extract_product_head(FakeProvider(good_repo(), ProviderNotFound()))
        self.assertEqual(result["status"], "unknown")
        self.assertIn(PRODUCT_REF, result["reason"])
        self.assertNotIn("sha", result)
        self.assertNotIn("provenance", result)
        self.assertNotIn("error", result)

    def test_repository_unavailable_is_explicit_error(self):
        provider = FakeProvider(ProviderNotFound())
        result = extract_product_head(provider)
        self.assertEqual(result["error"]["code"], "REPOSITORY_UNAVAILABLE")
        self.assertFalse(result["error"]["retryable"])
        self.assertEqual(provider.calls, [("repository", PRODUCT_REPOSITORY)])

    def test_api_unavailable_is_explicit_retryable_error(self):
        result = extract_product_head(
            FakeProvider(ProviderError("API_UNAVAILABLE", "unavailable", True))
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "API_UNAVAILABLE")
        self.assertTrue(result["error"]["retryable"])
        self.assertNotIn("sha", result)

    def test_malformed_repository_response_stops_before_ref(self):
        provider = FakeProvider({"full_name": "someone/else"}, good_ref())
        result = extract_product_head(provider)
        self.assertEqual(result["error"]["code"], "MALFORMED_UPSTREAM_RESPONSE")
        self.assertEqual(provider.calls, [("repository", PRODUCT_REPOSITORY)])

    def test_malformed_ref_sha_is_error_not_unknown(self):
        result = extract_product_head(FakeProvider(good_repo(), good_ref(SHA.upper())))
        self.assertEqual(result["error"]["code"], "MALFORMED_UPSTREAM_RESPONSE")
        self.assertNotIn("sha", result)

    def test_unexpected_ref_identity_is_error_not_fallback(self):
        bad = {"ref": "refs/heads/other", "object": {"type": "commit", "sha": SHA}}
        result = extract_product_head(FakeProvider(good_repo(), bad))
        self.assertEqual(result["error"]["code"], "MALFORMED_UPSTREAM_RESPONSE")
        self.assertNotIn("sha", result)


if __name__ == "__main__":
    unittest.main()
