import unittest
from control.context_ledger_publisher_contract import (
    ALLOWED_REPOSITORY, BOOTSTRAP_REQUEST_SCHEMA, REQUEST_SCHEMA, TRANSPORT_ISSUE,
    HistoricalLedgerPublishError, classify_replay, git_blob_sha, request_fingerprint,
    result_success, validate_public_blob, validate_request, verify_expected_base,
)

def request():
    a=git_blob_sha(b"claims\n"); b=git_blob_sha(b"conflicts\n")
    return {"schema":REQUEST_SCHEMA,"request_id":"I08-0037-contract-vector","repository":ALLOWED_REPOSITORY,"transport_issue":TRANSPORT_ISSUE,"expected_base":"8"*40,"publication_branch":"publisher/historical-ledger/i08-0037-contract-vector","changes":[{"op":"add","path":"claims/claims.jsonl","blob_sha":a,"mode":"100644"},{"op":"add","path":"claims/conflicts.json","blob_sha":b,"mode":"100644"}],"ci":{"workflow":"repository-bootstrap-ci.yml","required_check":"bootstrap"}}

class ContextLedgerPublisherContractTests(unittest.TestCase):
    def test_valid_request(self): self.assertEqual(validate_request(request())["schema"], REQUEST_SCHEMA)
    def test_bootstrap_v1_rejected(self):
        r=request(); r["schema"]=BOOTSTRAP_REQUEST_SCHEMA
        with self.assertRaises(HistoricalLedgerPublishError): validate_request(r)
    def test_wrong_repository_rejected(self):
        r=request(); r["repository"]="Dsamofalov/hwm-control"
        with self.assertRaises(HistoricalLedgerPublishError): validate_request(r)
    def test_forbidden_paths_and_protected_target_rejected(self):
        r=request(); r["changes"][0]["path"]=".github/workflows/pwn.yml"
        with self.assertRaises(HistoricalLedgerPublishError): validate_request(r)
        r=request(); r["publication_branch"]="main"
        with self.assertRaises(HistoricalLedgerPublishError): validate_request(r)
    def test_malformed_blob_rejected(self):
        r=request(); r["changes"][0]["blob_sha"]="deadbeef"
        with self.assertRaises(HistoricalLedgerPublishError): validate_request(r)
    def test_stale_head_rejected(self):
        with self.assertRaises(HistoricalLedgerPublishError): verify_expected_base(request(), "7"*40)
    def test_fingerprint_and_replay(self):
        r=request(); fp=request_fingerprint(r)
        self.assertEqual(classify_replay(r, [], []), "new")
        self.assertEqual(classify_replay(r, [r], [{"request_id":r["request_id"],"request_fingerprint":fp}]), "replay")
        changed=request(); changed["expected_base"]="7"*40
        with self.assertRaises(HistoricalLedgerPublishError): classify_replay(changed, [r], [])
    def test_unsafe_payload_rejected(self):
        with self.assertRaises(HistoricalLedgerPublishError): validate_public_blob(b"Authorization: Bearer secret")
    def test_success_result_binds_exact_head_ci(self):
        r=request(); out=result_success(r,commit_sha="9"*40,pr_number=12,run_id=34)
        self.assertEqual(out["ci_dispatch"]["head_sha"], "9"*40)
        self.assertEqual(out["ci_dispatch"]["required_check"], "bootstrap")

if __name__ == "__main__": unittest.main()
