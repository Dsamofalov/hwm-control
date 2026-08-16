# ADR 0003: Trusted compiler-backed task-context blob staging

Status: accepted for I09-0056.

## Context

The merged I09 deterministic compiler can produce a canonical `hwm-task-context-pack/v1` whose `context.json` is larger than the client/connector inline argument boundary. The merged task-context publisher intentionally accepts a pre-existing exact Git blob SHA and must not be widened into a large-byte upload transport.

Issue #56 therefore introduces a recurring staging primitive. The caller sends only a small canonical `hwm-task-context-stage-request/v1`; trusted protected code reconstructs the exact pack and stores the bytes as an unattached Git blob in `Dsamofalov/hwm-context`. The existing `hwm-task-context-publish-request/v1` remains unchanged and can later consume that returned blob SHA.

## Decision

### Forward-only contracts

Two new contracts are introduced:

- `hwm-task-context-stage-request/v1`;
- `hwm-task-context-stage-result/v1`.

The merged `hwm-task-context-request/v1`, `hwm-task-context-pack/v1`, `hwm-task-context-publish-request/v1`, and `hwm-task-context-publish-result/v1` are immutable predecessors and are not retroactively widened.

The stage request contains the complete canonical source `hwm-task-context-request/v1` plus small expected identity and provenance fields. It never contains generated `context.json` bytes.

### Trusted code binding

The staging workflow is defined only on protected `Dsamofalov/hwm-context/main`. It checks out that protected revision with a fully pinned `actions/checkout` SHA and `persist-credentials: false`.

Before compiler checkout, the stager independently observes protected `Dsamofalov/hwm-control/main` and requires it to equal the stage request's exact `expected_control_main`. It then checks out that exact protected commit and verifies the exact Git blobs for:

- `control/task_context_compiler.py`;
- `control/task_context_core.py`;
- `schemas/task-context-request.v1.schema.json`;
- `schemas/task-context-pack.v1.schema.json`.

Only the trusted `control.task_context_compiler.compile_task_context` callable from that exact checkout is imported. Candidate branch or PR-head compiler/stager code is rejected and never imported or executed. Generated context is inert bytes only.

### Independent source provider

The stager supplies the compiler with a read-only public GitHub provider. The provider independently observes protected/current heads and exact issue/blob inputs. It permits only the repositories required by I09:

- `Dsamofalov/hwm-control`;
- `Dsamofalov/hwm-context`;
- `Dsamofalov/hwm_predictor`.

The existing compiler remains authoritative for exact issue snapshot equality, project-state, historical-ledger and Knowledge Delta commit/path/blob/content checks, product `must_equal_current` freshness, public-data rejection, deterministic selection, and canonical serialization.

Each accepted request is compiled twice from identical exact inputs. The two byte streams must be identical. The stager then requires exact equality with the expected source request id, canonical source-request SHA-256, context SHA-256 and Git blob SHA-1 supplied by the stage request. The resulting canonical pack must be no larger than the existing task-context publisher `MAX_BLOB_BYTES = 4194304` boundary.

### GitHub coarse permission limitation and operational confinement

GitHub does not provide endpoint-level `GITHUB_TOKEN` permission for `POST /git/blobs`. Creating a Git blob requires the coarse `contents: write` permission class, and the same class is theoretically capable of Git-ref operations.

For I09-0056 this platform limitation is explicitly accepted. The distinction is:

1. the platform capability exposed by GitHub's coarse token permission;
2. the operational authority granted by the protected staging workflow and runtime contract;
3. the API operations actually implemented and executed.

A short-lived repository-scoped built-in `GITHUB_TOKEN` with job-scoped `contents: write` is allowed only in the trusted protected stager. `issues: write` is allowed only so that the normalized result can be posted to the exact transport Issue. No PAT, deploy key, GitHub App secret/credential, user-provided credential, or other long-lived token is introduced.

The residual theoretical ref capability is accepted, but it is not operational authority. The credentialed uploader has a closed constant API surface. Its only permitted mutations are:

- `POST /repos/Dsamofalov/hwm-context/git/blobs`;
- `POST /repos/Dsamofalov/hwm-context/issues/27/comments` for the normalized result.

