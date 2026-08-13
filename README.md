# hwm-control

Private trusted operational control-plane repository for the HeroesWM autonomous development infrastructure.

`docs/INFRA_SPEC.md` is the authoritative infrastructure design source. This repository is T1 trusted infrastructure: ordinary product-development tasks must not modify trusted control/security surfaces as part of product work.

I01 establishes repository structure, immutable I00 provenance, temporary `BUILD_STATUS.json`, issue/task bootstrap, and minimal infrastructure CI. Versioned contracts, deterministic state building, task claiming, Knowledge Delta v1, Graphify, wiki generation, GitHub job bus, and Windows worker implementation belong to later milestones.
