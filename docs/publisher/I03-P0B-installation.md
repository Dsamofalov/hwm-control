# I03-P0B controlled publisher installation

## Scope

This is the one-time bootstrap credential installation for the
`hwm-publish-request/bootstrap-v1` publisher in `Dsamofalov/hwm-control`.
It does not authorize `hwm-context`, `hwm-lab`, `main`, pull-request decisions,
ruleset changes, repository administration, or arbitrary command execution.

The trusted workflow keeps its GitHub Actions token at:

- `contents: read`
- `issues: write`
- `actions: write`

It intentionally has no `contents: write`, `pull-requests: write`,
`administration: write`, or workflow-management permission.

The only ref-write credential is one repository-scoped SSH deploy key.
It is used solely by the trusted publisher job for an exact
`git push --force-with-lease=refs/heads/<task-branch>:<expected-head>`.
The active `I01 main protection` ruleset has no bypass actor, so this deploy
key cannot directly update protected `main`.

## One-time owner action

On a trusted owner workstation:

1. Generate a dedicated ED25519 key pair used for no other purpose:

   ```text
   ssh-keygen -t ed25519 -C hwm-control-publisher-bootstrap-v1 -f hwm-control-publisher-bootstrap-v1
   ```

2. In GitHub, open:
   `Dsamofalov/hwm-control` → **Settings** → **Deploy keys** →
   **Add deploy key**.

   Configure:
   - Title: `hwm-control publisher bootstrap-v1`
   - Key: exact contents of `hwm-control-publisher-bootstrap-v1.pub`
   - **Allow write access: enabled**

   Do not reuse an organization/user SSH key and do not install this key in
   `hwm-context`, `hwm-lab`, or `hwm_predictor`.

3. In the same repository open:
   **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**.

   Configure:
   - Name: `HWM_PUBLISHER_DEPLOY_KEY`
   - Value: exact private key from `hwm-control-publisher-bootstrap-v1`

   Do not store the private key in Git, Issues, PRs, logs, artifacts, workflow
   variables, or environment dumps.

4. Delete the workstation copy of the private key after confirming the
   repository secret is configured, unless an independently secured recovery
   procedure explicitly requires retention.

No PAT and no GitHub App with `Contents: write` is required by bootstrap-v1.

## Verification after installation

Before any real paused task is resumed:

1. Confirm the deploy key appears only in `Dsamofalov/hwm-control`.
2. Confirm the Actions repository secret name is exactly
   `HWM_PUBLISHER_DEPLOY_KEY`; the secret value must never be printed.
3. Confirm `.github/workflows/task-branch-publisher.yml` gives its job only
   `contents: read`, `issues: write`, and `actions: write`.
4. Confirm ordinary `.github/workflows/infrastructure-ci.yml` remains
   `contents: read` and does not reference the deploy-key secret.
5. Confirm ruleset `I01 main protection` is still active for the default branch,
   has no bypass actors, requires PRs, resolved review threads, strict required
   status check `bootstrap`, and blocks deletion/non-fast-forward updates.
6. Run the I03-P0B disposable claimed-task sandbox proof. A successful proof
   must show an intended task branch update, a rejected competing lease,
   forbidden-path rejection, idempotent replay without a second ref move/run,
   inert malicious candidate data, and explicit ordinary-CI association to the
   exact published SHA.

## Credential rotation / removal

Rotation uses a new dedicated deploy key and replaces only
`HWM_PUBLISHER_DEPLOY_KEY`. Removing the deploy key or repository secret
disables publication without weakening `main` protection. Never broaden the
credential to compensate for a failed request; investigate the exact failure
instead.
