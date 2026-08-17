# ADR 0007: I10 Graphify supply chain and graph contracts

Status: Accepted for I10-P0 (#72)

## Authority
Graphify is derived, rebuildable navigation/impact data only. It is never authority for product/repository SHA, CI, issue lifecycle, readiness/ownership, provenance, requirements, merge authority, or protected project state. A graph is usable only when `snapshot.product_sha == requested_product_sha`. No timestamp, branch-name, latest, or heuristic freshness is allowed. Missing, stale, malformed, incompatible, or unhealthy Graphify falls back deterministically to raw protected sources and is not evidence about correctness/completion.

## Supply chain
Pin `Graphify-Labs/graphify` tag `v0.9.38`, commit `10ad921b423b767dd8a947bbf0fbcc2e95038ad3`, package `graphifyy==0.9.38`. Accept only wheel `graphifyy-0.9.38-py3-none-any.whl` SHA-256 `1335aa0805565279208a47059f8cb0994970ec3dd2155d753d12da425b9d7ee5`. The known sdist SHA-256 is recorded in the supply-chain manifest but source-build/artifact substitution is rejected. License is Apache-2.0; retain `LICENSE`, `LICENSE-MIT`, and `NOTICE`.

Use exact CPython 3.12.10 on Linux x86_64 in a disposable GitHub-hosted job. The immutable upstream `uv.lock` at the pinned commit is the dependency-lock source. Select only its default closure for this runtime; every direct/transitive distribution must be exact-versioned and SHA-256 verified. Optional extras/dev groups and floating build-time resolution are forbidden. Dependency acquisition is a separate allowlisted-network phase; install from a verified local wheelhouse with resolution disabled. Extraction runs only after network denial.

## Structural-only execution
Exact command: `python -m graphify extract . --code-only --no-cluster --no-viz`.

Upstream v0.9.38 documents code extraction as local tree-sitter AST with no LLM/API call, separates semantic/provider/MCP/database capabilities into optional extras, and contains `tests/test_extract_code_only_cli.py` for the code-only command without provider keys. HWM additionally requires the provider/remote-service environment deny policy in `contracts/graphify-supply-chain.v1.json`.

Run only against a read-only product checkout treated as untrusted data. Never execute product hooks, scripts, installs, tests, builds, binaries, or repository-provided commands. Do not install Graphify hooks/skills, start servers, run semantic/docs/media processing, or push to remote databases.

## Canonical snapshot
`hwm-graph-snapshot/v1` stores normalized structural nodes/edges. Paths are UTF-8 NFC, POSIX `/`, repository-relative; reject absolute, parent/current-segment, backslash, temp, runner, and host-specific paths. Unknown/unstable upstream fields are excluded.

Node ID is SHA-256 of `node\0{kind}\0{path}\0{qualified_name}\0{start_line}\0{end_line}`. Edge ID is SHA-256 of `edge\0{source}\0{target}\0{kind}`. Nodes sort by `(path,kind,qualified_name,start_line,end_line,id)`; edges by `(source,target,kind,id)`. Canonical JSON is UTF-8, sorted keys, compact, no BOM or trailing newline.

Canonical identity binds exact product repository/SHA, exact supply chain/runtime/build mode, canonicalization version, nodes, and edges. Wall-clock/generated timestamps, temp/runner paths, random IDs, and workflow observations are excluded and belong only to `hwm-graph-metadata/v1`. Maximum canonical snapshot size is exactly 67,108,864 bytes.

## Determinism, health, queries
P1 must perform at least three clean isolated builds of the same synthetic structural fixture with the exact supply chain/runtime/options; canonical digests must match. Irreducible nondeterminism yields `nondeterministic_rebuild`, no production-looking snapshot, raw-source fallback, and separate remediation/upstream-selection work.

Health states are `healthy_current`, `stale_product_sha`, `unsupported_schema`, `unsupported_upstream`, `malformed_snapshot`, `digest_mismatch`, `oversized_artifact`, `timeout_incomplete_build`, `nondeterministic_rebuild`, `incompatible_upstream_output`. `usable=true` is legal only for `healthy_current` after schema/upstream/digest/size checks and exact product-SHA equality.

`hwm-graph-query/v1` permits only symbol/file neighborhood, shortest dependency path, likely impacted tests, PR impact slice, and related components. No arbitrary graph language or mutation. Global response limits: 500 nodes, 1,000 edges, 1,048,576 bytes. Input limits: neighborhood <=32 seeds/depth<=2; shortest path one source+target/max 8 hops; impacted-tests <=200 changed paths/symbols and <=200 results; PR impact <=200 changed paths; related-components <=20 seeds and <=100 results. Stable canonical ordering is mandatory; over-budget requests fail closed.

## Placement
Future builder (#73): `hwm-lab`, disposable runner. Contracts/policy: `hwm-control`. Future generated snapshot/metadata/health: `hwm-context` derived read model. Future publication authority (#74): narrow typed `hwm-control` publisher with exact binding, CAS, idempotency, strict path allowlist, branch+PR only, no bypass/product mutation/arbitrary writes. Future query integration (#75): read-only derived surfaces governed by these contracts; persistent MCP/server deployment is not authorized.

I10-P0 defines contracts only; it does not implement the builder, publisher, query engine, or production graph.
