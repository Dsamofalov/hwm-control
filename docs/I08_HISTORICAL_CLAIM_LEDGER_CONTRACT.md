# I08-P0 Historical Knowledge Claim Ledger Contract

This document is the forward-only Phase-6 serialization barrier for Issue #35. It composes with I03 current-state truth, I04 task lifecycle, I05 task ownership, I06 Knowledge Delta gating, and I07 bootstrap generation. It does not implement the historical importer and does not modify the task-ownership `hwm-claim/v1` contract.

## 1. Versioned wire boundary

Historical knowledge uses a new, distinct schema: `hwm-historical-claim/v1`, serialized by `schemas/historical-claim.v1.schema.json`. Conflict materialization uses `hwm-historical-conflicts/v1`, serialized by `schemas/historical-conflicts.v1.schema.json`.

The existing `hwm-claim/v1` remains exclusively a task ownership/lease record. Phase-6 historical data is invalid when serialized as `hwm-claim/v1`.

The four architecture concepts are serialized in lower-case JSON as exactly: `supported`, `superseded`, `contradicted`, and `unverified`. Upper-case spellings in `INFRA_SPEC.md` are conceptual prose names, not alternate wire values.

## 2. Deterministic claim identity

`claim_id` has the form `hc1-<64 lowercase hex>` and equals SHA-256 of UTF-8 canonical JSON for exactly this identity object:

- `identity_schema = hwm-historical-claim-identity/v1`;
- `subject`;
- `predicate`;
- `value`;
- exact source `repository`, `commit`, `path`, `locator`, `blob_sha`, and `content_sha256`;
- `validity` (`valid_from`, `valid_until`).

Canonical JSON means `ensure_ascii=false`, object keys lexicographically sorted, separators exactly `,` and `:`, no insignificant whitespace, no NaN/Infinity, and no trailing newline in the identity digest input. Array order is significant. No implicit Unicode, whitespace, case, path, or value normalization occurs.

`source_class`, `status`, and relation arrays do not participate in identity. This keeps the same exact logical source statement addressable when deterministic ledger classification later changes (for example supported -> superseded) while causing inconsistent duplicate metadata for the same identity to fail rather than silently create a second ID.

Input enumeration order, wall clock, process state, environment, cache state, and LLM output ordering are not identity inputs. The same exact logical source claim therefore reproduces the same ID.

An object whose supplied `claim_id` does not exactly equal the recomputed ID is rejected. Exact duplicate objects with the same `claim_id` collapse idempotently during a rebuild. Same ID with any different serialized claim content is an inconsistent duplicate/collision and fails closed.

## 3. Exact provenance and stale-source semantics

Every claim carries disclosure-safe exact Git provenance:

- one `owner/repository` source repository;
- exact lower-case 40-hex source commit;
- exact repository-relative source path;
- either exact inclusive one-based line range or a stable symbol identity;
- exact Git blob SHA-1 for the source bytes;
- exact SHA-256 content digest for those source bytes;
- a source-class enum.

A later importer must resolve the requested repository/commit/path independently and require exactly one source revision. Zero matches is missing; more than one candidate is ambiguous. It must never substitute another commit, current HEAD, a cached revision, guessed path/line/symbol, or a best-effort source.

Binding succeeds only when the independently resolved repository/commit/path exactly match the claim, recomputed Git blob SHA-1 and SHA-256 match, and the locator exists uniquely in those exact bytes. Any stale, missing, malformed, ambiguous, or content-mismatched source fails closed.

## 4. Status, contradiction, and supersession invariants

`supported` means the exact source claim is verified against its provenance and is not currently conflict-marked or superseded. It may explicitly supersede older retained claims.

`superseded` means the claim remains in the ledger but has at least one stable `superseded_by` claim ID. Every relation is bidirectionally machine-checkable: if newer claim A lists old claim B in `supersedes`, B must remain present, have status `superseded`, and list A in `superseded_by`. Dangling, self, or one-sided relations are rejected.

`contradicted` means the statement remains separately addressable and has at least one symmetric `conflicts_with` relation to another distinct contradicted claim. Contradictory statements are never merged into one prose/current fact and no winner is inferred. `claims/conflicts.json` is a deterministic derived pair index; each pair gets `hcf1-<sha256(canonical pair)>` and both claim IDs remain in `claims.jsonl`.

`unverified` means provenance and identity may be recorded, but support has not been established. It cannot participate in supersession or conflict relations and must never be promoted to `supported` by omission, defaulting, import order, current-state agreement, or LLM judgment. A later supported classification must be the deterministic result of reprocessing exact sources and produces the same stable `claim_id` because status is not identity.

