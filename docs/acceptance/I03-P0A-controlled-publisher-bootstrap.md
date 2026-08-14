# I03-P0A Acceptance — Controlled task-branch publisher bootstrap

This document is normative acceptance input for Issue #13. I03-P0A itself is documentation-only and does not implement the publisher.

## Contract acceptance

I03-P0B must provide machine-readable validators for the two architecture-defined contracts:

- `hwm-publish-request/bootstrap-v1`
- `hwm-publish-result/bootstrap-v1`

Positive fixtures must cover valid add, valid replace, success result, error result, and idempotent replay.

Negative fixtures must reject missing/unknown fields, unknown operations, invalid SHA syntax, non-regular modes, delete/rename/copy/tree/gitlink/symlink operations, malformed repository/Issue/branch identities, and request-id reuse with changed normalized content.

The existing `hwm-job/v1` and `hwm-result/v1` schema files and semantics must remain unchanged by the publisher bootstrap contract.

## Transport and authorization acceptance

A publisher request is accepted only as a top-level Issue comment on the exact task Issue and only from the exact author allowlist:

```json
[
  {"github_account_id": 25666939, "login": "Dsamofalov"}
]
```

Tests must prove rejection of:

- a different login/id;
- collaborator/member/bot authors not explicitly allowlisted;
- a request object posted to a different Issue;
- a result comment accidentally matching request-like text;
- malformed or multiple request objects in one comment.

## Task/Issue/branch consistency acceptance

For hwm-control bootstrap-v1, tests must prove that publication requires:

- exact repository `Dsamofalov/hwm-control`;
- open task Issue carrying `claimed`;
- existing branch in the same repository;
- branch prefix `agent/infra-<issue number zero-padded to four digits>-`;
- any Issue-recorded branch identity matching the request;
- remote branch head exactly equal to `expected_head`.

A ready, closed, differently numbered, differently recorded, missing, or cross-repository task/branch must be rejected without ref mutation.

## Compare-and-set acceptance

The final task-branch ref update must be conditional on the remote ref still being exactly `expected_head`.

Security/concurrency tests must demonstrate:

1. normal publication creates one commit whose parent is `expected_head` and moves only the requested task branch;
2. if another writer changes the branch before the ref update, the request fails as `EXPECTED_HEAD_MISMATCH` and does not overwrite the other writer;
3. no unconditional force update is used;
4. unreachable Git objects created during a failed transaction are never reported as published state.

## Idempotency acceptance

Tests must demonstrate:

- exact replay of a successful `request_id` returns the original result without a second commit, ref move, or CI dispatch;
- exact replay while the first execution is active converges on the same execution/result;
- changed payload under an existing `request_id` is rejected as `REQUEST_ID_REUSE`;
- two new request ids racing on the same `expected_head` cannot both publish distinct commits to the same branch;
- requests for different task branches may proceed independently.

## Operation and path-policy acceptance

Bootstrap-v1 permits only add/replace of regular blobs with modes `100644` or `100755`.

Tests must reject:

- delete, rename, copy, directory/tree, symlink, submodule/gitlink, tag, and arbitrary-ref operations;
- add when the target path already exists at `expected_head`;
- replace when the path is absent, not a regular blob, or does not equal `expected_blob_sha`;
- nonexistent blob ids;
- path traversal or non-normalized paths;
- default branch or `main` target;
- `.github/workflows/**`;
- `.github/actions/**`;
- any `action.yml` or `action.yaml`;
- any `CODEOWNERS` path;
- every publisher-owned path from the protected publisher manifest.

The request must not be able to modify the publisher, its policy, its workflow/action code, its contract enforcement, or its credential configuration.

## Candidate-content isolation acceptance

The trusted publisher security context must never check out or execute candidate content.

Acceptance evidence must prove that:

- candidate task-branch/new-head files are never used as the checkout ref for the publisher job;
- candidate Python, shell, workflow, action, executable-mode file, or other content is never invoked/imported/evaluated by the publisher;
- the publisher operates on Git object metadata/tree construction only;
- any checkout needed for publisher code is pinned to trusted protected publisher source, not the candidate branch.

A malicious blob fixture that would visibly fail if executed must still be publishable as inert data to an otherwise allowed path without execution in the publisher context.

## Privilege-boundary acceptance

The publisher credential/policy must be unable to:

- write `main` or the default branch;
- approve or merge pull requests;
- change repository rulesets/branch protection;
- change repository settings;
- grant permissions;
- bypass the task-branch/path policy.

Tests and installation evidence must demonstrate least privilege rather than merely relying on application code to avoid these operations.

Ordinary CI must have no publisher credential and must remain read-only for repository contents. The current hwm-control protected baseline is the required status check context `bootstrap`; I03-P0B may add the minimum trusted dispatch trigger/inputs required to associate an exact task-branch head, but must not give that ordinary CI job task-branch write credentials.

## Exact-head CI dispatch acceptance

After a successful compare-and-set ref update, the publisher must explicitly dispatch the allowlisted ordinary CI workflow with both request id and exact `new_head`.

Acceptance requires evidence of a workflow run whose recorded/verified source SHA equals exactly `new_head`. Branch-name-only matching is insufficient.

The success `hwm-publish-result/bootstrap-v1` must include:

- exact `new_head`/`commit_sha`;
- exact workflow identity;
- exact associated CI `run_id`;
- exact dispatched `head_sha` equal to `new_head`.

If dispatch or exact run association fails, the publication result is an explicit error such as `CI_DISPATCH_FAILED`; it must not fabricate a CI run or claim validation.

## Audit/public-data acceptance

Every accepted request and normalized result must be durably auditable by request id, task Issue, repository, branch, expected head, final head/error, changed path/blob ids, actor identity, and CI run association.

Public comments/logs/artifacts must not expose credentials, tokens, cookies, browser/account/session data, private keys, sensitive raw evidence, or environment/header dumps.

Error messages are sanitized public diagnostics.

## Repository migration barriers

I03-P0B acceptance authorizes hwm-control only.

Before first publisher write to hwm-context, a separate architecture/contract Issue and protected merge must establish its repository-specific policy and acceptance. The same independent barrier is required for hwm-lab.

A test/configuration proof must show that the initial hwm-control publisher rejects both other repositories.

## Serialization policy acceptance

The publisher may serialize only per `(repository, task_branch)` to protect one compare-and-set transaction.

No global queue, milestone lock, cross-repository lock, or other task-DAG serialization point may be introduced by I03-P0B. Any such serialization point requires a separate architecture/contract Issue and protected merge before implementation.

## I11 compatibility acceptance

I03-P0B must not claim to replace full I11.

Documentation and code boundaries must preserve bootstrap-v1 as a versioned primitive that I11 can extend or migrate explicitly. Future incompatible semantics require a new contract version rather than retroactive mutation.

## Exit criterion for Issue #12

Issue #12 is complete when this acceptance contract, ADR 0001, and the migration record are merged through protected hwm-control main with the required `bootstrap` check passing, with no publisher implementation or Issue #3 extractor source publication in the diff.
