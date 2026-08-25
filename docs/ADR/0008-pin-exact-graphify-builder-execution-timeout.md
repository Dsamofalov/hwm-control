# ADR 0008: Pin exact Graphify builder execution timeout

## Status

Accepted for I10-P0-R1 / Issue #83.

## Context

I10-P0 / Issue #72 established the exact Graphify supply chain, structural-only execution mode, network phases, maximum snapshot size, graph health state `timeout_incomplete_build`, and fail-closed timeout behavior in `contracts/graphify-supply-chain.v1.json`, ADR 0007, the graph schemas, focused tests, and `knowledge-deltas/I10-0072.json`. Those accepted surfaces did not specify an exact numeric builder execution timeout.

Issue #73 is the implementation task for the disposable exact-SHA structural Graphify builder. It must not choose a correctness- and availability-affecting timeout itself. Allowing the implementation agent to select, infer, default, or silently increase the timeout would make execution behavior depend on implementation discretion rather than a reviewed versioned contract.

Issue #83 therefore remediates only this contract omission. It does not implement or execute Graphify, publish a graph, change product code, widen provider/API/model/billing capability, or mutate `hwm-lab`, `hwm-context`, or `hwm_predictor`.

## Decision

`contracts/graphify-supply-chain.v2.json` is the authoritative Graphify supply-chain contract for Issue #73 and later consumers that require the builder timeout policy. It explicitly supersedes `hwm-graphify-supply-chain/v1` while preserving every v1 upstream, package, license, runtime, dependency-lock, installation, network, structural command, provider-deny, and maximum-size pin.

`contracts/graphify-supply-chain.v1.json` remains the immutable historical predecessor. ADR 0007 remains historical evidence of the P0 decision as it was accepted; neither artifact is rewritten to imply that the numeric value existed at P0 acceptance.

The builder semantic timeout is exactly **900 seconds** of monotonic wall-clock time.

The timer starts only at the exact boundary:

`verified-wheelhouse-ready, network-denied, read-only-exact-source-ready`

At that point the exact source SHA has already been obtained, the exact verified wheelhouse is fully prepared, network access is denied, and the exact product checkout is mounted read-only.

The timer covers the complete builder execution after that boundary: offline installation, the exact structural Graphify invocation `python -m graphify extract . --code-only --no-cluster --no-viz`, output parsing, normalization, schema validation, digest calculation, and canonical artifact emission. The timer ends only at:

`canonical-artifact-emission-complete`

Reaching 900 seconds is a fail-closed result. The execution/process tree is terminated; partial snapshot or metadata output is rejected; partial canonical artifacts are deleted; health is exactly `timeout_incomplete_build`; `usable` is false; snapshot identity is absent/null; publication is forbidden; and the consumer uses deterministic raw-source fallback.

A retry may not reuse partial output. It is a new clean disposable execution with the same exact inputs. A timeout failure does not authorize Issue #73 to increase the timeout. Any future change from 900 seconds requires a new versioned contract amendment.

GitHub Actions job-level containment may exceed 900 seconds only so the job can terminate the execution and durably record the fail-closed health/result. Job-level containment cannot alter, extend, or reinterpret the 900-second semantic builder timeout.

## Consequences

Issue #73 may proceed only against `hwm-graphify-supply-chain/v2` and must implement the exact timeout and fail-closed semantics above. The value is not optional, floating, defaulted, environment-selected, or implementation-selected.

The remediation changes no graph snapshot, metadata, health, or query schema and does not expand the closed core `BUILD_STATUS.current_schema_versions` map. It introduces no product execution authority, provider access, MCP capability, remote database push, API/model credentials, or billing scope.

## References

- Issue #72 — I10-P0 Graphify supply-chain and graph contracts.
- Issue #73 — disposable exact-SHA Graphify builder implementation, blocked on this remediation until completion.
- Issue #83 — I10-P0-R1 exact builder timeout remediation.
- `contracts/graphify-supply-chain.v1.json` — immutable historical predecessor.
- `contracts/graphify-supply-chain.v2.json` — authoritative timeout-amended supply-chain contract for #73+.
