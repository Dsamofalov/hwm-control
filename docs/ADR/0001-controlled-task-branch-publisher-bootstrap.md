# ADR 0001 — Controlled task-branch publisher bootstrap

- Status: Accepted by merge of I03-P0A
- Task: #12 `I03-P0A: Record controlled task-branch publishing architecture`
- Depends on: completed I02 versioned contracts
- Unblocks contract/implementation task: #13 `I03-P0B: Implement controlled task-branch publisher`

## Context

I03 Issue #3 is legitimately claimed by `agent/infra-0003-product-head-extractor`, but its exact branch head contains only claim bookkeeping. The intended implementation and tests already exist as Git blob objects while the connector execution path cannot safely complete the source publication transaction. This is a bootstrap transport capability gap, not an extractor implementation, test, or CI defect.

The existing merged `hwm-job/v1` and `hwm-result/v1` contracts describe typed control-plane jobs. They are not retroactively widened to carry source publication. Controlled task-branch publication is a separate, intentionally narrow bootstrap primitive.

## Decision

Introduce two separate versioned bootstrap transport schemas:

- `hwm-publish-request/bootstrap-v1`
- `hwm-publish-result/bootstrap-v1`

They are independent of `hwm-job/v1` and `hwm-result/v1`. Any future evolution is versioned explicitly.

The first implementation is hwm-control-only. No write to `hwm-context` or `hwm-lab` is permitted until a separate architecture/contract barrier task for that repository has merged.

## Transport and exact author allowlist

The bootstrap transport is a top-level GitHub Issue comment on the exact task Issue being published.

A request is eligible only when all of the following hold:

1. the comment body contains exactly one `hwm-publish-request/bootstrap-v1` object in the publisher-defined canonical envelope;
2. the comment belongs to the same repository and Issue named by the request;
3. the comment author is exactly the allowlisted owner identity below, matched on both immutable GitHub account id and current login:

```json
[
  {"github_account_id": 25666939, "login": "Dsamofalov"}
]
```

No organization member, collaborator, bot, PR author, task claimant, or workflow actor is implicitly authorized. A change to this allowlist is an architecture/contract change and requires a separate trusted Issue and protected merge.

Publisher result comments are not requests and must never recursively trigger publication.

## `hwm-publish-request/bootstrap-v1`

The normative bootstrap-v1 request shape is:

```json
{
  "schema": "hwm-publish-request/bootstrap-v1",
  "request_id": "pub-0003-01",
  "repository": "Dsamofalov/hwm-control",
  "task_issue": 3,
  "task_branch": "agent/infra-0003-product-head-extractor",
  "expected_head": "6dc0b0539dcc4205ff97711d45580c00f73c9724",
  "changes": [
    {
      "op": "add",
      "path": "control/product_head.py",
      "blob_sha": "b13623aa990ed2bf76d20781ec90a74b1f93a417",
      "mode": "100644"
    },
    {
      "op": "add",
      "path": "tests/test_product_head.py",
      "blob_sha": "302090961f440aceda210d1657976ec26c178e9c",
      "mode": "100644"
    }
  ],
  "ci": {
    "workflow": "infrastructure-ci.yml"
  }
}
```

For `replace`, the change additionally requires `expected_blob_sha` for the path being replaced. An `add` requires the path to be absent at `expected_head`. A `replace` requires the path to be a regular blob with exactly `expected_blob_sha` at `expected_head`.

Bootstrap-v1 allows only `add` and `replace` of regular Git blobs. Allowed regular-file modes are `100644` and `100755`. Delete, rename, copy, directory/tree insertion, symlink mode `120000`, gitlink/submodule mode `160000`, tag/ref creation, and arbitrary tree operations are forbidden.

`request_id` is globally unique within the publisher audit domain. All SHA values are exact lower-case 40-hex Git object ids in bootstrap-v1, matching the current I02 Git-SHA convention.

## Task, Issue, repository, and branch consistency

Before any candidate commit object is created, the publisher must verify all of these facts from GitHub:

