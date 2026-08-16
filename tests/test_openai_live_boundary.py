from __future__ import annotations

import base64
import json
import unittest

from control import openai_live_boundary as live
from control import semantic_contract as sc
from tests.semantic_contract_vectors import valid_input, valid_output


MAIN_SHA = "1" * 40


def live_request():
    value = {
        "schema": live.REQUEST_SCHEMA,
        "request_id": "olr1-" + "0" * 64,
        "semantic_input": valid_input(),
        "execution": {
            "trust_policy": live.TRUST_POLICY,
            "auth_mechanism": live.AUTH_MECHANISM,
            "oidc_issuer": live.OIDC_ISSUER,
            "oidc_audience": live.OIDC_AUDIENCE,
            "oidc_subject": live.OIDC_SUBJECT,
            "repository": live.REPOSITORY,
            "ref": live.REF,
            "workflow_ref": live.WORKFLOW_REF,
            "token_endpoint": live.OPENAI_TOKEN_ENDPOINT,
            "api_endpoint": live.RESPONSES_ENDPOINT,
            "required_wif_scope": list(live.REQUIRED_WIF_SCOPE),
            "store": False,
            "tools": [],
            "public_data_preflight": "fail_closed_before_token_exchange",
            "verifier_order": "after_provider_response_before_acceptance",
            "raw_prompt_logging": False,
            "raw_output_logging": False,
            "raw_io_artifacts_or_cache": False,
            "token_persistence": False,
            "deterministic_fallback": "deterministic_task_context_only",
        },
    }
    value["request_id"] = live.expected_request_id(value)
    return value


def runtime():
    return {
        "repository": live.REPOSITORY,
        "ref": live.REF,
        "workflow_ref": live.WORKFLOW_REF,
        "event_name": "workflow_dispatch",
        "sha": MAIN_SHA,
    }


def credential():
    return {
        "access_token": "test-only-ephemeral-token",
        "identity_provider_id_sha256": "a" * 64,
        "service_account_id_sha256": "b" * 64,
        "scope": ["api.model.request"],
        "expires_in_seconds": 900,
    }


def response_for(value):
    semantic = valid_output(value["semantic_input"])
    return {
        "id": "resp_test",
        "output": [{
            "type": "message",
            "content": [{
                "type": "output_text",
                "text": json.dumps(semantic, sort_keys=True),
            }],
        }],
        "usage": {
            "input_tokens": value["semantic_input"]["budget_observation"]["input_tokens"],
            "output_tokens": semantic["usage"]["output_tokens"],
        },
    }


def jwt_for(claims):
    def enc(obj):
        return base64.urlsafe_b64encode(
            json.dumps(obj, separators=(",", ":")).encode()
        ).decode().rstrip("=")
    return f"{enc({'alg':'RS256','kid':'test'})}.{enc(claims)}.sig"


