# I07 Generated Fresh-Agent Bootstrap Policy

This document records the I07 decisions for Issue #10. It implements the merged
`docs/INFRA_SPEC.md` Phase 5 generated-bootstrap contract and composes with the
existing I03 deterministic state, I04 task Issue lifecycle, I05 ownership, and
I06 Knowledge Delta gate. It does not introduce a new versioned serialization
contract because the merged architecture already fixes the two materialized
outputs and their required content, while no I02 bootstrap schema exists.

## Canonical generated outputs

The compiler in `control/generated_bootstrap.py` deterministically renders exactly:

- `bootstrap/current.json`;
- `bootstrap/current.md`.

These are generated materialized outputs. The compiler returns their exact bytes
and canonical paths; I07 does not turn either output into a manually maintained
current-state file in `hwm-control`. The target context plane may materialize
those bytes later through its own trusted publication path. Re-running the
compiler from the same exact inputs produces byte-identical outputs.

## Authoritative input boundary

I07 accepts only the deterministic sources already established by merged
contracts:

1. one schema-valid `hwm-project-state/v2` object materialized as
   `Dsamofalov/hwm-context/state/current.json`, with an exact source commit and Git
   blob SHA;
2. the active task Issues whose identities are exactly the union of
   `project_state.tasks.ready`, `.claimed`, and `.blocked`;
3. the exact `updated_at` revision independently expected for each task Issue;
4. protected `Dsamofalov/hwm-control` `refs/heads/main` at an independently
   expected exact SHA.

`BUILD_STATUS.json`, conversation memory, milestone open/closed state, wall-clock
time, caches, environment variables, historical Markdown, wiki text, Graphify,
and caller-supplied volatile overrides are not bootstrap truth sources.

## Exact-source and stale-source semantics

Generation fails closed unless all source bindings agree:

- infrastructure repository/ref must be exactly
  `Dsamofalov/hwm-control` / `refs/heads/main`;
- observed infrastructure HEAD must equal the independently expected HEAD;
- project-state source repository/path must be exactly
  `Dsamofalov/hwm-context/state/current.json`;
- project-state source commit must equal the independently expected state commit;
- the supplied project-state blob SHA must equal the Git blob SHA of the
  deterministic canonical state bytes;
- task Issue identities must exactly match the active task identities in project
  state, with no missing, duplicate, or unrelated Issue;
- I04 interpretation of each Issue must exactly match its project-state task
  bucket;
- every task Issue `updated_at` must equal its independently expected revision.

Missing, malformed, stale, mismatched, or ambiguous inputs are errors. I07 never
substitutes a cached value, a guessed SHA, another task, or a manually supplied
replacement.

## Bootstrap contents

The JSON and Markdown views carry the same required operational projection:

- current infrastructure HEAD;
- current product HEAD lifecycle (`known`, `unknown`, or `error`) exactly as
  represented by project state;
- current Core, Full, post-merge, and live-evidenced checkpoint lifecycles;
- infrastructure milestone projection derived from active task Issue milestone
  titles and lifecycle states, explicitly excluding milestone open/closed state
  as a gate;
- ready tasks with exact GitHub Issue pointers as the currently available task
  context boundary;
- hard architecture invariants with exact infrastructure repository/SHA/path
  source tags;
- exact project-state source commit/blob/content digest and exact task Issue
  revision/content digests.

Until the later context-compiler milestone exists, the canonical GitHub Issue URL
is the exact ready-task context pointer. I07 does not synthesize historical or
semantic context packs.

## Determinism

The compiler has no implicit clock or mutable external reads. `generated_at` is
preserved from deterministic project state. Collections are normalized to stable
ordering, structured content uses deterministic JSON serialization, task-source
projections carry SHA-256 content digests, and identical exact inputs produce
byte-identical JSON and Markdown.

Milestone open/closed UI changes are deliberately excluded from the task-source
projection and therefore cannot change bootstrap correctness or output bytes.

## Unknown and error preservation

I03 lifecycle values are copied without reinterpretation. In particular:

- `unknown` remains explicit `unknown` with its reason and never gains a guessed
  SHA;
- `error` remains explicit `error` with its structured error;
- an ambiguous active-milestone projection becomes an explicit bootstrap error
  object rather than a guessed current milestone;
- absence of active task Issues yields explicit unknown milestone status.

## Versioning decision

I07 does not add `schemas/bootstrap.*` or retrofit an I02 schema. The merged
`INFRA_SPEC.md` already defines the output paths and required fields at the
architecture boundary, and no incompatible serialization dependency requires a
new barrier contract. If a future consumer needs a stable cross-repository
versioned bootstrap wire schema, that is a separate architecture/contract task
rather than a silent I07 expansion.

## I04 / I05 / I06 composition

I07 is read-only with respect to task lifecycle and ownership. It calls the I04
Issue interpreter to reject ambiguous/conflicting task snapshots and does not
implement claim, lease, recovery, selection, or scheduling. I05 remains the
owner/CAS authority.

The canonical `knowledge-deltas/I07-0010.json` is published atomically with the
first I07 source head and claim-state `BUILD_STATUS.json`. The existing I06 gate
therefore validates I07's own rationale/provenance from the first candidate CI
run and continues requiring the same delta after I07 completion.

## Non-goals

I07 does not implement or modify:

- product-repository behavior;
- publisher, workflow, ruleset, or CODEOWNERS behavior;
- historical knowledge import;
- generated wiki;
- task-context semantic compilation;
- Graphify;
- scheduler or ready-task selection;
- GitHub job bus;
- I03 state reduction, I04 lifecycle transitions, I05 claim semantics, or I06
  delta serialization/gating.

## Deterministic evidence

`tests/test_generated_bootstrap.py` covers minimal and representative generation,
byte-identical repeat generation, input ordering, exact source/task binding,
unknown/error preservation, stale infrastructure/state/task revisions, source
blob mismatch, malformed/missing project state, missing provenance, missing or
unrelated task snapshots, lifecycle mismatch, ambiguous source identity, manual
volatile override rejection, milestone open/closed irrelevance, and explicit
I07 Knowledge Delta valid/missing/invalid gate cases.

The repository-level I06 gate remains additionally exercised by the existing full
unittest discovery path in Infrastructure CI.