The uploader contains no generic arbitrary method/path/repository request function. Repository, methods, paths, and transport Issue are constants rather than request-controlled strings. Ref, tree, commit, Contents-file, pull-request, status, check, workflow-dispatch, ruleset, release, tag, default-branch, and protected-main mutations are forbidden even as code paths.

Compiler/provider/validation steps receive no GitHub token through their environment. The token is exposed only to the single minimal credentialed upload/result step. `actions/checkout` uses `persist-credentials: false`.

Static tests must reject uploader references to `/git/refs`, `/git/trees`, `/git/commits`, `/pulls`, `/statuses`, `/actions/`, Contents-file mutation APIs, workflow dispatch, rulesets, or releases. Workflow tests must prove the staging job has only `contents: write` and `issues: write`, and no `pull-requests`, `actions`, `statuses`, `checks`, or workflow write permission.

### Mutation boundary

Successful staging creates one content-addressed unattached Git blob object and one normalized result comment. It creates or changes no ref, branch, tree, commit, tag, PR, status/check, review, approval, merge, ruleset, release, workflow run dispatch, or protected-main state.

Live acceptance compares complete ref inventory before and after staging and proves exact equality. It also proves protected main, PR inventory and statuses did not change because of the staging path.

### Idempotency and concurrency

The workflow concurrency key is repository plus normalized stage request id and uses `cancel-in-progress: false`.

The normalized request fingerprint is SHA-256 over canonical JSON of the complete validated stage request. Transport history is trusted only when the comment author is the exact allowlisted caller for requests or exact `github-actions[bot]` identity for results.

For a stage request id:

- an exact prior successful result with the same normalized fingerprint is immutable replay evidence; replay returns the same content-addressed blob and provenance with `idempotent_replay=true` and performs no second blob-creation POST;
- prior trusted request/result evidence with the same request id but a different normalized fingerprint fails closed as `REQUEST_ID_REUSE`;
- failed or incomplete results never count as successful replay evidence;
- multiple successful results for the same request/fingerprint must agree on source-request, compiler, observations and artifact provenance or the request fails closed.

Content-addressed Git object reuse is acceptable only when the exact compiled bytes, expected digest identities, prior successful result and readback proof all agree.

### Result provenance

`hwm-task-context-stage-result/v1` records at least:

- stage request id and normalized fingerprint;
- exact observed control/context/product heads;
- issue snapshot and exact project-state, historical-ledger and Knowledge Delta bindings;
- exact source task-context request id and SHA-256;
- exact compiler/core/request-schema/pack-schema Git blob provenance;
- compile pass count and byte-equality proof;
- context byte length, SHA-256 and Git blob SHA-1;
- unattached blob creation and byte-exact readback proof;
- idempotent replay state;
- typed error or null;
- request-comment/workflow/result-author transport provenance.

### Compatibility with unchanged publisher

Staging never invokes publication. The returned `git_blob_sha` is later used unchanged as `artifact.blob_sha` in the already merged `hwm-task-context-publish-request/v1`. Disposable acceptance must prove that the existing publisher accepts that staged blob through its normal scoped branch/PR/CI/strict-status path, after which the disposable publication PR is closed unmerged and its scoped branch is cleaned.

## Rejected alternatives

- Retrofitting generated bytes into `hwm-task-context-publish-request/v1`: rejected as retroactive contract widening.
- Client-side one-time Git blob upload: rejected because it does not close the recurring production capability gap.
- PAT, deploy key or GitHub App credential: rejected because the repository-scoped short-lived built-in token is sufficient.
- Treating coarse `contents: write` theoretical ref capability as a terminal blocker: rejected by owner architecture correction; operational confinement is enforced in code, workflow permissions, static tests and live zero-delta evidence.
- Giving the stager pull-request, status, actions or workflow-dispatch authority: rejected as unnecessary authority widening.

## Consequences

The staging path is a durable trusted primitive with a deliberately tiny mutation surface. GitHub's coarse token scope remains a documented residual platform risk, while repository-controlled runtime code and live evidence enforce the narrower operational boundary required by I09-0056.
