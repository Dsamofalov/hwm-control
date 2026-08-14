# I03-P0B controlled publisher credential model

## Scope

The bootstrap-v1 publisher in `Dsamofalov/hwm-control` does **not** require a
long-lived deploy key, PAT, GitHub App private key, repository secret, or manual
credential installation.

The privileged publisher job uses GitHub Actions' built-in, short-lived,
repository-scoped `GITHUB_TOKEN`. GitHub creates a token for each job and the
workflow narrows the privileged job to exactly:

- `contents: write`
- `issues: write`
- `actions: write`

All unspecified permissions are `none`.

The preflight job and ordinary `Infrastructure CI` remain read-only for
repository contents. They do not receive a publisher write credential.

## Git publication authentication

The publisher uses HTTPS Git transport to the fixed allowlisted remote:

`https://github.com/Dsamofalov/hwm-control.git`

The only ref mutation remains an exact compare-and-set push:

`git push --force-with-lease=refs/heads/<task-branch>:<expected-head> ...`

The token is never embedded in a remote URL, command argument, Git config,
stdout, or stderr. `actions/checkout` keeps `persist-credentials: false`.
Immediately after the runner entrypoint reads the token from the job
environment, it removes that variable before starting Git subprocesses.
For the push only, trusted publisher code creates a mode-0600 temporary token
file and an executable temporary `GIT_ASKPASS` helper. Git receives only the
helper/token-file paths; the token itself is supplied as the HTTPS password by
the helper and both temporary files are deleted when the push finishes.
Persistent/global credential helpers are disabled for that push.

The publisher still rejects `main`, the repository default branch, protected
integration branches, non-claimed task branches, forbidden paths, and all
repositories except `Dsamofalov/hwm-control`. The active `I01 main protection`
ruleset has no bypass actor, so the job-scoped token does not grant a bypass of
protected `main`.

## Workflow dispatch behavior

A successful task-branch CAS is followed by an explicit
`workflow_dispatch` of `infrastructure-ci.yml` with both `request_id` and exact
`new_head`. The REST API response supplies the deterministic workflow run id;
the publisher then verifies that the associated run is a `workflow_dispatch`
run for the allowlisted workflow and has `head_sha == new_head`.

A push made with `GITHUB_TOKEN` is intentionally not expected to create an
ordinary push-triggered workflow run. The explicit dispatch is the sole CI
association used by bootstrap-v1 publication.

## Supply-chain pinning

Every external `uses:` in the privileged publisher workflow and ordinary
Infrastructure CI is pinned to an independently verified full commit SHA.
Mutable tags such as `actions/checkout@v4` are forbidden on these surfaces.
The current checkout pin is official `actions/checkout` release `v7.0.1` at:

`3d3c42e5aac5ba805825da76410c181273ba90b1`

`persist-credentials: false` remains mandatory on every checkout step.

## Acceptance verification

Before Issue #13 is closed completed, a fresh disposable claimed-task sandbox
must prove at least:

1. an allowed regular blob moves only the intended task branch;
2. the published commit has exactly `expected_head` as parent;
3. stale/competing exact-head lease fails without overwriting the winner;
4. `main` and the default branch cannot be targeted;
5. workflow/action/CODEOWNERS/publisher-owned paths are rejected;
6. malicious executable-mode candidate content remains inert and is never
   checked out or executed by the publisher;
7. exact request replay is idempotent with no second commit/ref move/CI
   dispatch, while changed content under the same request id is rejected;
8. explicit ordinary CI is associated to the exact `new_head` and the
   `bootstrap` job succeeds;
9. ordinary CI remains `contents: read` and has no publisher write token;
10. `hwm-context` and `hwm-lab` remain outside bootstrap-v1 authority.

If a live sandbox proves that the job-scoped `GITHUB_TOKEN` with
`contents: write` cannot perform the HTTPS force-with-lease push, preserve the
sanitized failure, leave Issue #13 open/claimed, and stop for a separate
credential architecture review. Do not introduce a deploy key, PAT, or GitHub
App credential as an automatic fallback.
