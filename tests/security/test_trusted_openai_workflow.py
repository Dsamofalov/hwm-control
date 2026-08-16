from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
LIVE = ROOT / ".github" / "workflows" / "trusted-openai-live.yml"
CI = ROOT / ".github" / "workflows" / "infrastructure-ci.yml"
ADR = ROOT / "docs" / "ADR" / "0005-trusted-openai-execution-boundary.md"
BOUNDARY = ROOT / "control" / "openai_live_boundary.py"


class TrustedOpenAIWorkflowSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.live = LIVE.read_text(encoding="utf-8")
        cls.ci = CI.read_text(encoding="utf-8")
        cls.adr = ADR.read_text(encoding="utf-8")
        cls.boundary = BOUNDARY.read_text(encoding="utf-8")

    def test_live_trigger_is_dispatch_only(self):
        self.assertIn("workflow_dispatch:", self.live)
        self.assertNotIn("pull_request:", self.live)
        self.assertNotIn("pull_request_target:", self.live)
        self.assertNotIn("\n  push:", self.live)
        self.assertNotIn("workflow_call:", self.live)

    def test_dispatch_cannot_select_code_ref_path_or_command(self):
        inputs = self.live.split("permissions:", 1)[0]
        self.assertIn("request_id:", inputs)
        for forbidden in ("ref:", "path:", "command:", "script:", "workflow:"):
            self.assertNotIn(forbidden, inputs)
        self.assertIn("ref: ${{ github.sha }}", self.live)
        self.assertIn("github.ref == 'refs/heads/main'", self.live)
        self.assertIn("github.ref_protected", self.live)
        self.assertIn("github.repository == 'Dsamofalov/hwm-control'", self.live)

    def test_oidc_permission_exists_only_in_live_job(self):
        self.assertEqual(self.live.count("id-token: write"), 1)
        preflight = self.live.split("\n  live:", 1)[0]
        self.assertNotIn("id-token: write", preflight)
        self.assertIn("needs: preflight", self.live)

    def test_no_openai_secret_or_secret_expression(self):
        for text in (self.live, self.ci, self.boundary):
            self.assertNotIn("OPENAI_API_KEY", text)
            self.assertNotIn("secrets.", text)
        self.assertIn("vars.OPENAI_IDENTITY_PROVIDER_ID", self.live)
        self.assertIn("vars.OPENAI_SERVICE_ACCOUNT_ID", self.live)

    def test_pr_ci_is_offline_and_has_no_oidc(self):
        self.assertIn("pull_request:", self.ci)
        self.assertNotIn("id-token: write", self.ci)
        self.assertNotIn("openai_live_boundary.py execute", self.ci)
        self.assertNotIn("OPENAI_IDENTITY_PROVIDER_ID", self.ci)
        self.assertNotIn("OPENAI_SERVICE_ACCOUNT_ID", self.ci)
        self.assertNotIn("auth.openai.com", self.ci)
        self.assertNotIn("api.openai.com", self.ci)

    def test_no_pr_artifact_or_cache_handoff(self):
        lowered = self.live.lower()
        for forbidden in (
            "actions/cache",
            "upload-artifact",
            "download-artifact",
            "pull_request",
            "pull_request_target",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_exact_main_reverification_precedes_execute(self):
        verify = self.live.index("Reverify exact protected main before OIDC exposure")
        execute = self.live.index("Execute protected WIF boundary")
        self.assertLess(verify, execute)
        self.assertIn("/git/ref/heads/main", self.live)
        self.assertIn("observed != expected", self.live)

    def test_provider_request_disables_tools_and_storage(self):
        self.assertIn('"tools": []', self.boundary)
        self.assertIn('"store": False', self.boundary)
        self.assertIn('"strict": True', self.boundary)
        self.assertIn('"type": "json_schema"', self.boundary)

    def test_no_raw_prompt_output_artifact_or_cache_logging(self):
        self.assertNotIn("upload-artifact", self.live)
        self.assertNotIn("actions/cache", self.live)
        self.assertIn("Digest/status-only output", self.boundary)
        allowed = re.search(
            r"_ALLOWED_LOG_FIELDS = \((.*?)\)\n\n",
            self.boundary,
            flags=re.S,
        )
        self.assertIsNotNone(allowed)
        fields = allowed.group(1)
        self.assertNotIn("rendered_text", fields)
        self.assertNotIn("raw_output", fields)
        self.assertNotIn("authorization", fields.lower())

    def test_auth_binding_is_exact_and_least_privilege(self):
        expected = (
            "repo:Dsamofalov@25666939/hwm-control@1333400971:"
            "ref:refs/heads/main"
        )
        self.assertIn(expected, self.boundary)
        self.assertIn(
            "Dsamofalov/hwm-control/.github/workflows/"
            "trusted-openai-live.yml@refs/heads/main",
            self.boundary,
        )
        self.assertIn('REQUIRED_WIF_SCOPE = ("api.model.request",)', self.boundary)
        self.assertNotIn("api.admin", self.boundary)

    def test_rotation_and_activation_are_durable_policy(self):
        for phrase in (
            "Disable the live boundary",
            "Revoke the service-account mapping",
            "prove a fresh token exchange is denied",
            "organization owner",
            "api.model.request",
            "finite project spend limit",
        ):
            self.assertIn(phrase, self.adr)


if __name__ == "__main__":
    unittest.main()
