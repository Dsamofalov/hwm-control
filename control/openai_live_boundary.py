from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from control import semantic_contract as sc

ROOT = Path(__file__).resolve().parents[1]

REQUEST_SCHEMA = "hwm-openai-live-request/v1"
RESULT_SCHEMA = "hwm-openai-live-result/v1"
AUTH_MECHANISM = "github-actions-oidc-openai-wif/v1"
TRUST_POLICY = "hwm-openai-protected-main/v1"

OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_AUDIENCE = "https://api.openai.com/v1"
OIDC_SUBJECT = (
    "repo:Dsamofalov@25666939/hwm-control@1333400971:ref:refs/heads/main"
)
REPOSITORY = "Dsamofalov/hwm-control"
REF = "refs/heads/main"
WORKFLOW_REF = (
    "Dsamofalov/hwm-control/.github/workflows/trusted-openai-live.yml@refs/heads/main"
)
OPENAI_TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
REQUIRED_WIF_SCOPE = ("api.model.request",)

REQUEST_ID_RE = re.compile(r"^olr1-[0-9a-f]{64}$")

# Forward-only trusted-live ceilings. The merged #49 contract remains authoritative;
# this boundary may be stricter but never relaxes it.
LIVE_CAPS = {
    "input_max_utf8_bytes": 500_000,
    "input_max_tokens": 64_000,
    "output_max_utf8_bytes": 250_000,
    "output_max_tokens": 8_192,
    "timeout_ms": 60_000,
    "max_attempts": 2,
}

_UNSUPPORTED_STRICT_SCHEMA_KEYS = {
    "$schema",
    "$id",
    "title",
    "allOf",
    "not",
    "dependentRequired",
    "dependentSchemas",
    "if",
    "then",
    "else",
}

_ALLOWED_LOG_FIELDS = (
    "status",
    "protected_main_sha",
    "model_id",
    "prompt_template_id",
    "prompt_version",
    "prompt_template_sha256",
    "prompt_rendered_sha256",
    "semantic_input_schema",
    "semantic_output_schema",
    "semantic_contract_id",
    "verifier_id",
    "task_context_content_sha256",
    "model_configuration_sha256",
    "structured_output_schema_sha256",
    "request_body_sha256",
    "input_tokens",
    "output_tokens",
    "latency_ms",
    "attempts",
    "rate_limit_classification",
    "openai_request_id",
    "failure_code",
    "verification_decision",
    "wif_scope",
    "wif_expires_in_seconds",
)


class LiveBoundaryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _schema(path: str) -> dict[str, Any]:
    return json.loads((ROOT / "schemas" / path).read_text(encoding="utf-8"))


def _validate_schema(path: str, value: Any) -> None:
    Draft202012Validator(
        _schema(path), format_checker=FormatChecker()
    ).validate(value)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def expected_request_id(value: Mapping[str, Any]) -> str:
    candidate = copy.deepcopy(dict(value))
    candidate.pop("request_id", None)
    return "olr1-" + _sha256(canonical_bytes(candidate))


def request_path(request_id: str) -> Path:
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise LiveBoundaryError(
            "INVALID_REQUEST_ID", "live request id has invalid syntax"
        )
    return (
        ROOT
        / "execution"
        / "openai-live-requests"
        / f"{request_id}.json"
    )