- `repository` is exactly an implementation-approved repository; bootstrap-v1 initially permits only `Dsamofalov/hwm-control`;
- `task_issue` is open and carries the `claimed` label;
- the request comment is on exactly `task_issue`;
- `task_branch` exists in the same repository;
- for hwm-control, the branch name begins with `agent/infra-<task_issue zero-padded to four digits>-`;
- the Issue's recorded recovery/task branch, when present, equals `task_branch`;
- the current remote branch head equals `expected_head`.

A mismatch is a hard failure. The publisher never guesses the intended Issue, branch, repository, or current head.

## Expected-head compare-and-set

`expected_head` is mandatory and is the compare value for the only allowed ref mutation.

The new commit must have `expected_head` as its parent. The final ref update must use an atomic lease/compare-and-set primitive whose success is conditional on the remote task branch still being exactly `expected_head`. A generic force push or unconditional ref update is forbidden.

If the branch changes before the compare-and-set completes, the publication fails with `EXPECTED_HEAD_MISMATCH`; no retry with a newly observed head is automatic.

Creating unreachable Git objects before a failed compare-and-set is not publication and must not be reported as success.

## Idempotency

The publisher persists a durable normalized fingerprint for every accepted `request_id`.

- same `request_id` + same normalized request after prior success: return the original successful result as an idempotent replay; do not create another commit, move the ref again, or dispatch CI again;
- same `request_id` + same normalized request while one execution is in progress: join/return the same execution outcome rather than starting a second writer;
- same `request_id` + different normalized request: reject as `REQUEST_ID_REUSE`;
- a semantically identical request with a different `request_id` is still subject to the current-head compare-and-set and therefore cannot silently create duplicate publication after the branch has moved.

## Concurrency semantics

The publisher serializes accepted executions only within the key `(repository, task_branch)`. Distinct task branches may publish concurrently.

The branch-local mutex is an implementation detail that protects one compare-and-set transaction; it is not a project-DAG serialization barrier.

Any new serialization point spanning multiple task branches, Issues, repositories, schemas, or milestones must be introduced only by a separate architecture/contract Issue and protected merge. The publisher must not create hidden global queues or implicit cross-task barriers.

## Forbidden targets and paths

Bootstrap-v1 may never target the repository default branch, `main`, any other protected integration branch, tags, or refs outside the approved claimed task branch.

The publisher rejects every request that would write any of the following:

- `.github/workflows/**`;
- `.github/actions/**`;
- any file named `action.yml` or `action.yaml`;
- any `CODEOWNERS` file at any path;
- publisher implementation, publisher policy, publisher schema/contract enforcement, publisher credential configuration, or other publisher-owned paths defined by the protected publisher manifest;
- ruleset/protection configuration represented in repository files, if any such surface is later introduced.

The publisher-owned path manifest is read from protected trusted publisher code/configuration, never from candidate content or the request.

Publisher self-modification is therefore impossible through this primitive.

## Candidate-content execution prohibition

The publisher never checks out, imports, evaluates, renders as executable configuration, or executes candidate content.

It may inspect Git object metadata and construct a tree/commit from already-existing regular blob object ids. If the trusted publisher workflow checks out code at all, it may check out only the exact trusted protected publisher source, never the candidate task branch or the newly published candidate commit.

Blob contents are data. They are not executed in the publisher security context.

## Explicitly excluded powers

The publisher:

- never writes `main` or the repository default branch;
- never approves, merges, closes, or otherwise decides a pull request;
- never changes branch protection or rulesets;
- never changes repository settings;
- never grants permissions or modifies CODEOWNERS;
- never performs arbitrary shell/PowerShell commands supplied by a request;
- never accepts arbitrary repository/ref/path targets outside bootstrap-v1 policy.

## Explicit exact-head CI dispatch

A successful task-branch ref update is immediately followed by an explicit dispatch of the allowlisted ordinary CI workflow against the exact new task-branch head.

The dispatch must carry both `request_id` and exact `new_head`. CI must independently resolve/verify that it is validating exactly `new_head`; branch-name-only association is insufficient.

