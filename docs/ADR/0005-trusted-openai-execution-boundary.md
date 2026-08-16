# ADR 0005: Trusted OpenAI execution and credential boundary

Status: accepted for I09-P5-P0 implementation; live activation remains fail-closed until the owner-side WIF mapping and project controls are independently read back.

Date: 2026-08-16

## Context

Completed I09-P4 defined the semantic contracts and deterministic verifier but intentionally added no live provider or credential path. I09-P5-P0 must add the smallest trusted OpenAI execution boundary without allowing pull-request, task-branch, fork, issue text, reusable workflow, artifact/cache handoff, or dispatch parameters to select executable code.

The handoff expected API-key Bearer authentication to be the fallback unless direct GitHub workload federation could be proven. Current official OpenAI documentation now explicitly documents Workload identity federation for GitHub Actions: a GitHub OIDC token can be exchanged at the OpenAI token endpoint for a short-lived OpenAI access token and then used as the bearer credential for normal OpenAI API calls, including Responses. The same documentation requires the OpenAI WIF provider and service-account mapping to be configured by an organization owner.

Authoritative public documentation consulted on 2026-08-16:

- `https://developers.openai.com/api/docs/guides/production-best-practices/workload-identity-federation/`
- `https://developers.openai.com/api/docs/guides/production-best-practices/github-actions-wif/`
- `https://developers.openai.com/api/reference/authentication/workload-identity-token-exchange`
- `https://developers.openai.com/api/docs/guides/structured-outputs/`
- `https://developers.openai.com/api/reference/resources/responses/methods/create`
- `https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform`

The GitHub repository metadata observed at claim time is:

- repository: `Dsamofalov/hwm-control`;
- repository id: `1333400971`;
- owner id: `25666939`;
- protected branch: `refs/heads/main`;
- repository OIDC subject customization reports `use_default=true`, `use_immutable_subject=false`, and subject prefix `repo:Dsamofalov@25666939/hwm-control@1333400971`.

No OpenAI secret value is part of this decision.

## Decision

Select `github-actions-oidc-openai-wif/v1`.

Do not introduce an OpenAI API key, organization Admin API key, personal shared key, repository secret, Environment secret, PAT, deploy key, or long-lived OpenAI credential.

The trusted live workflow is `.github/workflows/trusted-openai-live.yml`. It is dispatch-only. The sole dispatch input is an inert `olr1-...` request identity. A request identity deterministically selects exactly one JSON document under `execution/openai-live-requests/`; it cannot select a Git ref, repository, path outside that directory, script, shell command, workflow, action, model tool, or executable candidate.

The live request/result interfaces are new and forward-only:

- `hwm-openai-live-request/v1`;
- `hwm-openai-live-result/v1`.

They wrap the merged `hwm-semantic-transform-input/v1` and do not widen or reinterpret the task-context, historical-ledger, bootstrap publisher, `hwm-job/v1`, `hwm-result/v1`, or I09-P4 semantic schemas.

## Exact trust binding

The WIF mapping must require all of these exact claims:

- `iss = https://token.actions.githubusercontent.com`;
- `aud = https://api.openai.com/v1`;
- `sub = repo:Dsamofalov@25666939/hwm-control@1333400971:ref:refs/heads/main`;
- `repository = Dsamofalov/hwm-control`;
- `ref = refs/heads/main`;
- `workflow_ref = Dsamofalov/hwm-control/.github/workflows/trusted-openai-live.yml@refs/heads/main`.

The OpenAI service-account mapping permission must be exactly `api.model.request`. A broader mapping is rejected by this boundary policy.

GitHub OIDC `id-token: write` is granted only to the `live` job. The `preflight` job has only `contents: read`. The workflow must remain sourced from protected main. Before OIDC exposure, the live job reads the current `refs/heads/main` object and requires it to equal the exact `github.sha` executing the workflow. The runtime also rechecks repository, ref, workflow_ref, event, and SHA.

Because WIF is selected, a GitHub Environment is not used to store an OpenAI credential. The provider and service-account identifiers may be supplied as non-secret GitHub Actions variables; only SHA-256 digests of those identifiers are admitted to the sanitized result. The GitHub OIDC JWT and the exchanged OpenAI access token remain in process memory only and are never written to a file, output, artifact, cache, Issue, PR, repository state, or log.