def validate_live_request(value: Mapping[str, Any]) -> None:
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != REQUEST_SCHEMA
    ):
        raise LiveBoundaryError(
            "UNSUPPORTED_REQUEST_SCHEMA", "unsupported live request schema"
        )
    try:
        _validate_schema("openai-live-request.v1.schema.json", value)
        canonical_bytes(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise LiveBoundaryError(
            "REQUEST_SCHEMA_INVALID", "live request is not schema-valid"
        ) from exc

    if value["request_id"] != expected_request_id(value):
        raise LiveBoundaryError(
            "REQUEST_ID_MISMATCH",
            "request id does not bind the canonical protected request",
        )

    semantic_input = value["semantic_input"]
    try:
        sc.validate_semantic_input(semantic_input)
    except sc.SemanticContractError as exc:
        raise LiveBoundaryError(exc.code, exc.message) from exc

    budgets = semantic_input["budgets"]
    for key, cap in LIVE_CAPS.items():
        if budgets[key] > cap:
            raise LiveBoundaryError(
                "LIVE_BUDGET_EXCEEDED",
                f"{key} exceeds the trusted-live cap",
            )

    execution = value["execution"]
    if execution["tools"] != []:
        raise LiveBoundaryError(
            "TOOLS_FORBIDDEN", "OpenAI tools are forbidden"
        )
    if execution["store"] is not False:
        raise LiveBoundaryError(
            "STATE_STORAGE_FORBIDDEN", "Responses store must be false"
        )


def load_request(request_id: str) -> dict[str, Any]:
    path = request_path(request_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveBoundaryError(
            "REQUEST_NOT_FOUND_OR_INVALID",
            "protected request is unavailable or invalid",
        ) from exc
    validate_live_request(value)
    return value


def task_context_url(value: Mapping[str, Any]) -> str:
    ref = value["semantic_input"]["task_context"]
    if ref["repository"] != "Dsamofalov/hwm-context":
        raise LiveBoundaryError(
            "TASK_CONTEXT_REPOSITORY_MISMATCH",
            "unexpected context repository",
        )
    path = urllib.parse.quote(ref["path"], safe="/")
    return (
        "https://raw.githubusercontent.com/"
        f"Dsamofalov/hwm-context/{ref['commit']}/{path}"
    )


def verify_task_context_bytes(
    value: Mapping[str, Any], raw: bytes
) -> dict[str, Any]:
    ref = value["semantic_input"]["task_context"]
    if _sha256(raw) != ref["content_sha256"]:
        raise LiveBoundaryError(
            "TASK_CONTEXT_DIGEST_MISMATCH",
            "task-context content digest mismatch",
        )
    try:
        text = raw.decode("utf-8")
        pack = json.loads(text)
        _validate_schema("task-context-pack.v1.schema.json", pack)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
    ) as exc:
        raise LiveBoundaryError(
            "TASK_CONTEXT_INVALID",
            "task-context pack is invalid",
        ) from exc
    if pack.get("schema") != "hwm-task-context-pack/v1":
        raise LiveBoundaryError(
            "TASK_CONTEXT_INVALID",
            "unsupported task-context pack schema",
        )
    if sc._contains_forbidden_data(text):
        raise LiveBoundaryError(
            "PUBLIC_DATA_VIOLATION",
            "task-context pack fails public-data preflight",
        )
    return pack


def fetch_and_verify_task_context(
    value: Mapping[str, Any]
) -> dict[str, Any]:
    request = urllib.request.Request(
        task_context_url(value),
        headers={"User-Agent": "hwm-control-openai-boundary/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(2_000_001)
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise LiveBoundaryError(
            "TASK_CONTEXT_UNAVAILABLE",
            "immutable task-context pack could not be fetched",
        ) from exc
    if len(raw) > 2_000_000:
        raise LiveBoundaryError(
            "TASK_CONTEXT_INVALID", "task-context pack is too large"
        )
    return verify_task_context_bytes(value, raw)


def _strict_schema_projection(value: Any) -> Any:
    if isinstance(value, list):
        return [_strict_schema_projection(item) for item in value]
    if not isinstance(value, Mapping):
        return value
    projected: dict[str, Any] = {}
    for key, child in value.items():
        if key in _UNSUPPORTED_STRICT_SCHEMA_KEYS:
            continue
        projected[key] = _strict_schema_projection(child)
    return projected


def structured_output_schema() -> dict[str, Any]:
    # Provider strictness enforces the supported structural subset. The merged
    # hwm-semantic-transform-output/v1 schema and #49 verifier still run after
    # the response and remain the acceptance authority.
    return _strict_schema_projection(
        _schema("semantic-transform-output.v1.schema.json")
    )


def build_responses_payload(
    value: Mapping[str, Any]
) -> dict[str, Any]:
    validate_live_request(value)
    semantic_input = value["semantic_input"]
    model = semantic_input["llm_provenance"]["model"]
    config = model["configuration"]

    payload: dict[str, Any] = {
        "model": model["model_id"],
        "input": semantic_input["llm_provenance"]["prompt"][
            "rendered_text"
        ],
        "max_output_tokens": config["max_output_tokens"],
        "store": False,
        "tools": [],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "hwm_semantic_transform_output_v1",
                "schema": structured_output_schema(),
                "strict": True,
            }
        },
    }

    # Preserve exact #49 model configuration when the API field is present.
    # A provider-side unsupported-parameter response is non-authoritative and
    # fail-closed; this boundary never silently changes configured values.
    payload["temperature"] = config["temperature"]
    payload["top_p"] = config["top_p"]
    if config["seed"] is not None:
        payload["seed"] = config["seed"]
    return payload


def sanitized_provenance(
    value: Mapping[str, Any],
    protected_main_sha: str,
) -> dict[str, Any]:
    semantic_input = value["semantic_input"]
    prompt = semantic_input["llm_provenance"]["prompt"]
    contract = semantic_input["llm_provenance"]["contract"]
    model = semantic_input["llm_provenance"]["model"]
    provider_schema = structured_output_schema()
    body = build_responses_payload(value)
    return {
        "protected_main_sha": protected_main_sha,
        "model_id": model["model_id"],
        "prompt_template_id": prompt["template_id"],
        "prompt_version": prompt["version"],
        "prompt_template_sha256": prompt["template_sha256"],
        "prompt_rendered_sha256": prompt["rendered_sha256"],
        "semantic_input_schema": contract["input_schema"],
        "semantic_output_schema": contract["output_schema"],
        "semantic_contract_id": contract["contract_id"],
        "verifier_id": contract["verifier"],
        "task_context_content_sha256": semantic_input[
            "task_context"
        ]["content_sha256"],
        "model_configuration_sha256": sc.model_configuration_sha256(
            semantic_input
        ),
        "structured_output_schema_sha256": _sha256(
            canonical_bytes(provider_schema)
        ),
        "request_body_sha256": _sha256(canonical_bytes(body)),
    }


def assert_runtime_context(
    protected_main_sha: str,
    runtime: Mapping[str, str],
) -> None:
    expected = {
        "repository": REPOSITORY,
        "ref": REF,
        "workflow_ref": WORKFLOW_REF,
        "event_name": "workflow_dispatch",
        "sha": protected_main_sha,
    }
    for key, expected_value in expected.items():
        if runtime.get(key) != expected_value:
            raise LiveBoundaryError(
                "RUNTIME_TRUST_MISMATCH",
                f"runtime {key} is outside protected-main trust",
            )


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise LiveBoundaryError(
            "OIDC_TOKEN_INVALID", "GitHub OIDC token is not a JWT"
        )
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(
            base64.urlsafe_b64decode(payload.encode("ascii"))
        )
    except Exception as exc:
        raise LiveBoundaryError(
            "OIDC_TOKEN_INVALID",
            "GitHub OIDC claims cannot be decoded",
        ) from exc


def validate_oidc_claims(claims: Mapping[str, Any]) -> None:
    exact = {
        "iss": OIDC_ISSUER,
        "aud": OIDC_AUDIENCE,
        "sub": OIDC_SUBJECT,
        "repository": REPOSITORY,
        "ref": REF,
        "workflow_ref": WORKFLOW_REF,
    }
    for key, expected in exact.items():
        if claims.get(key) != expected:
            raise LiveBoundaryError(
                "OIDC_CLAIM_MISMATCH",
                f"OIDC claim {key} does not match trust policy",
            )
    if claims.get("event_name") not in (None, "workflow_dispatch"):
        raise LiveBoundaryError(
            "OIDC_CLAIM_MISMATCH",
            "OIDC event_name is not workflow_dispatch",
        )


def _request_github_oidc_token(
    request_url: str,
    request_token: str,
) -> str:
    parsed = urllib.parse.urlparse(request_url)
    query = dict(
        urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=True
        )
    )
    query["audience"] = OIDC_AUDIENCE
    url = urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query))
    )
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"bearer {request_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        json.JSONDecodeError,
    ) as exc:
        raise LiveBoundaryError(
            "OIDC_TOKEN_UNAVAILABLE",
            "GitHub OIDC token request failed",
        ) from exc
    token = payload.get("value")
    if not isinstance(token, str) or not token:
        raise LiveBoundaryError(
            "OIDC_TOKEN_UNAVAILABLE",
            "GitHub OIDC token response had no token",
        )
    return token


