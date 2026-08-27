# ADR 0010: Defer protected-path credentials and use in-job runtime acquisition

**Status:** Accepted  
**Date:** 2026-08-28  
**Task:** I10-0089 / Issue #89

## Context

The P0A contract in §38 and ADR 0009 defined a controlled protected-path installer. P0A contract was internally coherent but operationally unimplementable with `GITHUB_TOKEN` for `.github/workflows/**`. The P0B installation PR and CI proved only static/unit behavior; they did not prove that the installed workflow could perform the protected-path mutation it was designed to authorize.

Live acceptance is authoritative. The disposable hwm-lab acceptance attempt failed at the authority boundary, so #87 is superseded/not-planned, not completed. The installed protected-path implementation and its contracts remain audit evidence, but their active route is replaced by this decision. The installed route is retained only in a dormant historical/fail-closed state and must not be invoked after this reconciliation.

## Decision

Credentialed protected-path mutation is deferred to I11. No such credential is authorized now. No PAT, GitHub App credential, deploy key, private key, long-lived token, or substitute privileged credential is introduced by I10-0089.

A future I11 security/architecture decision must explicitly determine the credential type, exact `Workflows` permission, repository scope, private-key/secret storage, rotation, revocation, duration/review date, and audit and cleanup requirements before any credentialed protected-path mutation is authorized. This ADR does not preselect those answers and grants no present credential authority.

#85 must avoid `.github/**`. Exact runtime acquisition moves into ordinary read-only CI code. The current #85 route is to acquire the exact actions/python-versions CPython 3.12.10 Ubuntu 24.04 x86_64 archive in-job under the forward-only `hwm-graphify-acceptance-runtime/v1` contract, validate its exact URL, filename, byte size, SHA-256, redirect host and executable report, and use only the verified task-local runtime.

Do not use `actions/setup-python`. There is no runtime lookup through the current `main` version-manifest, no mirror fallback, no toolcache fallback, and no mutable manifest selection. The runtime acquisition uses anonymous HTTPS GET only and no provider/API/model/database credentials. Acquisition and bounded setup occur before the 900-second semantic builder timer.

The verified archive is extracted only beneath `RUNNER_TEMP`, rejects path traversal, symlinks and special files, uses `RUNNER_TEMP/task-local` as the install root, rejects a preexisting runtime/cache target, does not use a global/shared cache or cross-run reuse, and is deleted after acceptance. Network remains denied before artifact setup, product parsing and Graphify invocation according to the runtime contract.

§38 and ADR 0009 remain historical audit evidence, together with the installed hwm-lab implementation and the live-failure evidence. Failed live acceptance supersedes the installer only as the active implementation route; it does not rewrite historical evidence or declare the static installation work successful in production.

#73 resumes only after completed #85. When it resumes, it must use a fresh replacement hwm-lab branch based on then-current `hwm-lab/main`. The historical #73 recovery branches remain immutable anchors and must not be reused or mutated.

## Consequences

- I10-0089 changes architecture and exact-runtime contracts only; it does not implement #85 or #73, modify hwm-lab source, execute Graphify, or authorize credentials.
- #87 remains superseded/not-planned and never becomes a completed dependency.
- #85 depends on completed I10-0089 and implements the ordinary read-only exact-runtime path without protected-path mutation.
- General protected-path authority is an I11 decision with a separate security review.
- Existing ordinary publisher and repository rulesets are unchanged.
