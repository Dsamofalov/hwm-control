# ADR 0004: Verified semantic transformation contract

Status: accepted for I09-P4 contract scope.

## Context

I09 already has a deterministic task-context path (`hwm-task-context-request/v1` -> `hwm-task-context-pack/v1`) that is independently authoritative for exact source selection, freshness, provenance binding, and deterministic task bootstrap. I09-P4 adds only a forward semantic convenience layer for context/wiki synthesis. It does not change any predecessor contract and does not implement the I09-P5 LLM runtime.

The semantic layer can consume only public-disclosure-safe data already admitted to the deterministic context boundary. LLM output is probabilistic and therefore cannot become a control-plane source of truth.

## Decision

Introduce three forward-only interfaces:

- `hwm-semantic-transform-input/v1` in `schemas/semantic-transform-input.v1.schema.json`;
- `hwm-semantic-transform-output/v1` in `schemas/semantic-transform-output.v1.schema.json`;
- `hwm-semantic-verification-result/v1` in `schemas/semantic-verification-result.v1.schema.json`.

The contract identifier is `hwm-semantic-transformation-contract/v1`; the deterministic post-verifier identifier is `hwm-semantic-verifier/v1`.

No existing I09 request/pack/stage/publish schema, historical-ledger schema, bootstrap publisher schema, `hwm-job/v1`, or `hwm-result/v1` is widened or reinterpreted.

### Processing order

The only accepted order is:

1. materialize/validate the existing deterministic task context through the existing I09 path;
2. construct a strict `hwm-semantic-transform-input/v1` object from exact task-context provenance and public-safe source payloads;
3. enforce input byte/token budgets before an LLM attempt;
4. use the exact prompt, prompt version/hash, provider/model id, and model configuration carried by the input;
5. parse an attempted LLM response only as `hwm-semantic-transform-output/v1`;
6. apply `hwm-semantic-verifier/v1` deterministically;
7. materialize semantic output only when the verifier result is `decision=accept` and `materialization_allowed=true`.

Schema validation alone is not acceptance. The deterministic verifier is mandatory after structured output parsing and before any semantic artifact is accepted or materialized.

`control/semantic_contract.py` is a minimal offline reference validator for these contract rules. It performs no semantic generation, network access, GitHub writes, credential handling, or OpenAI API calls.

## Authority boundary

All semantic output is permanently classified `derived_non_authoritative`. The v1 interfaces carry an explicit empty `may_override` set and an exact deny list.

An LLM or semantic artifact never determines, replaces, promotes, or overrides:

- current product HEAD;
- current `hwm-control` HEAD;
- current `hwm-context` HEAD;
- authoritative project state;
- GitHub Issue lifecycle;
- task ownership;
- CI status;
- branch-protection or ruleset state;
- source freshness;
- provenance acceptance;
- deterministic gate outcomes;
- merge authority.

An authority-promotion attempt is verifier rejection and fails closed.

The deterministic I09 task-context path remains correct and usable when the semantic layer is absent, disabled, timed out, malformed, unsupported, verifier-rejected, or otherwise unavailable. Semantic failure may remove convenience output only; it cannot invalidate or alter deterministic context.

## Input and source provenance

`hwm-semantic-transform-input/v1` binds:

- the exact deterministic `hwm-task-context-pack/v1` artifact by repository, commit, path, Git blob, content SHA-256, task key, and request id;
- every semantic source by stable `source_id`, authority class, media type, exact content SHA-256, exact provenance, and public-safe content;
- prompt template id/version/template hash, rendered prompt text/hash;
- provider, model id, and exact model configuration;
- explicit budgets and budget observations;
- historical conflict/supersession state;
- execution/failure policy;
- the public-data policy and authority boundary.

`transform_id` is `str1-` plus SHA-256 of canonical JSON for the full input with only `transform_id` omitted. The canonical profile is UTF-8 JSON with lexicographically sorted object keys, comma/colon separators without insignificant whitespace, no Unicode normalization, and non-finite numbers rejected.

Input sources are unique and lexicographically ordered by `source_id`. Their content hashes are recomputed before acceptance. The rendered prompt hash is recomputed before acceptance.

`hwm-semantic-transform-output/v1` must echo the complete source-provenance projection, historical semantics, exact input digest, deterministic task-context digest, prompt digest, and model-configuration digest. The verifier compares those fields exactly; omission, substitution, or drift rejects.

## Historical conflict and supersession semantics

Historical evidence is never silently collapsed to a winner.

The input carries:

- explicit unresolved conflict groups with stable `conflict_id` and at least two source ids;
- explicit supersession edges from a historical source to its superseding source;
- `silent_winner_selection=false`.

The output must preserve the entire historical-semantics object byte-for-value. In addition, any artifact referencing a member of an unresolved conflict must carry that `conflict_id` and the `conflict` historical label. Any artifact referencing a superseded source must carry the `superseded` label and identify that source in `superseded_source_ids`.

Ambiguity is representable with the `ambiguous` label; it is not an error that the LLM must resolve.

The verifier cannot infer truth from prose. These structural obligations prevent the semantic layer from encoding a silent control-plane winner and preserve machine-visible conflict/supersession state next to generated convenience text.

## Public-data and security boundary

Prompts, model-visible source content, logs, artifacts, and public semantic outputs remain under `hwm-public-data/v1` with classification `public-disclosure-safe`.

The following categories are forbidden:

- API secrets/tokens;
- cookies;
- browser profiles;
- account credentials;
- private keys;
- session state;
- personal data;
- sensitive raw evidence;
- secret-bearing environment/config.

