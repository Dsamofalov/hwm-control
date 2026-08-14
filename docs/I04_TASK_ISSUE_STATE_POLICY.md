# I04 Durable Task Issue State Policy

This document records the I04 transition-policy decisions that refine `docs/INFRA_SPEC.md` section 12 without retroactively changing the merged I02 `hwm-task/v1` or `hwm-claim/v1` schemas.

## Authoritative execution projection

GitHub Issues are the initial durable task database. The Issue-level execution states are exactly:

- `ready`
- `claimed`
- `blocked`
- `completed`

For an **open** task Issue, exactly one lifecycle label from `ready`, `claimed`, `blocked` must be present. These labels are mutually exclusive. Other labels such as `infrastructure` and `trusted` are orthogonal metadata.

`completed` is not an active label. It is represented only by a **closed** Issue with `state_reason=completed` and with no active lifecycle label.

An open Issue with zero or multiple lifecycle labels is invalid/ambiguous. A closed Issue with an active lifecycle label is invalid. A closed Issue whose reason is not `completed` is not execution-completed. Consumers must reject unknown or contradictory snapshots rather than guess.

Milestone assignment and milestone open/closed state are best-effort UI projections. They are never an authoritative execution-state or dependency gate.

## Relation to `hwm-task/v1`

The merged I02 `hwm-task/v1` schema remains unchanged. Its broader internal/planning states are not retroactively redefined. For the GitHub Issue execution projection:

- `ready` maps to Issue `ready`;
- `claimed` maps to Issue `claimed`;
- `blocked` maps to Issue `blocked`;
- terminal task `done` maps to Issue `completed`.

Intermediate task-record states such as `in_progress`, `pr_open`, `validating`, `merged`, and `post_merge_validating` may describe internal execution detail, but they do not create additional authoritative Issue lifecycle labels.

No new schema version is required for I04 because the Issue projection is a policy/validation layer over existing contracts; introducing a second machine schema would duplicate the already versioned task record instead of resolving an incompatibility.

## Allowed transitions

| From | To | Required deterministic evidence |
|---|---|---|
| `ready` | `claimed` | every declared dependency is known `completed` |
| `ready` | `blocked` | at least one declared dependency is known non-completed, or a concrete non-dependency blocker is recorded |
| `blocked` | `ready` | every declared dependency is known `completed` and all recorded blockers are cleared |
| `claimed` | `completed` | every dependency is known `completed`; PR is merged; required candidate/PR validation is green; required post-merge validation is green |

All other lifecycle transitions are forbidden. In particular, `ready -> completed`, `blocked -> claimed`, `claimed -> ready`, and every transition out of `completed` are invalid.

## Dependency semantics

Dependencies are explicit Issue/task edges, not milestone membership. Every required dependency must have a deterministically observed execution state. A missing dependency observation, malformed state, or conflicting Issue snapshot is an error/unknown condition and cannot be treated as satisfied.

Only `completed` satisfies a dependency. `ready`, `claimed`, and `blocked` do not.

## Completion prerequisites

Completion is fail-closed. A claimed task may become completed only after:

1. its declared dependencies are completed;
2. its PR is merged through the protected path;
3. all required candidate/PR validation is green;
4. required post-merge validation is green on the exact merged SHA.

Closing an Issue before these facts are established is forbidden by policy.

## Claimed-task recovery

Recovery of an already claimed task is state-preserving: the Issue remains `claimed`. Recovery must durably record enough exact evidence to disambiguate ownership and continuation (task id, exact base/protected-main SHA, sole current ownership branch, and the reason/context for recovery). If a replacement ownership branch is used, the superseded/replacement relationship must be explicit before controlled source publication.

I04 validates that recovery is an explicit `claimed -> claimed` operation with a complete durable record. It does **not** implement the atomic branch compare-and-set, lease expiry, multi-agent concurrency primitive, or scheduler; those belong to I05.

A defect discovered while a task is claimed does not require adding `blocked` alongside `claimed`. Conflicting lifecycle labels are invalid. The claimed task may retain ownership while a separately proven prerequisite/remediation is performed, with blocker/recovery evidence recorded durably.

## Deterministic validator

`control/task_issue_state.py` is the machine-checkable I04 policy implementation. It:

- interprets GitHub Issue snapshots without guessing;
- enforces lifecycle-label exclusivity;
- validates explicit transitions;
- rejects claim when dependencies are unmet;
- rejects completion when required merge/CI evidence is incomplete;
- treats milestone state as non-authoritative;
- supports explicit state-preserving claimed recovery;
- contains no atomic claim, lease, scheduler, or GitHub mutation implementation.
