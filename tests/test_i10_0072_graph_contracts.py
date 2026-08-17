import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def load(p): return json.loads((ROOT / p).read_text(encoding="utf-8"))

def test_supply_chain_exact_and_structural_only():
    m=load("contracts/graphify-supply-chain.v1.json")
    assert m["upstream_repository"]=="Graphify-Labs/graphify"
    assert m["upstream_tag"]=="v0.9.38"
    assert m["upstream_commit"]=="10ad921b423b767dd8a947bbf0fbcc2e95038ad3"
    assert m["package"]["name"]=="graphifyy"
    assert m["package"]["accepted_artifact"]["sha256"]=="1335aa0805565279208a47059f8cb0994970ec3dd2155d753d12da425b9d7ee5"
    assert m["runtime"]["version"]=="3.12.10"
    assert m["dependency_lock"]["hashes_required"] is True
    assert m["dependency_lock"]["build_time_resolution"]=="forbidden"
    assert m["dependency_lock"]["optional_extras"]==[]
    assert m["execution"]["command"]==["python","-m","graphify","extract",".","--code-only","--no-cluster","--no-viz"]
    assert m["execution"]["semantic_docs_models"]=="forbidden"
    assert m["execution"]["mcp_server"]=="forbidden"
    assert m["execution"]["remote_database_push"]=="forbidden"
    assert m["max_snapshot_bytes"]==67108864

def test_identity_excludes_observational_metadata():
    s=load("schemas/graph-snapshot.v1.schema.json")
    assert s["properties"]["schema"]["const"]=="hwm-graph-snapshot/v1"
    assert "generated_at" not in s["properties"]
    assert s["properties"]["canonicalization"]["const"]=="hwm-graph-canonical/v1"
    md=load("schemas/graph-metadata.v1.schema.json")
    assert md["properties"]["generated_at"]["description"].startswith("Observational only")

def test_health_fail_closed_states():
    h=load("schemas/graph-health.v1.schema.json")
    assert set(h["properties"]["state"]["enum"])=={"healthy_current","stale_product_sha","unsupported_schema","unsupported_upstream","malformed_snapshot","digest_mismatch","oversized_artifact","timeout_incomplete_build","nondeterministic_rebuild","incompatible_upstream_output"}
    assert {"requested_product_sha","snapshot_product_sha","usable"}<=set(h["required"])

def test_query_contract_bounded_read_only():
    q=load("schemas/graph-query.v1.schema.json")
    assert set(q["properties"]["query"]["enum"])=={"symbol_file_neighborhood","shortest_dependency_path","likely_impacted_tests","pr_impact_slice","related_components"}
    lim=q["properties"]["limits"]["properties"]
    assert lim["max_nodes"]["maximum"]==500
    assert lim["max_edges"]["maximum"]==1000
    assert lim["max_response_bytes"]["const"]==1048576