The four wire statuses are mutually exclusive in v1. A source statement that would need simultaneous status meanings must be represented through retained relation history and a deterministic single current ledger classification; v1 does not silently compress multi-state ambiguity.

## 5. Validity interval

Every claim has `valid_from` and `valid_until`, each RFC3339 timestamp or `null`. Both null means the source establishes no bounded real-world validity interval. One null means open-ended. When both are present, `valid_until` must not precede `valid_from`.

Validity is evidence metadata, not current-state authority. Import order and source commit chronology do not fabricate missing validity endpoints.

## 6. Canonical deterministic ledger

The canonical materialized repository/domain is the public bot-owned read model `Dsamofalov/hwm-context`, under exactly:

- `claims/claims.jsonl` — authoritative materialized historical-claim ledger view;
- `claims/conflicts.json` — deterministic derived conflict-pair index.

`claims/claims.jsonl` is UTF-8 without BOM, one canonical `hwm-historical-claim/v1` object per line, sorted strictly by `claim_id`, with exactly one LF after every line and no blank lines.

`claims/conflicts.json` is one canonical JSON `hwm-historical-conflicts/v1` object, with conflict entries ordered by the lexicographically sorted two-claim tuple, `claim_ids` within each pair lexicographically sorted, and exactly one trailing LF.

A rebuild from the same exact source snapshot must produce byte-identical outputs. Import iteration order cannot affect output. Exact duplicate input claims are ignored after equality verification; inconsistent duplicate identities fail. Re-importing the same exact source snapshot is idempotent and produces no logical or byte change.

The architecture suggestion `claims/claims.jsonl` / `claims/conflicts.json` is therefore made normative by this forward contract. `index.sqlite` is not authoritative and is not required; any future database/index is disposable derived acceleration and must be rebuildable from the canonical ledger and exact sources.

`hwm-context` is a materialized read model: underlying Git/evidence sources remain provenance authority. The ledger paths above are the canonical materialization boundary, not a new source of current operational truth.

## 7. Current-state separation

Every historical claim has `authority = historical`. v1 forbids `subject` beginning `current:` and `predicate` beginning `current.`. Importers and consumers must not use this ledger to replace, select, infer, or overwrite:

- current product HEAD;
- current infrastructure HEAD;
- any CI green SHA;
- current task lifecycle;
- task claim ownership;
- protected-branch status;
- current deterministic `state/current.json`.

Those facts remain governed by I03/I04/I05 and the current-state materialization path. A future current-state object may reference a historical `claim_id` as evidence, but historical claims never become current-state authority by themselves.

## 8. Initial Phase-6 source boundary

The schema reserves the Phase-6 source classes `git_history`, `changelog`, `ability_changelog`, `status_doc`, `handoff_doc`, `specification_history`, and `evidence_doc`.

The first importer implementation is not required to support all classes at once. The minimum deterministic vertical slice SHALL support at least `changelog` and `specification_history`, resolved only from exact Git commits/paths/locators. The remaining source classes may be added incrementally under the same v1 contract when their extraction rules are deterministic. Raw or sensitive evidence is still governed by the public-data boundary and is not copied merely because `evidence_doc` exists as a source class.

## 9. Cross-repository publication boundary

Phase-6 Done requires actual materialization of the canonical ledger into `hwm-context`; a local-only renderer is insufficient for the project architecture.

No currently merged trusted publication mechanism authorizes that write. The bootstrap publisher is explicitly restricted to `Dsamofalov/hwm-control`; `hwm-context` currently has only bootstrap CI and its README requires protected trusted writes. Therefore the later importer has an explicit prerequisite: a separate trusted architecture/contract + implementation path that authorizes deterministic generated writes to the exact `hwm-context` claim paths with protected branch/PR/CI, exact-head CAS/idempotence, narrow credential scope, public-data enforcement, and no candidate-content execution.

Issue #35 does not implement that publisher, does not change `ALLOWED_REPOSITORY`, does not direct-push, and does not use generic connector file/commit mutations as an escape hatch. The prerequisite must be tracked separately before importer materialization can be considered complete.

## 10. Migration and acceptance

This is forward-only. Existing `hwm-claim/v1`, `hwm-task/v1`, Knowledge Delta, and project-state schemas are not retroactively changed. There is no historical ledger to migrate: audited `hwm-context/main` contained only `claims/.gitkeep`.

Acceptance requires contract tests proving all four statuses, deterministic identity vectors, exact source binding, stale/missing/ambiguous rejection, stable ordering, byte-identical repeat rendering, duplicate idempotence/inconsistency rejection, preserved contradiction pairs, retained superseded claims, no implicit unverified promotion, current-state separation, rejection of Phase-6 data as `hwm-claim/v1`, canonical path/serialization rules, and the cross-repository publication boundary.
