# I09-P0 Deterministic Task-Context Contract

This document is the forward-only Phase-7 serialization barrier for Issue #45. It defines the deterministic request and canonical task-context pack contracts before any compiler, publisher, semantic LLM transformation, wiki synthesis, or Graphify implementation.

It composes with the existing I03 current-state contracts, I04 task lifecycle, I05 ownership, I06 Knowledge Delta gate, I07 bootstrap, and I08 historical ledger. It does not redefine those contracts.

## 1. Versioned wire boundary

I09 introduces exactly two new v1 schema markers:

- `hwm-task-context-request/v1`, serialized by `schemas/task-context-request.v1.schema.json`;
- `hwm-task-context-pack/v1`, serialized by `schemas/task-context-pack.v1.schema.json`.

Both schemas use closed object field sets. Unknown fields and unsupported schema/version markers are invalid.

The existing `hwm-job/v1` operation named `build_task_context` is not widened or reinterpreted by this barrier. It remains an older typed-job envelope. A future integration may bind that operation to this request only through a separately versioned transport decision if one is required.

Likewise, this barrier does not change `hwm-result/v1`, `hwm-publish-request/bootstrap-v1`, `hwm-publish-result/bootstrap-v1`, `hwm-historical-claim/v1`, `hwm-historical-conflicts/v1`, the historical-ledger publisher request/result contracts, `hwm-task/v1`, `hwm-claim/v1`, or `hwm-project-state/v1|v2`.

## 2. Artifact authority

`context.json` is the only canonical v1 task-context artifact. It is a deterministic derived read model and is never authority for the facts from which it was built.

`context.md` is not defined by v1. No v1 compiler or publisher may claim a Markdown projection is equivalent to or authoritative over `context.json`. A later version may add a Markdown projection only with deterministic byte rules and explicit derived-only status.

The pack may be deleted and rebuilt from its exact bound sources without loss of authoritative state.

## 3. Stable request identity

A request carries `request_id = tcr1-<64 lowercase hex>`.

The suffix is SHA-256 of UTF-8 canonical JSON for the complete validated request **with `request_id` omitted**. No trailing LF participates in this digest.

This identity binds all of the following at once:

- stable task identity;
- exact GitHub Issue snapshot;
- exact product repository/commit and explicit HEAD policy;
- exact project-state snapshot provenance;
- exact historical-ledger commit plus both canonical ledger blob identities;
- the explicit exact Knowledge Delta input set;
- the explicit exact product-source input set;
- selection and byte-budget inputs;
- freshness requirements;
- public-data policy declaration.

A changed source binding, budget, selection input, or freshness expectation is a different request identity. Wall clock, process id, cache state, environment state, random data, or LLM output are not identity inputs.

## 4. Task and GitHub Issue binding

`task.task_key` has canonical form `IXX-NNNN`. The decimal `NNNN` suffix must equal both `task.issue_number` and `issue_snapshot.issue_number`; the repositories must also match exactly.

The Issue snapshot does not rely on a mutable URL or a later re-read. It binds:

- repository and Issue number;
- exact `updated_at`;
- open/closed state and state reason;
- canonical I04 lifecycle;
- SHA-256 of title bytes;
- SHA-256 of body bytes;
- lexicographically sorted labels;
- lexicographically sorted assignees;
- milestone number or null.

`issue_snapshot.snapshot_sha256` is SHA-256 of canonical JSON for the whole Issue snapshot with only `snapshot_sha256` omitted.

The lifecycle projection remains governed by I04. A pack cannot change lifecycle meaning.

## 5. Exact product binding

`product.repository` and exact lowercase 40-hex `product.commit` identify the product revision.

`head_policy` is explicit:

- `exact_revision_only` means the exact requested commit is the source. It need not equal current HEAD, and current HEAD must never be substituted for it.
- `must_equal_current` additionally requires `expected_current_head`; the compiler must independently observe current HEAD and require exact equality.

There is no implicit default from one mode to the other.

