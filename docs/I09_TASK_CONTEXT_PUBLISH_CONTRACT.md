# I09 Task Context Publication Contract

Status: I09-P2 forward-only contract for publication of canonical I09 task-context packs into `Dsamofalov/hwm-context`.

This contract is separate from and does not retroactively modify:

- `hwm-task-context-request/v1`;
- `hwm-task-context-pack/v1`;
- historical-ledger publication request/result contracts;
- `hwm-publish-request/bootstrap-v1` / result;
- `hwm-job/v1` / `hwm-result/v1`.

## Versioned publication messages

- request: `hwm-task-context-publish-request/v1`, schema file `schemas/task-context-publish-request.v1.schema.json`;
- result: `hwm-task-context-publish-result/v1`, schema file `schemas/task-context-publish-result.v1.schema.json`.

The normalized request fingerprint is SHA-256 over canonical JSON of the validated request. The immutable request identity binds the exact expected protected `hwm-context/main`, exact scoped publication branch, task key, source Issue identity, source `tcr1-*` task-context request identity, canonical pack Git blob SHA-1, canonical pack SHA-256, target path, candidate parent/tree policy, and CI/status provenance.

## Only v1 artifact

The only target artifact is:

`tasks/<IXX-NNNN>/context.json`

The `<IXX-NNNN>` path component must equal the validated pack task key and its numeric suffix must equal the bound hwm-control Issue number. The pack must declare `hwm-task-context-pack/v1`; its task, Issue snapshot, source request binding, canonical bytes, Git blob SHA-1 and SHA-256 must match the publication request.

V1 permits only regular Git blob mode `100644` and only add/replace. `context.md`, extra task files, generic `tasks/**` writes, symlinks, gitlinks/submodules, executable modes, tree writes and additional publication artifacts are forbidden.

## Canonical bytes and public-data boundary

`context.json` must be canonical `hwm-canonical-json/v1`: UTF-8, no BOM, lexicographic object keys, comma/colon separators without whitespace, no non-finite numbers and exactly one trailing LF. `context_markdown` remains `not_defined_in_v1`.

Publication fails closed if the pack's public-data declaration is not `hwm-public-data/v1` / `public-disclosure-safe` / `reject`, if the exact freshness proof is not `fresh` with matching expected/observed identities, or if secret-bearing content is detected. Publication never redacts a failing candidate into an accepted candidate.

## Trusted publisher authority

The trusted publisher is repository-local to `Dsamofalov/hwm-context` and uses only the built-in job-scoped GitHub Actions token. It may use the minimal contents, pull-request, issues and actions writes required to create an inert Git candidate, scoped branch, PR, result comment and exact-head CI dispatch.

It must not:

- receive `statuses:write`;
- write protected `main`;
- approve or merge a PR;
- weaken or bypass the ruleset;
- use a PAT, deploy key or new long-lived credential;
- execute, import or check out candidate content in privileged publisher code;
- widen the historical publisher into a generic writer.

The candidate commit has exactly one parent: the requested protected-base SHA. Its tree is exactly the base tree plus the single requested task-context regular blob. The publication branch is task-scoped under `publisher/task-context/<lowercase-task-key>/...`.

## Exact CI and strict status gate

A successful publisher result binds the candidate commit/tree/parent, PR number/base/head, exact `repository-bootstrap-ci.yml` workflow-dispatch run, and required `bootstrap` status provenance (`integration_id=15368`, GitHub Actions creator).

The publisher explicitly dispatches Repository Bootstrap CI on the exact candidate head. A generated-only task-context PR does not rely on an automatic `pull_request` run for the required check.

The strict gate runs only from protected-main workflow code and has read permissions plus isolated `statuses:write`. It independently revalidates:

- the trusted transport author and immutable request fingerprint;
- the matching successful result;
- current protected main and expected base;
- exact open generated PR/base/head/repository;
- exact one-parent candidate commit, request/fingerprint trailers and tree;
- exactly one changed canonical task path and blob;
- regular `100644` Git mode and add/replace base state;
- exact canonical bytes, pack/task/Issue/source-request binding and SHA-256;
- synthetic merge parents/tree;
- successful exact candidate `workflow_dispatch` bootstrap run;
- absence of base/head/PR/merge drift immediately before status publication.

Only then may it publish the required `bootstrap` commit status. It has no contents write, pull-request write, approval or merge authority.

## Ordinary CI routing

Repository Bootstrap CI remains read-only, runs on pushes to main and ordinary PRs, and validates repository-local publisher security tests plus all canonical task artifacts. Its `paths-ignore` may contain only the historical canonical generated files and the narrow canonical task pattern `tasks/I[0-9][0-9]-[0-9][0-9][0-9][0-9]/context.json`; broad `tasks/**` filtering is forbidden.

Therefore generated-only canonical task-context PRs can receive the required check through exact dispatch + strict status, while mixed or wrong-path PRs continue to receive ordinary automatic PR CI and fail closed when task artifacts are malformed.

## Replay, stale state and cleanup

Exact replay of a previously successful immutable request is idempotent and must not create a second candidate commit, PR, dispatch or strict status. Reuse of the same request id with different normalized content is rejected.

Stale protected base, branch collisions without an exact prior success, stale candidate head, stale PR/result/merge identity, wrong task/path/Issue/source request, extra artifacts and non-regular modes fail closed.

Closing an unmerged same-repository generated task-context PR may delete only its exact scoped `publisher/task-context/...` branch. The publisher never treats a generated acceptance PR as implementation merge authority.
