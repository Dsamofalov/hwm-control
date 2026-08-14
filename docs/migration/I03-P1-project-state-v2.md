# I03-P1 — project-state v2 migration and compatibility

## Decision

Issue #25 introduces the forward-only marker `hwm-project-state/v2` in
`schemas/project-state.v2.schema.json`. The merged
`schemas/project-state.v1.schema.json` is historical and immutable; its
semantics are not reinterpreted or weakened.

`product.head` is the only project-state field whose representation changes.
In v2 it is a dedicated lifecycle object named `product_head`, not a checkpoint
alias:

- `known` requires exact lowercase 40-hex `sha` plus non-empty disclosure-safe
  `provenance`, and forbids `reason` and `error`;
- `unknown` requires a non-empty sanitized single-line `reason` and forbids
  `sha`, `provenance`, and `error`;
- `error` requires structured `error` (`code`, `message`, `retryable`) and
  forbids `sha`, `provenance`, and `reason`.

All Core/Full/post-merge/live checkpoint definitions, provenance rules, health
objects, required project-state fields, and closed-object behavior are carried
forward unchanged.

## Reducer migration contract

New I03 reducer artifacts MUST emit `hwm-project-state/v2`. Issue #5 must map
the exact product-head extractor result by status:

- extractor `known` -> v2 `product.head.status=known` with the exact extractor
  SHA and exact disclosure-safe provenance;
- extractor `unknown` -> v2 `product.head.status=unknown` with its sanitized
  reason;
- extractor `error` -> v2 `product.head.status=error` with its structured
  sanitized error.

`unknown` and `error` MUST NOT become guessed `known`. Cached product HEAD
fallback is prohibited.

## v1 compatibility boundary

`hwm-project-state/v1` remains valid only against
`schemas/project-state.v1.schema.json`. Existing v1 artifacts are not rewritten.

A v1 artifact MUST NOT be automatically upgraded to v2 `known` merely because
v1 contains a 40-hex `product.head`. A v2 known-head assertion requires
sufficient exact provenance establishing that SHA as the exact product ref at
the relevant extraction boundary. Without that evidence, an automatic
v1-to-v2 known conversion is forbidden.

Consumers MUST choose the schema by the artifact's exact `schema` marker.
Silent v1/v2 coercion, marker rewriting, shape guessing, and cached fallback are
prohibited.

## BUILD_STATUS transition

The schema-version pin changes only
`current_schema_versions.project_state`, from `hwm-project-state/v1` to
`hwm-project-state/v2`. The transition is atomic with the v2 schema and
compatible bootstrap validator. All other schema-version pins,
`exact_relevant_heads`, and `blockers` are preserved.
