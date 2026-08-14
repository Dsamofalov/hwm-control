# I03-P0A Migration — Controlled task-branch publisher bootstrap

## Purpose

Define the staged migration from the current connector publication gap to the narrow `hwm-publish-request/bootstrap-v1` / `hwm-publish-result/bootstrap-v1` primitive without changing merged `hwm-job/v1` semantics.

## Stage 0 — Architecture barrier

Merge Issue #12 through the protected `hwm-control/main` path with documentation only. No publisher implementation, workflow mutation, extractor publication, or product change belongs to this stage.

After merge, the architecture and bootstrap-v1 semantics are authoritative. Issue #13 remains the only implementation task for this primitive.

## Stage 1 — Implement in hwm-control only

Issue #13 may implement only the hwm-control publisher described by ADR 0001.

Its protected PR may add the machine-readable bootstrap-v1 schema files, trusted publisher code, narrowly scoped workflow entrypoint, security tests, and deterministic CI-dispatch association required by the ADR.

The implementation must not modify Issue #3 extractor logic. The selected Issue #3 source/test blobs remain read-only recovery inputs:

- implementation: `b13623aa990ed2bf76d20781ec90a74b1f93a417`
- tests: `302090961f440aceda210d1657976ec26c178e9c`

No replacement blobs are required merely to bootstrap the transport.

## Stage 2 — One-time controlled installation and sandbox proof

Issue #13 must perform a one-time controlled installation/bootstrap activation through owner/admin actions only where GitHub requires permissions or settings that cannot be established by protected repository code itself.

That action must be narrowly scoped and auditable. It must not grant ordinary CI publisher credentials.

Before publication to a real paused task branch, Issue #13 proves in an isolated sandbox/test branch that:

- only the intended claimed task branch can move;
- expected-head mismatch prevents movement;
- forbidden paths/targets are rejected;
- idempotent replay creates no second commit or CI dispatch;
- candidate content is never checked out or executed by the publisher;
- exact-head ordinary CI dispatch is associated with the new head;
- default branch, rulesets, PR merge/review, workflow/action/CODEOWNERS, and publisher-owned paths are outside publisher authority.

## Stage 3 — Resume paused Issue #3

Only after Issue #13 is complete and its acceptance evidence is merged may Issue #3 resume.

The existing task ownership is preserved:

- Issue: #3
- branch: `agent/infra-0003-product-head-extractor`
- recovery expected head at the architecture checkpoint: `6dc0b0539dcc4205ff97711d45580c00f73c9724`

The first real use should publish the already-selected implementation/test blobs under bootstrap-v1, subject to a fresh exact-head check. If the branch head is no longer the expected value, publication fails; the publisher does not automatically rewrite the request against a new head.

After exact publication, the publisher explicitly dispatches ordinary CI against the exact new task-branch head. Issue #3 then continues through its normal PR/protected merge lifecycle.

## Stage 4 — hwm-context barrier

Before the first publisher write to `Dsamofalov/hwm-context`, create and merge a separate architecture/contract barrier task.

That task must define, for hwm-context specifically:

- approved task branch naming and Issue/task authority;
- target repository allowlisting;
- publisher-owned forbidden paths;
- protected installation/credential scope;
- exact required CI or validation association;
- public-data restrictions;
- acceptance and rollback semantics.

Until that barrier is merged and its implementation installed, hwm-control bootstrap-v1 authority does not permit writes to hwm-context.

## Stage 5 — hwm-lab barrier

Before the first publisher write to `Dsamofalov/hwm-lab`, create and merge an independent architecture/contract barrier task with the same repository-specific requirements.

Approval for hwm-context does not authorize hwm-lab and vice versa.

## Stage 6 — I11 extension

Full I11 remains on the infrastructure roadmap. It may extend this primitive with a richer typed job bus, broader capability model, better audit/recovery, and additional trusted transports.

I11 must preserve versioned compatibility. If semantics change, introduce a new contract/version and migration rather than retroactively redefining `hwm-publish-request/bootstrap-v1` or `hwm-publish-result/bootstrap-v1`.

## Rollback and failure rule

A failed publisher request never changes project truth by prose. The task remains owned by its existing Issue/branch, the result is recorded as explicit failure, and recovery starts from the actual remote head.

No automatic fallback to direct push, default-branch write, alternate repository, alternate task branch, or unversioned connector mutation is permitted.
