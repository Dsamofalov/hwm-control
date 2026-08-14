"""Deterministic exact product HEAD extractor for the I03 reducer inputs."""
from __future__ import annotations

import re
from typing import Any, Protocol

PRODUCT_REPOSITORY = "Dsamofalov/hwm_predictor"
PRODUCT_REF = "refs/heads/main"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ProviderError(Exception):
    """Sanitized public-metadata provider failure."""

    def __init__(self, code: str, message: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ProviderNotFound(ProviderError):
    def __init__(self):
        super().__init__("NOT_FOUND", "public GitHub resource not found", False)


class ProductHeadProvider(Protocol):
    def get_repository(self, repository: str) -> Any: ...
    def get_ref(self, repository: str, ref: str) -> Any: ...


def _error(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {
        "status": "error",
        "repository": PRODUCT_REPOSITORY,
        "ref": PRODUCT_REF,
        "error": {"code": code, "message": message, "retryable": retryable},
    }


def extract_product_head(provider: ProductHeadProvider) -> dict[str, Any]:
    """Extract only the exact fixed product main ref; never guess a SHA."""
    try:
        repository = provider.get_repository(PRODUCT_REPOSITORY)
    except ProviderNotFound:
        return _error(
            "REPOSITORY_UNAVAILABLE",
            f"exact repository {PRODUCT_REPOSITORY} is unavailable",
            False,
        )
    except ProviderError as exc:
        return _error(exc.code, exc.message, exc.retryable)

    if not isinstance(repository, dict) or repository.get("full_name") != PRODUCT_REPOSITORY:
        return _error(
            "MALFORMED_UPSTREAM_RESPONSE",
            "repository response does not identify the exact repository",
            False,
        )

    try:
        ref_payload = provider.get_ref(PRODUCT_REPOSITORY, PRODUCT_REF)
    except ProviderNotFound:
        return {
            "status": "unknown",
            "repository": PRODUCT_REPOSITORY,
            "ref": PRODUCT_REF,
            "reason": f"exact ref {PRODUCT_REF} is missing in {PRODUCT_REPOSITORY}",
        }
    except ProviderError as exc:
        return _error(exc.code, exc.message, exc.retryable)

    target = (
        ref_payload.get("object")
        if isinstance(ref_payload, dict) and ref_payload.get("ref") == PRODUCT_REF
        else None
    )
    sha = (
        target.get("sha")
        if isinstance(target, dict) and target.get("type") == "commit"
        else None
    )
    if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
        return _error(
            "MALFORMED_UPSTREAM_RESPONSE",
            "ref response does not contain the exact lowercase commit SHA",
            False,
        )

    return {
        "status": "known",
        "repository": PRODUCT_REPOSITORY,
        "ref": PRODUCT_REF,
        "sha": sha,
        "provenance": [
            {
                "kind": "git_ref",
                "repo": PRODUCT_REPOSITORY,
                "sha": sha,
                "reference": PRODUCT_REF,
            }
        ],
    }
