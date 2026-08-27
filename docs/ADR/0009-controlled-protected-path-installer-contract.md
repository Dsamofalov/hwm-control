# ADR 0009: Controlled protected-path installer contract and one-time P0B bootstrap

- **Status:** Accepted
- **Date:** 2026-08-27
- **Milestone:** I10 Graphify
- **Decision Issue:** Dsamofalov/hwm-control#86
- **Implementation barrier:** Dsamofalov/hwm-control#87
- **Runtime prerequisite:** Dsamofalov/hwm-control#85

## Context

The repository-local ordinary task-branch publisher intentionally rejects `.github/workflows/**`,
`.github/actions/**`, `CODEOWNERS`, protected/default-branch targets, publisher-owned paths and other
self-modifying trust surfaces. That denial is part of the accepted `hwm-publish-request/bootstrap-v1`
boundary and must not be widened for Issue #85.

Issue #73 is paused because its real Graphify acceptance requires exact CPython 3.12.10, which is not
present on the GitHub-hosted runner used by source-v3 CI. Installing the narrow trusted acceptance
workflow/runtime capability required by #85 therefore needs a separate protected-path installation
primitive. The completed #79 publisher self-installation exception was one-time and is not reusable.

## Decision

Introduce two forward-only interfaces, independent of the ordinary publisher:

- `hwm-protected-path-install-request/bootstrap-v1`;
- `hwm-protected-path-install-result/bootstrap-v1`.

The protected-path installer is repository-local, typed and fail-closed. It is available only to an
open, claimed architecture Issue carrying `architecture`, `trusted`, and `contract`. Each request
binds the repository, architecture Issue, task id, dedicated installation branch, expected branch
HEAD, exact protected-main base SHA, exact normalized Issue-declared path allowlist, regular-file
add/replace operations, exact Git blob identities, replace preconditions, commit message, and the
trusted validation workflow/check association.

### Authority boundary

The installer may construct inert Git blobs/trees/commits and compare-and-set only the dedicated
non-default installation branch. It has no authority to:

- update the default/protected branch;
- approve or merge a pull request;
- mutate rulesets, repository settings, secrets or environments;
- delete, rename, create symlinks or gitlinks/submodules;
- execute free-form shell supplied by the request;
- execute or interpret candidate protected workflow/action bytes.

Actor/author association, repository/Issue/task/branch identity, required Issue labels, exact
protected-main base, expected-head CAS, path normalization, object type/mode, replace old-blob
precondition, deterministic request fingerprint, and request-id replay semantics are all verified
before branch mutation. A byte-identical successful replay returns the existing result without a
second ref move or validation dispatch; a reused request id with different normalized bytes is
rejected.

### Initial protected path class

Bootstrap-v1 may add or replace only exact paths enumerated by the owning architecture Issue under:

- `.github/workflows/**`;
- `.github/actions/**`.

Even when Issue-declared, bootstrap-v1 always rejects:

- the protected-path installer's own workflow/backend/policy/contracts;
- the ordinary task-branch publisher workflow/backend/policy/contracts;
- the existing required bootstrap workflow;
- every `CODEOWNERS`;
- ruleset/repository-settings paths;
- secret/environment configuration;
- the default branch or any request that targets it;
- undeclared paths and non-regular-file mutation shapes.

This is a semantic policy boundary in addition to the JSON Schema syntax boundary.

### Candidate-content non-execution

Privileged installer code and policy are loaded only from protected `main`. Candidate blobs are
resolved by exact Git object identity and treated as inert bytes. The installer must never check out,
import, source, render as executable configuration, invoke, or otherwise execute candidate content.

A candidate workflow remains untrusted data until protected merge. It cannot mint its own trusted
credential or publish its own acceptance verdict.

### Trusted validation and protected merge

Before a protected PR is eligible:

1. exact path/mode/blob inventory is read back from the candidate head;
2. trusted/static validation sourced from protected `main` validates the candidate bytes by exact SHA;
3. candidate workflows are constrained to minimum permissions, no secrets, and full commit-SHA pins
   for every external Action;
4. the existing required `bootstrap` check remains unchanged and succeeds on the exact PR head;
5. mergeability is clean, requested changes are absent, unresolved review threads are zero, and the
   validated head has not moved.

If a token-created PR suppresses a normal PR-triggered trusted validation event, the allowed recovery
is an explicit protected-main `workflow_dispatch` plus exact status/head association. `pull_request_target`
must not be used to execute candidate content.

A newly installed candidate workflow may be dispatched only after it has merged to protected `main`
and the dispatch is bound to that exact protected-main state.

## One-time P0B bootstrap exception

Because #87 must install the protected-path installer before that installer exists, #87 receives one
non-reusable bootstrap exception and no other task inherits it.

The exception is limited to one dedicated hwm-lab P0B branch created from an exact verified protected
`main` SHA and one transparent Git-object installation transaction containing only the exact
predeclared protected-installer workflow/backend/policy/schema/test paths approved by #87. The commit
has exactly one parent; the branch update is non-force; protected `main` is never written directly.

The #87 transaction must complete protected PR review, unchanged required CI, exact diff/blob
readback, guarded exact-head merge, post-merge CI, and disposable live acceptance. The exception
expires permanently after #87 whether or not later architecture work would find it convenient.

### Exact #87 bootstrap installation allowlist

The one-time #87 transaction is predeclared to exactly these repository paths and no others:

- `.github/workflows/protected-path-installer.yml`;
- `control/protected_path_installer.py`;
- `control/protected_path_installer_backend.py`;
- `control/protected_path_installer_contract.py`;
- `control/protected_path_installer_policy.py`;
- `control/protected_path_installer_manifest.bootstrap-v1.json`;
- `schemas/protected-path-install-request.bootstrap-v1.schema.json`;
- `schemas/protected-path-install-result.bootstrap-v1.schema.json`;
- `tests/contracts/test_protected_path_install_contracts.py`;
- `tests/security/test_protected_path_installer.py`.

The bootstrap transaction may add or replace only these exact paths as regular blobs. Any need for a
different implementation path requires a new architecture amendment before #87 mutates Git. This
predeclared list does not widen the runtime protected-path installer's own path class; it only bounds
the one transaction that installs that runtime primitive.

This exception does not authorize generic `create_file`/`update_file`/`create_commit` publication,
product mutation, Graphify builder/runtime implementation, graph publication, provider/API/model/
billing capability, or widening the ordinary publisher.

## Required P0B live acceptance

#87 must prove, using only disposable non-production branches/content:

- positive protected-path publication;
- identical request replay with no second mutation or validation dispatch;
- changed payload under a reused request id is rejected;
- stale expected head is rejected without mutation;
- wrong repository, Issue, task, or branch is rejected;
- unauthorized actor is rejected;
- default-branch target is rejected;
- undeclared path is rejected;
- installer self-modification is rejected;
- ordinary publisher modification is rejected;
- existing required bootstrap workflow modification is rejected;
- `CODEOWNERS`, ruleset/settings, and secret/environment paths are rejected;
- every negative case leaves the target ref unchanged.

The disposable candidate workflow is `workflow_dispatch`-only, has `contents: read`, receives no
secrets, is never merged to `main`, and is removed with disposable branch cleanup.

## Consequences

Issue #85 remains blocked and unclaimed until #87 completes. Issue #73 remains open, claimed and
paused on #85. This ADR installs no workflow and selects no CPython acquisition method; those are
outside P0A. The ordinary publisher schemas, implementation, workflows, closed BUILD_STATUS core
schema map, product checkpoint, hwm-lab, hwm-context, and hwm_predictor remain unchanged by #86.