Publication is not reported as successful until an exact associated CI run has been identified. The normalized result records the workflow identity, run id, and exact dispatched head. CI completion may happen later, but the run association must already be deterministic.

Ordinary CI is read-only with respect to repository contents, runs without publisher credentials, and does not inherit the publisher's write-capable token/App installation credential. The current hwm-control `bootstrap` job is the protected required check baseline; I03-P0B may add the minimal trusted dispatch entrypoint through its own protected PR without weakening ordinary CI permissions.

## `hwm-publish-result/bootstrap-v1`

The normative success shape is:

```json
{
  "schema": "hwm-publish-result/bootstrap-v1",
  "request_id": "pub-0003-01",
  "status": "success",
  "repository": "Dsamofalov/hwm-control",
  "task_issue": 3,
  "task_branch": "agent/infra-0003-product-head-extractor",
  "expected_head": "6dc0b0539dcc4205ff97711d45580c00f73c9724",
  "observed_head_before": "6dc0b0539dcc4205ff97711d45580c00f73c9724",
  "new_head": "0123456789abcdef0123456789abcdef01234567",
  "commit_sha": "0123456789abcdef0123456789abcdef01234567",
  "changes": [
    {
      "op": "add",
      "path": "control/product_head.py",
      "blob_sha": "b13623aa990ed2bf76d20781ec90a74b1f93a417",
      "mode": "100644"
    }
  ],
  "idempotent_replay": false,
  "ci_dispatch": {
    "workflow": "infrastructure-ci.yml",
    "head_sha": "0123456789abcdef0123456789abcdef01234567",
    "run_id": 123456789
  }
}
```

The normative error shape replaces `new_head`, `commit_sha`, `changes`, and `ci_dispatch` with:

```json
{
  "error": {
    "code": "EXPECTED_HEAD_MISMATCH",
    "message": "sanitized public diagnostic",
    "retryable": false
  }
}
```

Allowed bootstrap-v1 error codes include at least:

- `INVALID_SCHEMA`
- `UNAUTHORIZED_AUTHOR`
- `REPOSITORY_NOT_ALLOWED`
- `TASK_NOT_CLAIMED`
- `BRANCH_TASK_MISMATCH`
- `EXPECTED_HEAD_MISMATCH`
- `FORBIDDEN_TARGET`
- `FORBIDDEN_PATH`
- `PATH_STATE_MISMATCH`
- `BLOB_NOT_FOUND`
- `BLOB_NOT_REGULAR`
- `REQUEST_ID_REUSE`
- `CI_DISPATCH_FAILED`
- `INTERNAL_ERROR`

Failures are explicit and never fabricate a commit, ref update, CI run, or success result.

All result data is safe for the public-data boundary. Credentials, token values, request headers, environment dumps, cookies, sessions, or private data never appear in Issue comments, logs, or artifacts.

## Migration and repository boundaries

This primitive is bootstrapped in `hwm-control` first. The migration sequence is normative in `docs/migration/I03-P0A-controlled-publisher-bootstrap.md`.

Before the first publisher write to `hwm-context`, a separate architecture/contract barrier Issue must define that repository's approved branch/task consistency rules, protected publisher installation, publisher-owned paths, required CI association, and credential scope. The same requirement independently applies to `hwm-lab`.

No hwm-control acceptance result automatically authorizes writes to either repository.

## Relationship to I11

The planned full I11 trusted job bus remains required. I11 extends this narrow, versioned publication primitive where appropriate: richer authenticated transport, broader typed operations, stronger audit/recovery, cross-repository capability policy, and lifecycle management may be layered on top.

I11 must not silently replace bootstrap-v1 with an unrelated unversioned mechanism or retroactively mutate its semantics. Compatibility is handled by explicit new versions and migration.

## Consequences

The immediate design deliberately accepts a narrow capability instead of granting browser agents general write credentials. It is sufficient to resume paused claimed tasks such as Issue #3 after I03-P0B implements and proves the contract, while preserving protected-main governance and leaving the broader I11 design intact.
