# I03-P1 — project-state v2 acceptance

Issue #25 is acceptable only if all of the following are true.

- `schemas/project-state.v1.schema.json` is byte-for-byte unchanged and remains independently schema-valid.
- `schemas/project-state.v2.schema.json` uses exact marker `hwm-project-state/v2`.
- v2 product HEAD accepts valid `known`, `unknown`, and `error` forms.
- `known` requires `sha` and provenance and rejects `reason`/`error`.
- `unknown` requires a non-empty sanitized reason and rejects `sha`/provenance/`error`.
- `error` requires structured error and rejects `sha`/provenance/`reason`.
- malformed SHA and extra product-head properties are rejected.
- all other product/state required fields remain required.
- Core/Full checkpoint semantics are unchanged.
- v1 rejects the v2 product-head object shape.
- exact schema markers select the contract; silent v1/v2 coercion is rejected.
- bootstrap accepts BUILD_STATUS with project-state v2 and rejects stale project-state v1 after the transition.
- full `python -m unittest discover -s tests -p 'test_*.py' -v` discovery remains green.
- reducer implementation is absent from this change.

Migration policy is defined in `docs/migration/I03-P1-project-state-v2.md`. In particular, no v1 artifact is automatically promoted to v2 known-head without sufficient exact provenance; UNKNOWN is never guessed, and cached fallback is forbidden.
