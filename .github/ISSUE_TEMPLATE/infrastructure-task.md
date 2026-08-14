---
name: Infrastructure task
about: Bounded infrastructure bootstrap or implementation task
title: ""
labels: ""
assignees: ""
---

# Goal

# Parent milestone

Best-effort UI projection only; milestone open/closed state is not an execution or dependency gate.

# Inputs

# Scope

# Required behavior

# Non-goals

# Done when

# Required tests

# Knowledge delta requirements

# Merge dependencies

List exact dependency Issues/tasks. Readiness requires every dependency to be deterministically `completed`.

# Durable execution record

Execution state is represented by GitHub metadata, not by a free-form field here:

- open Issue: exactly one of `ready`, `claimed`, `blocked`;
- completed task: closed with `state_reason=completed` and no active lifecycle label.

Populate after claim/recovery when applicable:

- task id:
- exact protected-main/base SHA:
- sole ownership branch:
- satisfied dependencies:
- scope/non-goals:
- recovery relationship/evidence:
