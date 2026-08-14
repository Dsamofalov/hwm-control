# I06 Knowledge Delta Required Gate Policy

This document records the I06 decisions for Issue #9. It composes with the existing I02 `hwm-knowledge-delta/v1` schema, I04 durable Issue lifecycle semantics, and I05 claim ownership semantics without retroactively changing those versioned contracts.

## Existing contract is sufficient

The merged `schemas/knowledge-delta.v1.schema.json` already provides the serialization surfaces needed by I06:

- integer `task_id`;
- non-empty `goal`;
- `verified_facts` whose entries carry non-empty provenance;
- `decisions` whose entries carry rationale;
- `rejected_alternatives`;
- `changed_components`;
- `tests`;
- top-level `evidence`;
- `followups` and `unresolved`.

The I06 gap is therefore enforcement and deterministic task binding, not a serialization incompatibility. No new schema version is introduced.

## Canonical durable representation

Infrastructure task deltas are stored at exactly:

`knowledge-deltas/<IXX-NNNN>.json`

For task id `I06-0009`, the canonical file is `knowledge-deltas/I06-0009.json` and the schema field `task_id` must equal GitHub Issue number `9` encoded by the four-digit suffix. The milestone prefix is retained in the filename so the durable execution task id remains unambiguous.

Nested JSON files, alias filenames, a delta whose `task_id` belongs to another Issue, and multiple canonical task ids bound to the same Issue number are rejected. A delta for another task never satisfies the current task's gate.

## Required-task boundary

The gate derives required deltas only from durable `BUILD_STATUS.json` task ids:

- every active task with milestone number I06 or later requires its canonical delta;
- every completed task with milestone number I06 or later continues to require its canonical delta after completion and merge;
- I00/I01/I02 and pre-I06 task ids are not retroactively required to gain synthetic deltas.

Milestone assignment and milestone open/closed state are not inputs to the gate. This preserves the I04 rule that milestone state is a best-effort UI projection, not an execution or dependency gate.

## Fail-closed policy above the schema

Schema validity is necessary but not sufficient. I06 additionally requires every canonical delta to contain:

- at least one `verified_facts` entry, which therefore carries schema-required non-empty provenance;
- at least one rationale-bearing `decisions` entry;
- at least one `changed_components` entry;
- at least one `tests` entry.

The top-level `evidence` array remains governed by the existing v1 schema and may be empty; I06's mandatory evidence boundary is satisfied by at least one verified fact with its schema-required provenance. Missing, malformed, or ambiguous provenance is rejected rather than guessed.

## Real Infrastructure CI enforcement

`control/knowledge_delta_gate.py` is the deterministic read-only validation primitive.

`tests/test_knowledge_delta_gate.py` contains both negative/positive policy tests and a repository-level gate test that calls the primitive on the checked-out repository. The existing protected `.github/workflows/infrastructure-ci.yml` already executes full unittest discovery on workflow dispatch, pull requests, and pushes to `main`. Therefore the repository-level test is part of the real Infrastructure CI path without modifying the workflow:

`python -m unittest discover -s tests -p 'test_*.py' -v`

Consequently the existing CI path automatically fails when an I06+ required delta is missing, malformed, wrong-version, ambiguously represented, or bound to another task/Issue, and passes when the checked-out repository has the valid canonical delta.

## Lifecycle and ownership boundary

The gate does not infer or mutate Issue lifecycle state, dependencies, claim ownership, lease state, branch ownership, or completion evidence. I04 remains authoritative for lifecycle interpretation and completion prerequisites; I05 remains authoritative for one-owner claim/recovery semantics.

Knowledge Delta validity is an additional merge/completion gate, not a replacement for dependency, PR, candidate-CI, post-merge-CI, or claim evidence.

## Non-goals

I06 does not implement or modify:

- task selection or scheduling;
- atomic claim/recovery behavior;
- publisher semantics;
- workflow or ruleset configuration;
- product-repository behavior;
- wiki/history import;
- generated current bootstrap or I07 behavior.

## Deterministic tests

The I06 tests cover at least:

- minimal valid delta;
- complete valid delta;
- correct task/Issue binding;
- repository-level valid gate path;
- completion-state persistence of the requirement;
- missing delta;
- malformed JSON and non-object JSON;
- wrong schema/version;
- missing/empty required rationale, provenance-bearing facts, changed components, or tests;
- mismatched task id;
- malformed provenance;
- non-canonical/duplicate representations;
- duplicate Issue binding;
- invalid required task ids;
- unrelated-task delta not satisfying the gate;
- milestone projection irrelevance.

## I06 Knowledge Delta decisions

Issue #9's own `knowledge-deltas/I06-0009.json` records these decisions and their provenance. It is published atomically with the source implementation and claim-state `BUILD_STATUS.json`, so the gate is required to validate its own durable rationale/evidence record on the first exact-head source CI run.