def _exchange_wif_token(
    subject_token: str,
    identity_provider_id: str,
    service_account_id: str,
) -> dict[str, Any]:
    body = {
        "grant_type": (
            "urn:ietf:params:oauth:grant-type:token-exchange"
        ),
        "subject_token_type": (
            "urn:ietf:params:oauth:token-type:jwt"
        ),
        "subject_token": subject_token,
        "identity_provider_id": identity_provider_id,
        "service_account_id": service_account_id,
    }
    request = urllib.request.Request(
        OPENAI_TOKEN_ENDPOINT,
        data=canonical_bytes(body),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LiveBoundaryError(
            "TOKEN_EXCHANGE_REJECTED",
            f"OpenAI token exchange rejected with HTTP {exc.code}",
        ) from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        json.JSONDecodeError,
    ) as exc:
        raise LiveBoundaryError(
            "TOKEN_EXCHANGE_REJECTED",
            "OpenAI token exchange failed",
        ) from exc
    return payload


def acquire_wif_credential(
    env: Mapping[str, str],
    *,
    oidc_fetch: Callable[[str, str], str] = _request_github_oidc_token,
    exchange: Callable[
        [str, str, str], dict[str, Any]
    ] = _exchange_wif_token,
) -> dict[str, Any]:
    provider_id = env.get("OPENAI_IDENTITY_PROVIDER_ID", "")
    service_account_id = env.get(
        "OPENAI_SERVICE_ACCOUNT_ID", ""
    )
    request_url = env.get(
        "ACTIONS_ID_TOKEN_REQUEST_URL", ""
    )
    request_token = env.get(
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN", ""
    )
    if not provider_id or not service_account_id:
        raise LiveBoundaryError(
            "WIF_CONFIGURATION_ABSENT",
            "OpenAI WIF provider/service-account metadata is absent",
        )
    if not request_url or not request_token:
        raise LiveBoundaryError(
            "OIDC_TOKEN_UNAVAILABLE",
            "GitHub OIDC request capability is absent",
        )

    subject_token = oidc_fetch(request_url, request_token)
    claims = _decode_jwt_claims(subject_token)
    validate_oidc_claims(claims)

    exchanged = exchange(
        subject_token, provider_id, service_account_id
    )
    access_token = exchanged.get("access_token")
    token_type = exchanged.get("token_type")
    expires_in = exchanged.get("expires_in")
    scope_raw = exchanged.get("scope", "")
    if (
        not isinstance(access_token, str)
        or not access_token
        or token_type != "Bearer"
    ):
        raise LiveBoundaryError(
            "TOKEN_EXCHANGE_REJECTED",
            "OpenAI token exchange returned no bearer token",
        )
    if (
        not isinstance(expires_in, int)
        or expires_in <= 0
        or expires_in > 3600
    ):
        raise LiveBoundaryError(
            "WIF_TOKEN_LIFETIME_INVALID",
            "OpenAI WIF token lifetime is outside policy",
        )
    if "refresh_token" in exchanged:
        raise LiveBoundaryError(
            "WIF_TOKEN_LIFETIME_INVALID",
            "refresh tokens are forbidden",
        )
    scope = sorted(
        item for item in str(scope_raw).split() if item
    )
    if scope != list(REQUIRED_WIF_SCOPE):
        raise LiveBoundaryError(
            "WIF_SCOPE_MISMATCH",
            "OpenAI WIF scope is not least-privilege api.model.request",
        )
    return {
        "access_token": access_token,
        "identity_provider_id_sha256": _sha256(
            provider_id.encode("utf-8")
        ),
        "service_account_id_sha256": _sha256(
            service_account_id.encode("utf-8")
        ),
        "scope": scope,
        "expires_in_seconds": expires_in,
    }