## Trusted execution order

The mandatory order is:

1. resolve the protected request by inert request identity;
2. schema-validate `hwm-openai-live-request/v1`;
3. validate the embedded merged I09-P4 semantic input;
4. enforce the additional trusted-live budget ceilings;
5. fetch the exact immutable `hwm-context` task-context pack by its bound commit and path;
6. verify exact content SHA-256 and `hwm-task-context-pack/v1`;
7. fail closed on forbidden public-data signatures;
8. verify exact protected-main workflow runtime;
9. independently read back the protected main SHA;
10. only then request the GitHub OIDC JWT;
11. locally check the exact claims above without logging the JWT;
12. exchange the JWT for a short-lived OpenAI token;
13. require bearer type, lifetime `1..3600` seconds, no refresh token, and exact scope `api.model.request`;
14. call the Responses API with the exact merged model/prompt configuration;
15. discard the access-token reference before verification;
16. parse only a structured `hwm-semantic-transform-output/v1` candidate;
17. run `hwm-semantic-verifier/v1`;
18. allow semantic materialization only on deterministic verifier acceptance.

Any failure before step 10 prevents credential acquisition. Any failure after step 10 cannot promote provider output into authority.

## Responses and Structured Outputs

The request uses `/v1/responses` with:

- exact `model_id` from the merged semantic input;
- exact rendered prompt bytes from the merged semantic input;
- exact temperature/top-p/max-output-token/seed configuration where represented;
- `store=false`;
- `tools=[]`;
- `text.format.type=json_schema`;
- `strict=true`.

No web search, file search, computer use, code interpreter, MCP, external function, or other model tool is enabled.

OpenAI strict Structured Outputs supports a JSON Schema subset. The provider-facing schema is therefore a deterministic projection of the merged `hwm-semantic-transform-output/v1` that removes only documented unsupported composition/annotation keywords. Its SHA-256 is recorded. This projection is not an acceptance schema migration: the complete merged output schema and `hwm-semantic-verifier/v1` still run locally after the response and remain authoritative for acceptance.

A provider rejection caused by unsupported model parameters or schema features is a typed degraded semantic result; the boundary never silently rewrites the prompt, model, or model configuration to obtain a response.

## Public-data boundary

`hwm-public-data/v1` remains fail closed. Before any OIDC request, the semantic input and exact deterministic task-context pack must reject known signatures for:

- API secrets or tokens;
- cookies;
- browser profiles;
- account credentials;
- private keys;
- session state;
- personal data;
- sensitive raw evidence;
- secret-bearing environment or configuration.

Known-signature scanning is a minimum mechanical guard, not a declaration that unrecognized private data is safe. Producers remain responsible for public-disclosure-safe classification. Unsafe input does not enter the credentialed step.

## Authority boundary

Every accepted live result remains `derived_non_authoritative`.

It may never determine or override product HEAD, control HEAD, context HEAD, authoritative project state, GitHub Issue lifecycle, task ownership, CI status, ruleset or branch-protection state, source freshness, provenance acceptance, deterministic gate outcomes, or merge authority.

The deterministic task-context path is independently correct and usable whether OpenAI is configured, unavailable, rate-limited, timed out, malformed, rejected, or disabled.

## Logging and storage

Raw prompt text, raw LLM output, GitHub OIDC JWTs, OpenAI access tokens, Authorization headers, full request bodies, and sensitive context are forbidden from logs.

No live workflow step uses Actions cache or artifact upload/download. The response is held in memory inside one process through deterministic verification.

Sanitized evidence is limited to typed status, exact protected SHA, exact model id, prompt/schema/contract/verifier identities and digests, task-context digest, model-configuration digest, provider-structured-schema digest, request-body digest, token usage, latency, bounded attempt count, rate-limit classification, OpenAI request id, verifier decision/code, WIF scope, and token lifetime. Provider/service-account identifiers are represented only by SHA-256 digests.

## Budgets, cost, and failure behavior

The trusted-live layer adds ceilings that are equal to or stricter than I09-P4:

