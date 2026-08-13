# hwm-control

Public operational control-plane repository for the HeroesWM autonomous development infrastructure.

`docs/INFRA_SPEC.md` is the authoritative infrastructure design source. This repository contains T1 trusted infrastructure, but public visibility is not the trust boundary: trusted changes are established by protected workflow code, protected `main`, exact trusted SHA, actor/event policy, CODEOWNERS/review policy where available, and narrowly scoped credentials. Ordinary product-development tasks must not modify trusted control/security surfaces as part of product work.

PR CI runs on ephemeral GitHub-hosted runners with `contents: read`, no secrets, and no `pull_request_target` execution of PR code. Reproducible trusted post-merge jobs may also use GitHub-hosted runners when all required inputs are GitHub data or external immutable inputs. Any local executor is deferred to I11/I12 and must be capability-driven; if introduced, a typed service/poller with an allowlisted operation enum is preferred over a universal self-hosted arbitrary-shell runner.

Everything stored in this public repository or emitted through public Issues, PRs, Actions logs, artifacts, context/wiki/graph/job/result outputs must be safe for full public disclosure. Tokens, cookies, browser profiles, account credentials, private keys, session data, personal data, and sensitive raw evidence are forbidden. Standard Git author/committer attribution metadata is expected to be public and is permitted; the personal-data prohibition applies to files, Issues, PR bodies/comments, Actions logs/artifacts, and generated public artifacts. Raw corpus may be public only after a separate safety determination; otherwise it remains an external/local immutable input.

I01 establishes repository structure, immutable I00 provenance, temporary `BUILD_STATUS.json`, issue/task bootstrap, and minimal infrastructure CI. Versioned contracts, deterministic state building, task claiming, Knowledge Delta v1, Graphify, wiki generation, GitHub job bus, and any local Windows executor implementation belong to later milestones.