Product source files are an `explicit_exact_set`. Every entry is bound by exact path, Git blob SHA-1, SHA-256 of source bytes, media type, deterministic priority, required/optional status, and whether deterministic byte truncation is permitted.

Files not explicitly present in this set are ineligible in v1. This prevents a compiler from broadening scope by semantic search or LLM judgment.

## 6. Exact project-state binding

The request binds one `hwm-project-state/v2` snapshot using:

- source repository;
- exact source commit;
- exact repository-relative path;
- Git blob SHA-1;
- SHA-256 of the exact state bytes.

The request freshness block also binds `project_state_commit` and `control_main_sha`; in v1 these must equal the project-state commit. If protected control `main` has moved, compilation rejects as stale rather than reading a newer state and continuing.

The project-state object remains authoritative for its deterministic current-state domains. The context pack merely carries provenance to it.

## 7. Exact historical-ledger binding

Historical input is bound to exactly `Dsamofalov/hwm-context` at one exact commit that must equal the requested exact context `main` freshness observation.

The binding names both canonical I08 files:

- `claims/claims.jsonl`;
- `claims/conflicts.json`.

For each file, request and pack carry exact Git blob SHA-1 and SHA-256 content digest.

The historical ledger retains authority class `historical_ledger`. It cannot determine or override current product HEAD, current control state, CI status, task lifecycle/ownership, branch protection, or deterministic gate success.

## 8. Exact Knowledge Delta set

Knowledge Delta inputs are `set_mode = explicit_exact_set`.

Every item carries:

- canonical `IXX-NNNN` task key and matching integer Issue/task id;
- repository `Dsamofalov/hwm-control`;
- exact commit;
- exact canonical path `knowledge-deltas/<task-key>.json`;
- Git blob SHA-1;
- SHA-256 of exact bytes.

Set-like ordering is lexicographic by `(task_key, path, content_sha256)`. The compiler may not silently add a different delta, replace an unavailable delta with prose, or infer rationale from wiki/context text.

An empty set is representable when the caller intentionally binds no Knowledge Delta inputs; it never authorizes implicit discovery.

## 9. Authority classes

The pack names these classes exactly:

1. `authoritative_current_state` — deterministic current-state materialization governed by current-state contracts.
2. `authoritative_git_github_ci` — exact Git, GitHub Issue, GitHub Actions, ruleset/gate provenance.
3. `historical_ledger` — I08 historical evidence/read model.
4. `knowledge_delta` — durable rationale/evidence from merged Knowledge Deltas.
5. `product_source` — product repository bytes at the exact requested product commit.
6. `derived_task_context` — this pack and later deterministic projections.
7. `llm_semantic_output` — future semantic output, never deterministic authority.

These are classifications, not a license to promote one class into another. Historical claims, generated context, wiki prose, or future LLM output cannot substitute for deterministic current state or exact Git/GitHub/CI facts.

## 10. Eligibility, ranking, ordering, and deduplication

The deterministic v1 selection algorithm is `hwm-task-context-selection/v1`.

Eligibility is closed:

- exact mandatory task/Issue/current-state/ledger/KD provenance objects required by the request;
- product source inputs explicitly bound in `product_sources.inputs`;
- no unbound repository scan, semantic search, Graphify result, wiki result, or LLM-selected candidate.

For payload candidates, the stable rank tuple is:

1. required before optional (`required_desc`);
2. fixed authority order:
   `authoritative_current_state`,
   `authoritative_git_github_ci`,
   `product_source`,
   `knowledge_delta`,
   `historical_ledger`;
3. ascending integer `priority`;
4. lexicographic `source_id`.

`source_id` is the final tie-break. Input enumeration order is irrelevant.

Deduplication identity is exactly:

`(authority_class, media_type, content_sha256)`

The authority class participates intentionally. Byte-identical historical and current-state text is **not** collapsed across authority classes. Within one dedup identity, the first stable-ranked candidate wins; later duplicates remain represented as `status=omitted`, `omission_reason=deduplicated`, with `duplicate_of` pointing to the earlier winner.