- input UTF-8 bytes: at most 500,000;
- input tokens: at most 64,000;
- output UTF-8 bytes: at most 250,000;
- output tokens: at most 8,192;
- per-attempt timeout: at most 60 seconds;
- total attempts: at most 2.

The existing semantic input may request lower limits; those exact lower limits remain binding. Retries never change input, prompt, model, or model configuration.

Retryable live transport classes are timeout, transient provider error, HTTP 429/rate limiting, and malformed provider output. Total attempts are bounded by the semantic contract and never exceed two. Provider authentication/request rejection, unsupported schema/version, public-data violation, provenance mismatch, authority promotion, or verifier rejection is fail closed.

Every unavailable/failed/rejected semantic path returns or preserves:

- `mode=deterministic_task_context_only`;
- `deterministic_task_context_usable=true`;
- `semantic_materialization=none`.

Owner-side activation must additionally set a finite project spend limit, spend alert, exact model permissions, and appropriate project rate limits for the dedicated OpenAI project/service account. Those project controls are required activation evidence; code-side token ceilings are not a substitute for project spend controls.

## Activation gate

The code path is intentionally inert until all activation metadata is present and the OpenAI WIF mapping accepts the exact trust binding.

An OpenAI organization owner must:

1. create or select a dedicated project and service account for this boundary;
2. configure a WIF provider for GitHub's issuer and the exact OpenAI audience;
3. create a service-account mapping requiring every exact claim in this ADR;
4. restrict that mapping to exactly `api.model.request`;
5. configure the finite project spend limit, spend alert, exact model permissions, and rate limits;
6. set only the non-secret GitHub Actions variables `OPENAI_IDENTITY_PROVIDER_ID` and `OPENAI_SERVICE_ACCOUNT_ID`;
7. read back the provider/mapping/project policy metadata and prove it matches this ADR.

No user should paste a credential, OIDC token, OpenAI access token, API key, or Admin API key into chat, an Issue, a PR, a repository file, or a workflow input.

The current automation identity cannot perform or read back the owner-only OpenAI WIF/project configuration. GitHub secret-name and Actions-variable metadata are also not readable through the current integration. Therefore implementation can be merged safely, but Issue #62 must remain `claimed` until this activation gate is independently proven.

## Revocation and rotation

Revocation is fail closed and metadata-only:

1. **Disable the live boundary** before changing trust.
2. Revoke the service-account mapping, disable the WIF provider, or disable the dedicated service account/project as appropriate.
3. From the trusted protected-main workflow, prove a fresh token exchange is denied; record only typed denial/status metadata, never the rejected JWT or token.
4. Update only the owner-side WIF provider/service-account/project binding and the two non-secret GitHub metadata variables if identifiers changed.
5. Re-read exact claim, permission, model/rate, and spend controls.
6. Restore the live boundary only after the new binding passes the same protected-main checks.

There is no long-lived OpenAI secret to rotate in GitHub. If the repository is renamed/transferred, the repository/owner ids change, GitHub OIDC subject customization changes, or the workflow path changes, the exact mapping no longer satisfies this ADR and must fail closed until a separately reviewed trust-binding update is merged and activated.

## Rejected alternatives

### Project API key in a protected GitHub Environment

Rejected for the current implementation because official OpenAI documentation now explicitly supports GitHub Actions workload identity federation for API authentication. A long-lived key would create unnecessary secret storage and rotation surface.

### Organization Admin API key

Rejected. It is outside least privilege and explicitly forbidden for this boundary.

### Pull-request or reusable-workflow credential path

Rejected. PR, fork, candidate, task-branch, reusable-workflow, artifact/cache, and user-selected-ref execution can cross trust boundaries and therefore cannot receive the OpenAI credential.

### Live acceptance from candidate code

Rejected. Candidate CI is offline/mock only. The first credential-eligible execution must occur from the workflow and Python implementation already merged to protected main.

## Consequences

The repository gains a protected-main-only, no-tool, fail-closed WIF execution boundary and deterministic offline tests, while retaining deterministic context correctness without OpenAI.

Merging this ADR and implementation does not by itself complete I09-P5-P0. Completion additionally requires owner-side WIF/project activation/readback and, if a live proof is contractually required, a minimal public-safe disposable request executed only through the merged protected boundary. Until that evidence exists, downstream Issue #50 remains blocked and unclaimed.