class LiveBoundaryTests(unittest.TestCase):
    def test_request_is_forward_only_strict_and_tool_free(self):
        value = live_request()
        live.validate_live_request(value)
        payload = live.build_responses_payload(value)
        self.assertEqual(payload["model"], value["semantic_input"]["llm_provenance"]["model"]["model_id"])
        self.assertEqual(payload["input"], value["semantic_input"]["llm_provenance"]["prompt"]["rendered_text"])
        self.assertFalse(payload["store"])
        self.assertEqual(payload["tools"], [])
        fmt = payload["text"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertTrue(fmt["strict"])

        forbidden = set(live._UNSUPPORTED_STRICT_SCHEMA_KEYS)

        def walk(node):
            if isinstance(node, dict):
                self.assertTrue(forbidden.isdisjoint(node))
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(fmt["schema"])

    def test_request_id_is_the_only_path_selector(self):
        value = live_request()
        self.assertTrue(str(live.request_path(value["request_id"])).endswith(
            f"execution/openai-live-requests/{value['request_id']}.json"
        ))
        with self.assertRaises(live.LiveBoundaryError):
            live.request_path("../../main")

    def test_runtime_must_be_exact_protected_main_workflow(self):
        live.assert_runtime_context(MAIN_SHA, runtime())
        for key, bad in [
            ("ref", "refs/heads/agent/infra-0062-trusted-openai-boundary"),
            ("event_name", "pull_request"),
            ("workflow_ref", "Dsamofalov/hwm-control/.github/workflows/other.yml@refs/heads/main"),
            ("sha", "2" * 40),
        ]:
            candidate = runtime()
            candidate[key] = bad
            with self.assertRaises(live.LiveBoundaryError):
                live.assert_runtime_context(MAIN_SHA, candidate)

    def test_public_preflight_precedes_credential_and_verifier(self):
        value = live_request()
        events = []

        def context_check(_):
            events.append("context")
            return {}

        def credential_factory(_):
            events.append("credential")
            return credential()

        def call_once(payload, token, timeout):
            events.append("call")
            self.assertEqual(token, "test-only-ephemeral-token")
            self.assertGreater(timeout, 0)
            self.assertEqual(payload["tools"], [])
            return response_for(value), "req_safe", 12

        result = live.execute_live(
            value, MAIN_SHA, runtime(), {},
            context_check=context_check,
            credential_factory=credential_factory,
            call_once=call_once,
        )
        self.assertEqual(events, ["context", "credential", "call"])
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(result["verification"]["materialization_allowed"])
        self.assertEqual(result["classification"], "derived_non_authoritative")
        self.assertNotIn("test-only-ephemeral-token", json.dumps(result))

    def test_credential_absence_degrades_without_provider_call(self):
        value = live_request()
        called = []

        def no_credential(_):
            raise live.LiveBoundaryError("WIF_CONFIGURATION_ABSENT", "absent")

        def should_not_call(*args):
            called.append(True)
            raise AssertionError("provider call must not occur")

        result = live.execute_live(
            value, MAIN_SHA, runtime(), {},
            context_check=lambda _: {},
            credential_factory=no_credential,
            call_once=should_not_call,
        )
        self.assertFalse(called)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["failure_code"], "WIF_CONFIGURATION_ABSENT")
        self.assertTrue(result["fallback"]["deterministic_task_context_usable"])
        self.assertEqual(result["fallback"]["semantic_materialization"], "none")

    def test_rate_limit_retries_are_bounded(self):
        value = live_request()
        attempts = []

        def rate_limited(*args):
            attempts.append(1)
            raise live.LiveBoundaryError("RATE_LIMITED", "req_rate")

        result = live.execute_live(
            value, MAIN_SHA, runtime(), {},
            context_check=lambda _: {},
            credential_factory=lambda _: credential(),
            call_once=rate_limited,
        )
        self.assertEqual(len(attempts), value["semantic_input"]["budgets"]["max_attempts"])
        self.assertEqual(result["failure_code"], "RETRY_EXHAUSTED")
        self.assertEqual(result["provider"]["rate_limit_classification"], "http_429")

    def test_timeout_retries_are_bounded(self):
        value = live_request()
        attempts = []

        def timeout(*args):
            attempts.append(1)
            raise live.LiveBoundaryError("TIMEOUT", "provider_timeout")

        result = live.execute_live(
            value, MAIN_SHA, runtime(), {},
            context_check=lambda _: {},
            credential_factory=lambda _: credential(),
            call_once=timeout,
        )
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["failure_code"], "RETRY_EXHAUSTED")

    def test_malformed_response_retries_then_degrades(self):
        value = live_request()
        attempts = []
        malformed = {"id": "bad", "output": [], "usage": {}}

        def bad(*args):
            attempts.append(1)
            return malformed, "req_bad", 1

        result = live.execute_live(
            value, MAIN_SHA, runtime(), {},
            context_check=lambda _: {},
            credential_factory=lambda _: credential(),
            call_once=bad,
        )
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result["failure_code"], "RETRY_EXHAUSTED")

    def test_verifier_rejection_is_fail_closed(self):
        value = live_request()
        rejected = valid_output(value["semantic_input"])
        rejected["classification"] = "authoritative"

        def call_once(*args):
            response = response_for(value)
            response["output"][0]["content"][0]["text"] = json.dumps(rejected)
            return response, "req_reject", 2

        result = live.execute_live(
            value, MAIN_SHA, runtime(), {},
            context_check=lambda _: {},
            credential_factory=lambda _: credential(),
            call_once=call_once,
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["failure_code"], "VERIFIER_REJECTED")
        self.assertFalse(result["verification"]["materialization_allowed"])
        self.assertEqual(result["fallback"]["semantic_materialization"], "none")

    def test_public_data_violation_is_rejected_before_credential(self):
        value = live_request()
        prompt = value["semantic_input"]["llm_provenance"]["prompt"]
        prompt["rendered_text"] = "authorization: bearer secret-secret-secret-secret"
        prompt["rendered_sha256"] = sc.sha256_bytes(prompt["rendered_text"].encode())
        value["semantic_input"]["transform_id"] = sc.expected_transform_id(value["semantic_input"])
        value["request_id"] = live.expected_request_id(value)
        called = []
        with self.assertRaises(live.LiveBoundaryError):
            live.execute_live(
                value, MAIN_SHA, runtime(), {},
                context_check=lambda _: {},
                credential_factory=lambda _: called.append(True),
                call_once=lambda *args: None,
            )
        self.assertFalse(called)

    def test_oidc_claim_binding_and_token_exchange_metadata(self):
        claims = {
            "iss": live.OIDC_ISSUER,
            "aud": live.OIDC_AUDIENCE,
            "sub": live.OIDC_SUBJECT,
            "repository": live.REPOSITORY,
            "ref": live.REF,
            "workflow_ref": live.WORKFLOW_REF,
            "event_name": "workflow_dispatch",
        }
        token = jwt_for(claims)
        env = {
            "OPENAI_IDENTITY_PROVIDER_ID": "idp_123",
            "OPENAI_SERVICE_ACCOUNT_ID": "svc_123",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.invalid/oidc",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "github-runtime-secret",
        }
        got = live.acquire_wif_credential(
            env,
            oidc_fetch=lambda *_: token,
            exchange=lambda *_: {
                "access_token": "ephemeral",
                "token_type": "Bearer",
                "expires_in": 900,
                "scope": "api.model.request",
            },
        )
        self.assertEqual(got["scope"], ["api.model.request"])
        self.assertEqual(got["expires_in_seconds"], 900)
        self.assertNotEqual(got["identity_provider_id_sha256"], "idp_123")
        self.assertNotEqual(got["service_account_id_sha256"], "svc_123")

        bad = dict(claims, ref="refs/pull/1/merge")
        with self.assertRaises(live.LiveBoundaryError):
            live.validate_oidc_claims(bad)

    def test_wif_scope_and_lifetime_are_fail_closed(self):
        claims = {
            "iss": live.OIDC_ISSUER,
            "aud": live.OIDC_AUDIENCE,
            "sub": live.OIDC_SUBJECT,
            "repository": live.REPOSITORY,
            "ref": live.REF,
            "workflow_ref": live.WORKFLOW_REF,
        }
        env = {
            "OPENAI_IDENTITY_PROVIDER_ID": "idp_123",
            "OPENAI_SERVICE_ACCOUNT_ID": "svc_123",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.invalid/oidc",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runtime",
        }
        token = jwt_for(claims)
        with self.assertRaises(live.LiveBoundaryError):
            live.acquire_wif_credential(
                env,
                oidc_fetch=lambda *_: token,
                exchange=lambda *_: {
                    "access_token": "ephemeral",
                    "token_type": "Bearer",
                    "expires_in": 900,
                    "scope": "api.model.request api.vector_stores.read",
                },
            )
        with self.assertRaises(live.LiveBoundaryError):
            live.acquire_wif_credential(
                env,
                oidc_fetch=lambda *_: token,
                exchange=lambda *_: {
                    "access_token": "ephemeral",
                    "token_type": "Bearer",
                    "expires_in": 7200,
                    "scope": "api.model.request",
                },
            )

    def test_provenance_contains_digests_not_raw_prompt_or_tokens(self):
        value = live_request()
        provenance = live.sanitized_provenance(value, MAIN_SHA)
        self.assertEqual(provenance["model_id"], value["semantic_input"]["llm_provenance"]["model"]["model_id"])
        self.assertEqual(provenance["prompt_rendered_sha256"], value["semantic_input"]["llm_provenance"]["prompt"]["rendered_sha256"])
        self.assertRegex(provenance["structured_output_schema_sha256"], r"^[0-9a-f]{64}$")
        encoded = json.dumps(provenance)
        self.assertNotIn(value["semantic_input"]["llm_provenance"]["prompt"]["rendered_text"], encoded)
        self.assertNotIn("access_token", encoded)


if __name__ == "__main__":
    unittest.main()