Pack `sources` use the same stable rank order.

## 11. Exact byte budgets and overflow

Budgets count only UTF-8 bytes of emitted payload `content`; provenance/metadata bytes are not charged to the retrieval budget. This avoids a recursive pack-size budget.

The request defines:

- `total_content_bytes`;
- `per_source_max_bytes`;
- `per_authority_bytes` for every selectable authority class.

After ranking and deduplication, each non-duplicate candidate receives the minimum of:

- remaining total budget;
- remaining budget for its authority class;
- `per_source_max_bytes`.

If allowance is zero, the candidate is `omitted` with `budget_exhausted`.

If complete content fits, status is `included`.

If complete content does not fit and `truncation_allowed=false`, status is `omitted` with `budget_exhausted`.

If truncation is allowed, emit the longest prefix whose UTF-8 byte encoding is valid and whose byte length does not exceed the allowance. Do not add an ellipsis, marker, newline, or synthetic text. If no non-empty valid prefix fits, status is `omitted`; otherwise status is `truncated`.

The pack records original and emitted byte counts and SHA-256 digests where content is emitted. Budget accounting is exact integer byte accounting, never token estimates.

## 12. Included, omitted, truncated, unknown, and error

Every payload source has exactly one status shape.

`included`
- exact source was resolved and complete selected bytes are emitted;
- original and emitted byte counts are equal;
- full and emitted SHA-256 digests are recorded.

`truncated`
- exact source was resolved;
- truncation was explicitly allowed;
- original digest/count remain recorded;
- emitted digest/count and exact deterministic truncation rule are recorded.

`omitted`
- exact source identity/provenance remains recorded;
- no content is fabricated;
- reason is one of `budget_exhausted`, `deduplicated`, `not_selected`, `optional_policy`;
- deduplicated entries name the stable earlier winner.

`unknown`
- an optional source cannot be deterministically resolved to a known value;
- a non-empty reason is recorded;
- no guessed value/content is permitted.

`error`
- optional retrieval/validation failed with typed code/message/retryable fields;
- no guessed content is permitted.

A required source may be `included`, or `truncated` only when its request explicitly permits truncation. A required source may never survive into an accepted pack as `omitted`, `unknown`, or `error`. Missing or invalid mandatory Issue/current-state/ledger/KD provenance prevents pack creation entirely.

## 13. Freshness and stale-source rejection

Freshness policy is `hwm-exact-bound-freshness/v1`.

The request binds exact expected values for:

- protected control `main`;
- protected context `main`;
- Issue snapshot digest;
- project-state commit;
- historical-ledger commit.

The accepted pack has `freshness.status = fresh` and a complete set of exact `expected == observed` checks for those bindings.

A mismatch is not a valid “stale pack” variant. It is a fail-closed compilation failure. The compiler must not produce `hwm-task-context-pack/v1` with a mismatched freshness check.

Specifically forbidden:

- replace requested product SHA with current product HEAD;
- bind another Issue revision;
- use project state from another source commit/blob;
- use ledger files from another hwm-context commit/blob;
- silently omit required authoritative source;
- translate an unavailable required source into guessed prose;
- continue after protected control/context head drift where exact-current equality is required.

Freshness is equality-based, not wall-clock-age-based. No current time is needed to reproduce the decision.

## 14. Canonical JSON

Canonical profile is `hwm-canonical-json/v1`.

For request identity inputs and pack rendering:

- encoding: UTF-8 without BOM;
- object keys: lexicographic Unicode code-point order;
- separators: exactly `,` and `:` with no insignificant whitespace;
- `ensure_ascii=false`: non-ASCII Unicode is emitted directly;
- Unicode normalization: none; canonically equivalent but byte-different strings remain different;
- JSON non-finite numbers (`NaN`, `Infinity`, `-Infinity`) are rejected;
- schemas use integers where numeric values are needed;
- array order is significant and must follow the contract-specific rules;
- no implementation-dependent map iteration order.