A known forbidden-data signature is rejected, not redacted or silently logged. The contract also requires producers to classify/omit forbidden categories; absence of a known signature is not permission to move private data into the semantic path.

The semantic interfaces contain no credential field, credential transport, endpoint secret, cookie/session field, or browser/account profile. I09-P4 introduces no API key, PAT, deploy key, GitHub App secret, OpenAI credential, live API execution, or unmerged-code-with-secret execution path.

## Budgets

Every input carries exact per-request budgets, constrained by v1 caps:

- `input_max_utf8_bytes`: 1..1,000,000;
- `input_max_tokens`: 1..128,000;
- `output_max_utf8_bytes`: 1..500,000;
- `output_max_tokens`: 1..32,000;
- `timeout_ms`: 1,000..120,000 per attempt;
- `max_attempts`: 1..2.

The input byte metric is the sum of UTF-8 bytes of the rendered prompt plus all source content payloads. It excludes transport/envelope overhead. `budget_observation.input_utf8_bytes` must equal that recomputed metric exactly.

The token count is a pre-attempt observation produced by the pinned tokenizer/model configuration and must not exceed `input_max_tokens`. The post-verifier also requires output usage to echo the exact input-token observation and remain within output token/byte budgets. The model configuration `max_output_tokens` must equal the contract output-token budget; a retry may not silently change it.

The output byte metric is the sum of UTF-8 bytes of generated artifact `content` fields. Over-budget output is rejected before materialization.

## Timeout, retry, malformed/unsupported output, and degraded operation

Timeout scope is per attempt.

Retryable failure classes are exactly, in order:

1. `timeout`;
2. `transient_provider_error`;
3. `malformed_output`.

Non-retryable failure classes are exactly:

- `unsupported_schema_version`;
- `public_data_violation`;
- `provenance_mismatch`;
- `authority_promotion_attempt`;
- `verifier_rejected`.

A retry uses the exact same canonical input, rendered prompt, provider/model id, and model configuration. V1 permits at most two total attempts and defines zero contract-level backoff (`backoff_ms=0`); an implementation may not add hidden retries.

Malformed output means no valid `hwm-semantic-transform-output/v1` document was obtained. It may consume another attempt only while attempts remain. Unsupported schema/version is never retried. A deterministic verifier rejection is never retried by changing prompt/model/source identity; it fails closed.

After retryable failure exhaustion the only degraded fallback is:

- `mode=deterministic_task_context_only`;
- `deterministic_task_context_usable=true`;
- `semantic_materialization=none`.

A valid structured output may declare `status=partial` only with `finish_reason=max_output_tokens` or `output_byte_budget`. Partial output is not automatically accepted: it must still pass the full schema, provenance, authority, public-data, historical-semantics, and budget verifier. Otherwise the semantic output is rejected and no semantic materialization occurs.

## Deterministic verifier

`hwm-semantic-verifier/v1` is pure contract validation. Given the same canonical input/output documents it returns the same `hwm-semantic-verification-result/v1`.

Acceptance requires all of the following:

- supported exact schemas;
- exact input identity and output-to-input binding;
- exact task-context, prompt, model-configuration, and source provenance propagation;
- exact preservation of conflict/supersession state;
- no silent conflict winner structure;
- explicit superseded/ambiguous markings where applicable;
- no authority promotion;
- input/output budgets within contract;
- valid partial/truncation semantics;
- public-data compliance.

Any failed requirement sets `materialization_allowed=false`. Rejection or degraded fallback always keeps the deterministic task-context fallback usable and sets semantic materialization to `none`.

## Test corpus

`tests/semantic_contract_vectors.py` defines deterministic cases named:

- `valid`;
- `invalid`;
- `ambiguous`;
- `conflicting`;
- `truncated`;
- `unsupported`;
- `verifier_rejected`.

`tests/test_semantic_contract.py` proves valid input/output acceptance; malformed/unsupported rejection; missing provenance rejection; authority-promotion rejection; conflict/supersession preservation; no silent winner selection; verifier fail-closed behavior; deterministic truncation/budget handling; timeout/retry/degraded semantics; public-data rejection; exact provenance propagation; and absence of live API/runtime/credential behavior.

The repository's existing deterministic task-context compiler/contract tests remain in the same Infrastructure CI job. I09-P4 adds no import/call edge from deterministic compilation to the semantic contract, so semantic availability cannot become a prerequisite for task-context correctness.

## Rejected alternatives

### Widen the existing deterministic task-context contracts

Rejected. Semantic generation is a separate probabilistic layer. Retroactively widening `hwm-task-context-request/v1`, `hwm-task-context-pack/v1`, stage/publish contracts, historical-ledger schemas, bootstrap publisher schemas, or `hwm-job/v1`/`hwm-result/v1` would change already merged meanings and blur trust boundaries.

### Treat generated wiki/context prose as current state

Rejected. It would let probabilistic text override exact Git/GitHub/CI authority.

### Let the LLM resolve historical conflicts

Rejected. The model may describe ambiguity but may not silently select an authoritative winner.

### Add a live OpenAI call or credential boundary in I09-P4

Rejected. Runtime execution and any separately authorized credential boundary belong to downstream implementation work, not this architecture/contract issue.

### Retry with a different model or rewritten prompt

Rejected. That would make retry identity nondeterministic and weaken provenance. V1 retries bind the exact same input/prompt/model configuration.

## Consequences

I09-P5 can implement a semantic runtime only against these forward-only contracts and only behind a separately authorized execution/credential boundary. It must preserve the deterministic task-context path as independently correct.

This ADR authorizes no semantic runtime, no live provider call, no credential setup, no product-repository mutation, and no authority promotion.