def _extract_output_text(response: Mapping[str, Any]) -> str:
    for item in response.get("output", []):
        if (
            not isinstance(item, Mapping)
            or item.get("type") != "message"
        ):
            continue
        for part in item.get("content", []):
            if (
                isinstance(part, Mapping)
                and part.get("type") == "output_text"
            ):
                text = part.get("text")
                if isinstance(text, str) and text:
                    return text
    raise LiveBoundaryError(
        "MALFORMED_RESPONSE",
        "Responses payload contains no output_text",
    )


def _call_once(
    payload: Mapping[str, Any],
    access_token: str,
    timeout_s: float,
) -> tuple[dict[str, Any], str | None, int]:
    request = urllib.request.Request(
        RESPONSES_ENDPOINT,
        data=canonical_bytes(payload),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "hwm-control-openai-boundary/1",
        },
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(
            request, timeout=timeout_s
        ) as response:
            raw = response.read(2_000_001)
            request_id = response.headers.get("x-request-id")
    except urllib.error.HTTPError as exc:
        request_id = exc.headers.get("x-request-id")
        if exc.code == 429:
            raise LiveBoundaryError(
                "RATE_LIMITED", request_id or "rate_limited"
            ) from exc
        if exc.code in (408, 500, 502, 503, 504):
            raise LiveBoundaryError(
                "TRANSIENT_PROVIDER_ERROR",
                request_id or "provider_transient",
            ) from exc
        if exc.code in (401, 403):
            raise LiveBoundaryError(
                "PROVIDER_AUTH_REJECTED",
                request_id or "provider_auth_rejected",
            ) from exc
        raise LiveBoundaryError(
            "PROVIDER_REQUEST_REJECTED",
            request_id or "provider_request_rejected",
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise LiveBoundaryError(
            "TIMEOUT", "provider_timeout"
        ) from exc
    except urllib.error.URLError as exc:
        raise LiveBoundaryError(
            "TRANSIENT_PROVIDER_ERROR",
            "provider_transport_error",
        ) from exc

    latency_ms = int((time.monotonic() - start) * 1000)
    if len(raw) > 2_000_000:
        raise LiveBoundaryError(
            "MALFORMED_RESPONSE",
            "provider response exceeds live boundary size",
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveBoundaryError(
            "MALFORMED_RESPONSE",
            "provider response is not JSON",
        ) from exc
    return value, request_id, latency_ms


def perform_provider_call(
    value: Mapping[str, Any],
    access_token: str,
    *,
    call_once: Callable[
        [Mapping[str, Any], str, float],
        tuple[dict[str, Any], str | None, int],
    ] = _call_once,
) -> dict[str, Any]:
    payload = build_responses_payload(value)
    budgets = value["semantic_input"]["budgets"]
    max_attempts = budgets["max_attempts"]
    timeout_s = budgets["timeout_ms"] / 1000.0
    total_latency_ms = 0

    for attempt in range(1, max_attempts + 1):
        try:
            response, request_id, latency_ms = call_once(
                payload, access_token, timeout_s
            )
            total_latency_ms += latency_ms
            try:
                text = _extract_output_text(response)
                parsed_output = json.loads(text)
            except (
                LiveBoundaryError,
                json.JSONDecodeError,
            ) as exc:
                raise LiveBoundaryError(
                    "MALFORMED_RESPONSE",
                    "structured response is malformed",
                ) from exc
            if (
                not isinstance(parsed_output, Mapping)
                or parsed_output.get("schema")
                != sc.OUTPUT_SCHEMA
            ):
                return {
                    "status": "degraded",
                    "attempts": attempt,
                    "failure_code": (
                        "UNSUPPORTED_SCHEMA_VERSION"
                    ),
                    "rate_limit_classification": "none",
                    "openai_request_id": request_id,
                    "latency_ms": total_latency_ms,
                    "response": None,
                }
            return {
                "status": "response_received",
                "attempts": attempt,
                "failure_code": None,
                "rate_limit_classification": "none",
                "openai_request_id": request_id,
                "latency_ms": total_latency_ms,
                "response": response,
            }
        except LiveBoundaryError as exc:
            retryable = exc.code in {
                "TIMEOUT",
                "TRANSIENT_PROVIDER_ERROR",
                "RATE_LIMITED",
                "MALFORMED_RESPONSE",
            }
            rate_class = (
                "http_429"
                if exc.code == "RATE_LIMITED"
                else "none"
            )
            if not retryable or attempt == max_attempts:
                return {
                    "status": "degraded",
                    "attempts": attempt,
                    "failure_code": (
                        "RETRY_EXHAUSTED"
                        if retryable
                        else exc.code
                    ),
                    "failure_detail_code": exc.code,
                    "rate_limit_classification": rate_class,
                    "openai_request_id": (
                        exc.message
                        if exc.message
                        not in {
                            "provider_timeout",
                            "provider_transport_error",
                        }
                        else None
                    ),
                    "latency_ms": total_latency_ms,
                    "response": None,
                }

    raise AssertionError("bounded retry loop exhausted unexpectedly")


def _empty_auth() -> dict[str, Any]:
    return {
        "mechanism": AUTH_MECHANISM,
        "issuer": OIDC_ISSUER,
        "audience": OIDC_AUDIENCE,
        "subject": OIDC_SUBJECT,
        "repository": REPOSITORY,
        "ref": REF,
        "workflow_ref": WORKFLOW_REF,
        "identity_provider_id_sha256": None,
        "service_account_id_sha256": None,
        "scope": [],
        "expires_in_seconds": 0,
        "oidc_token_recorded": False,
        "openai_access_token_recorded": False,
    }


def _auth_metadata(
    credential: Mapping[str, Any]
) -> dict[str, Any]:
    result = _empty_auth()
    result.update(
        {
            "identity_provider_id_sha256": credential[
                "identity_provider_id_sha256"
            ],
            "service_account_id_sha256": credential[
                "service_account_id_sha256"
            ],
            "scope": list(credential["scope"]),
            "expires_in_seconds": credential[
                "expires_in_seconds"
            ],
        }
    )
    return result


def _make_result(
    value: Mapping[str, Any],
    protected_main_sha: str,
    *,
    auth: Mapping[str, Any],
    status: str,
    call_result: Mapping[str, Any],
    verification: Mapping[str, Any] | None,
    failure_code: str | None,
) -> dict[str, Any]:
    response = call_result.get("response")
    usage = (
        response.get("usage", {})
        if isinstance(response, Mapping)
        else {}
    )
    provider = {
        "openai_request_id": call_result.get(
            "openai_request_id"
        ),
        "input_tokens": int(
            usage.get("input_tokens", 0) or 0
        ),
        "output_tokens": int(
            usage.get("output_tokens", 0) or 0
        ),
        "latency_ms": int(
            call_result.get("latency_ms", 0) or 0
        ),
        "attempts": int(
            call_result.get("attempts", 0) or 0
        ),
        "rate_limit_classification": str(
            call_result.get(
                "rate_limit_classification",
                "not_attempted",
            )
        ),
    }
    result = {
        "schema": RESULT_SCHEMA,
        "request_id": value["request_id"],
        "trust_policy": TRUST_POLICY,
        "protected_main_sha": protected_main_sha,
        "auth": dict(auth),
        "status": status,
        "classification": "derived_non_authoritative",
        "provenance": sanitized_provenance(
            value, protected_main_sha
        ),
        "provider": provider,
        "verification": {
            "decision": (
                verification["decision"]
                if verification
                else "not_run"
            ),
            "materialization_allowed": bool(
                verification
                and verification["materialization_allowed"]
            ),
            "codes": (
                list(verification["codes"])
                if verification
                else []
            ),
        },
        "failure_code": failure_code,
        "fallback": {
            "mode": "deterministic_task_context_only",
            "deterministic_task_context_usable": True,
            "semantic_materialization": (
                "accepted" if status == "accepted" else "none"
            ),
        },
        "sanitized_log_fields": list(
            _ALLOWED_LOG_FIELDS
        ),
    }
    _validate_schema(
        "openai-live-result.v1.schema.json", result
    )
    return result


def execute_live(
    value: Mapping[str, Any],
    protected_main_sha: str,
    runtime: Mapping[str, str],
    env: Mapping[str, str],
    *,
    context_check: Callable[
        [Mapping[str, Any]], Mapping[str, Any]
    ] = fetch_and_verify_task_context,
    credential_factory: Callable[
        [Mapping[str, str]], dict[str, Any]
    ] = acquire_wif_credential,
    call_once: Callable[
        [Mapping[str, Any], str, float],
        tuple[dict[str, Any], str | None, int],
    ] = _call_once,
) -> dict[str, Any]:
    # Public/deterministic checks are completed before any OIDC token request.
    validate_live_request(value)
    assert_runtime_context(protected_main_sha, runtime)
    context_check(value)

    try:
        credential = credential_factory(env)
    except LiveBoundaryError as exc:
        return _make_result(
            value,
            protected_main_sha,
            auth=_empty_auth(),
            status="degraded",
            call_result={
                "attempts": 0,
                "latency_ms": 0,
                "rate_limit_classification": (
                    "not_attempted"
                ),
                "openai_request_id": None,
                "response": None,
            },
            verification=None,
            failure_code=exc.code,
        )

    # Both the GitHub OIDC JWT and the exchanged access token stay in memory.
    access_token = credential["access_token"]
    call_result = perform_provider_call(
        value, access_token, call_once=call_once
    )
    access_token = None  # do not persist or pass to verifier

    if call_result["status"] != "response_received":
        return _make_result(
            value,
            protected_main_sha,
            auth=_auth_metadata(credential),
            status="degraded",
            call_result=call_result,
            verification=None,
            failure_code=str(
                call_result.get("failure_code")
                or "PROVIDER_FAILURE"
            ),
        )

    try:
        text = _extract_output_text(
            call_result["response"]
        )
        semantic_output = json.loads(text)
    except (
        LiveBoundaryError,
        json.JSONDecodeError,
    ):
        return _make_result(
            value,
            protected_main_sha,
            auth=_auth_metadata(credential),
            status="degraded",
            call_result=call_result,
            verification=None,
            failure_code="MALFORMED_RESPONSE",
        )

    verification = sc.verify_semantic_output(
        value["semantic_input"], semantic_output
    )
    accepted = verification["decision"] == "accept"
    return _make_result(
        value,
        protected_main_sha,
        auth=_auth_metadata(credential),
        status="accepted" if accepted else "rejected",
        call_result=call_result,
        verification=verification,
        failure_code=(
            None if accepted else "VERIFIER_REJECTED"
        ),
    )


def _runtime_from_env() -> dict[str, str]:
    return {
        "repository": os.environ.get(
            "HWM_RUNTIME_REPOSITORY", ""
        ),
        "ref": os.environ.get("HWM_RUNTIME_REF", ""),
        "workflow_ref": os.environ.get(
            "HWM_RUNTIME_WORKFLOW_REF", ""
        ),
        "event_name": os.environ.get(
            "HWM_RUNTIME_EVENT_NAME", ""
        ),
        "sha": os.environ.get("HWM_RUNTIME_SHA", ""),
    }


def _cmd_preflight(args: argparse.Namespace) -> int:
    value = load_request(args.request_id)
    assert_runtime_context(
        args.protected_main_sha, _runtime_from_env()
    )
    fetch_and_verify_task_context(value)
    provenance = sanitized_provenance(
        value, args.protected_main_sha
    )
    # Digest/status-only output: never prompt text, model output, or tokens.
    print(
        json.dumps(
            {"status": "preflight_ok", **provenance},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _cmd_execute(args: argparse.Namespace) -> int:
    value = load_request(args.request_id)
    result = execute_live(
        value,
        args.protected_main_sha,
        _runtime_from_env(),
        os.environ,
    )
    # Result schema is sanitized: no prompt/output/token fields exist.
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "accepted" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "execute"):
        child = sub.add_parser(command)
        child.add_argument("--request-id", required=True)
        child.add_argument(
            "--protected-main-sha",
            required=True,
            type=str,
        )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "preflight":
            return _cmd_preflight(args)
        return _cmd_execute(args)
    except LiveBoundaryError as exc:
        # Never include exception source data; only a typed code is printable.
        print(
            json.dumps(
                {"status": "rejected", "failure_code": exc.code},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