`context.json` is canonical pack JSON followed by exactly one LF. No extra blank line is permitted.

For SHA-256 identities explicitly defined over canonical JSON (`request_id`, Issue snapshot digest, request binding digest), the digest input has **no trailing LF** unless the field explicitly says it hashes a file's bytes.

No generated timestamp, current wall clock, process id, random UUID, environment value, locale, filesystem order, cache order, or network-response order may enter canonical output. An exact timestamp such as GitHub Issue `updated_at` is permitted only because it is bound source provenance, not generation entropy.

## 15. Public-data boundary

Request, pack, `context.json`, future publication metadata, logs, and any future derived projection must be safe for full public disclosure.

The v1 declaration `hwm-public-data/v1` lists forbidden categories:

- API secrets/tokens;
- cookies;
- browser profiles;
- account credentials;
- private keys;
- session state;
- personal data;
- sensitive raw evidence;
- secret-bearing environment/config dumps.

Closed schemas prevent arbitrary credential/config fields from being added. Content-bearing source values still require deterministic public-data validation before an accepted pack can be produced; declaration alone is not a sanitization mechanism. Violation is `reject`, never redact-and-guess.

Standard public Git/GitHub provenance that is already permitted by the repository policy remains allowed.

## 16. Failure and mismatch semantics

Schema validity is necessary, not sufficient. A v1 compiler must apply semantic checks described here after schema validation and fail closed on:

- task key / Issue number mismatch;
- Issue snapshot digest mismatch;
- request-id digest mismatch;
- stale current-head or snapshot freshness binding;
- malformed or mismatched Git blob/content digest;
- wrong canonical ledger paths;
- noncanonical or inconsistent Knowledge Delta identity/path;
- source outside the explicit input set;
- invalid ordering or duplicate identity;
- byte-budget overflow;
- required source becoming omitted/unknown/error;
- truncation without permission;
- public-data policy violation.

Failure does not authorize a partially authoritative pack. Optional source-level `unknown` and `error` are explicit records only after mandatory pack bindings have already passed.

## 17. No LLM or Graphify in the deterministic path

No LLM participates in request construction, source eligibility, rank, tie-break, deduplication, budget allocation, provenance verification, current state, freshness, or canonical rendering.

Future OpenAI/LLM work may consume a successfully validated deterministic pack for semantic transformations. Its output is `llm_semantic_output`, not current-state authority.

Graphify belongs to I10. No graph input, graph health, graph ranking, or graph-derived selection is present in these v1 schemas.

## 18. Publication boundary

This task does not define or implement an hwm-context task-pack publisher.

The existing hwm-context historical-ledger publisher remains restricted to exactly `claims/claims.jsonl` and `claims/conflicts.json`; its T1 strict generated-PR gate is not copied, generalized, or weakened here.

Future Issue #47 owns any task-pack publication contract/implementation. It must consume canonical v1 `context.json` bytes without reinterpreting this serialization barrier and must use a separately authorized protected path.

## 19. Acceptance vectors

`tests/contracts/test_task_context_contracts.py` makes the barrier executable without implementing a compiler. It covers:

- valid request and pack;
- closed fields and unsupported versions;
- task/Issue identity;
- exact SHA/blob/snapshot provenance;
- stale/mismatched rejection;
- request and canonical JSON vectors;
- byte-identical `context.json` rendering;
- stable ranking/tie-breaking;
- authority-preserving deduplication;
- exact UTF-8 byte-budget/truncation behavior;
- distinct omitted/truncated/unknown/error shapes;
- required-source fail-closed behavior;
- authority separation;
- structural public-data restrictions;
- exact Git-blob non-regression of every pre-I09 schema;
- historical/current-state separation;
- explicit absence of a v1 `context.md` artifact.

The test helper functions are contract vectors only. They are not a compiler, GitHub retrieval implementation, publisher, or runtime API.
