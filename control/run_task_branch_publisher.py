#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from task_branch_publisher import (
    ALLOWED_REPOSITORY,
    GitHubAPIBackend,
    Publisher,
    preflight_concurrency,
)

# GitHub's published ED25519 host key for github.com.
# Source is trusted protected publisher code, never request/candidate content.
GITHUB_KNOWN_HOSTS = (
    "github.com ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n"
)


def _event(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_output(values: dict[str, str]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        for key, value in values.items():
            print(f"{key}={value}")
        return
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _write_secret_file(path: Path, content: str) -> None:
    path.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in {"preflight", "publish"}:
        print("usage: run_task_branch_publisher.py {preflight|publish} EVENT_JSON", file=sys.stderr)
        return 2
    event = _event(argv[2])
    if argv[1] == "preflight":
        _write_output(preflight_concurrency(event))
        return 0

    token = os.environ.get("HWM_PUBLISHER_TOKEN")
    deploy_key = os.environ.get("HWM_PUBLISHER_DEPLOY_KEY")
    if not token or not deploy_key:
        print("publisher credential is not configured", file=sys.stderr)
        return 2

    repository = ((event.get("repository") or {}).get("full_name"))
    if repository != ALLOWED_REPOSITORY:
        print("event repository is not bootstrap-v1 allowlisted", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="hwm-publisher-credentials-") as tmp:
        tmp_path = Path(tmp)
        key_path = tmp_path / "deploy_key"
        known_hosts_path = tmp_path / "known_hosts"
        _write_secret_file(key_path, deploy_key)
        known_hosts_path.write_text(GITHUB_KNOWN_HOSTS, encoding="utf-8")
        known_hosts_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        backend = GitHubAPIBackend(
            token=token,
            repository=repository,
            deploy_key_path=key_path,
            known_hosts_path=known_hosts_path,
        )
        result = Publisher(backend).handle_event(event)
        if result is None:
            return 0
        issue_number = (event.get("issue") or {}).get("number")
        if not isinstance(issue_number, int):
            print("event does not identify an Issue", file=sys.stderr)
            return 2
        backend.post_result(issue_number, result)
        print(f"publish_status={result['status']} request_id={result['request_id']}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
