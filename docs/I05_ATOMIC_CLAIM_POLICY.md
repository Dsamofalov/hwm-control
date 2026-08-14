# I05 Atomic Claim Prototype Policy

This document records the I05 concurrency decisions for Issue #8. It refines the
`docs/INFRA_SPEC.md` section 12.3 claim behavior and composes with
`docs/I04_TASK_ISSUE_STATE_POLICY.md` without retroactively changing the merged
`hwm-task/v1` or `hwm-claim/v1` schemas.

## Contract compatibility

`hwm-claim/v1` is sufficient for the I05 prototype. A successful ownership record
uses its existing fields exactly:

- `schema = hwm-claim/v1`;
- integer `task_id`, which is the durable GitHub Issue/task number for this
  prototype;
- one ownership `branch`;
- exact `base_repo` and `base_sha`;
- UTC `claimed_at` and `lease_expires_at`;
- optional `agent_id`.

No new versioned claim schema is introduced. I05 adds deterministic policy and a
machine-checkable compare-and-set implementation around the existing record.

## Serialization and compare-and-set

The claim CAS is **task-scoped**, keyed by `task_id`. The atomic write installs:

1. the sole active claim record for that task; and
2. its ownership-branch binding.

The protected base SHA and authoritative Issue state are compare inputs. A
successful initial claim therefore requires, in the same CAS decision:

- the Issue/task number equals `hwm-claim/v1.task_id`;
- I04 interprets the Issue as exactly `ready`;
- every declared dependency is deterministically `completed`;
- the store's current protected head equals the proposed exact `base_sha`;
- the task has no existing active claim;
- the ownership branch is not already bound.

The ownership branch remains the durable Git ownership token described by
`INFRA_SPEC.md`. The task-scoped slot is important because two contenders must
not both win merely by proposing different legal branch suffixes. A production
adapter must preserve these compare-and-set semantics; splitting the compare and
ownership write into best-effort independent mutations is not equivalent.

The winner receives `claimed`. A loser receives a typed, clean conflict and the
prototype leaves the existing owner unchanged. There is no partial second owner.

## Lifecycle and dependency boundary

I04 remains authoritative for Issue lifecycle interpretation.

Initial claim is only `ready -> claimed`. Missing, malformed, or conflicting
lifecycle labels reject without guessing. In particular, `ready+claimed`,
`ready+blocked`, and `claimed+blocked` are invalid inputs.

Dependency state is explicit. Only `completed` satisfies a dependency. Missing or
unknown dependency observations reject; they are not treated as satisfied.

Milestone assignment/open/closed state is accepted only as a UI projection and
does not affect claim eligibility.

## Exact-head semantics

`base_sha` is both durable ownership evidence and an optimistic compare input for
an initial claim. If the protected head has moved since the contender's
observation, the claim fails with a clean `STALE_EXPECTED_HEAD` conflict before
ownership is installed.

This prevents a fresh claim from silently starting on a stale protected-main
observation.

## Replay semantics

The merged claim schema has no request-id field, so I05 does not invent a new
request envelope. The safe idempotent case is exact-record replay after the
authoritative Issue projection is already `claimed`: if the stored active
`hwm-claim/v1` record is byte-for-field equivalent to the proposed record, the
prototype returns `replay` and performs no second ownership write.

A different owner/branch/lease proposal for an already claimed task is a
conflict, not a replay.

## Lease semantics

Lease timestamps are interpreted as UTC RFC3339 values ending in `Z`.

For a newly installed claim:

- `claimed_at < lease_expires_at`;
- `claimed_at` cannot be in the future relative to the CAS observation time;
- the proposed lease must still be active at CAS time.

A lease is active while:

`now < lease_expires_at`

and is stale beginning exactly when:

`now >= lease_expires_at`.

Expiry by itself does not change the Issue lifecycle label. The Issue remains
`claimed` until an explicit recovery operation succeeds.

## Stale-lease recovery

Recovery composes with the I04 state-preserving `claimed -> claimed` rule.

The I05 prototype deliberately supports the smallest safe recovery:

- the Issue must still be exactly `claimed`;
- the caller supplies the exact previously observed active claim record as CAS
  evidence;
- that exact record must still be current;
- the old lease must be stale;
- dependencies must still be deterministically completed;
- durable recovery evidence must identify task id, original base SHA, current
  ownership branch, and a non-empty reason;
- the renewed lease cannot overlap the old lease;
- recovery retains the **same** ownership branch and base.

The last rule keeps recovery from creating a second branch owner. I04 permits a
replacement branch only when a superseded/replacement relationship is explicit,
but Issue #8 does not need to implement that larger takeover transaction. The
prototype rejects replacement-branch recovery rather than guessing a safe
supersession protocol.

A premature recovery attempt fails with `LEASE_ACTIVE`. A contender using a
stale expected claim record fails with `STALE_EXPECTED_CLAIM`.

## Implementation boundary

`control/atomic_claim.py` is an in-memory, thread-safe deterministic prototype.
It intentionally contains no:

- task selection or scheduler;
- GitHub API mutation adapter;
- Issue template rewrite;
- publisher/workflow/ruleset mutation;
- I06 Knowledge Delta gate;
- I07 bootstrap generation.

Its purpose is to make the I05 claim/CAS/lease/recovery policy executable and
testable before any later integration layer is introduced.

## Deterministic evidence

`tests/test_atomic_claim.py` covers at least:

- successful single-owner claim;
- concurrent contenders with different proposed branches -> exactly one winner;
- clean loser conflict with no partial ownership;
- exact replay;
- stale expected protected head;
- unmet/missing dependencies;
- non-READY and ambiguous lifecycle states;
- malformed/missing claim/base/ownership evidence;
- branch/task mismatch;
- second-owner rejection;
- milestone irrelevance;
- lease-expiry boundary;
- valid stale same-branch recovery;
- premature takeover rejection;
- stale expected recovery record;
- incomplete recovery evidence;
- unmet dependency during recovery;
- replacement-branch recovery rejection.

## Knowledge delta

I05 records these decisions:

1. Existing `hwm-claim/v1` is sufficient; no schema migration is needed.
2. One-owner safety is task-scoped, not merely branch-name-scoped.
3. Exact protected-head and Issue-state observations are compare inputs, not
   advisory metadata.
4. Lease expiry starts at `now >= lease_expires_at`.
5. Expiry does not silently free a task; recovery is explicit `claimed -> claimed`.
6. The minimal recovery renews the same ownership branch after exact-record CAS.
7. Milestone state is never a claim gate.
8. Scheduler behavior remains outside I05.
