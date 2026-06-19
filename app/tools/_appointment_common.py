from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import Context

logger = logging.getLogger(__name__)


def _mask_token(token: str | None) -> str | None:
    if token is None:
        return None

    normalized = token.strip()
    if normalized == "":
        return None

    if len(normalized) <= 10:
        return f"{normalized[:4]}...{normalized[-2:]}"

    return f"{normalized[:6]}...{normalized[-4:]}"


def summarize_authorization(authorization: str | None) -> tuple[bool, str | None, str | None]:
    if authorization is None:
        return False, None, None

    normalized = authorization.strip()
    if normalized == "":
        return False, None, None

    parts = normalized.split(None, 1)
    if len(parts) == 2:
        scheme = parts[0].capitalize()
        token = parts[1]
    else:
        scheme = None
        token = normalized

    return True, scheme, _mask_token(token)


def extract_request_authorization(ctx: Context | None) -> str | None:
    if ctx is None:
        return None

    request = getattr(getattr(ctx, "request_context", None), "request", None)
    headers = getattr(request, "headers", None)
    if headers is None:
        return None

    for header_name in ("Authorization", "authorization"):
        try:
            authorization = headers.get(header_name, "")
        except Exception:
            continue

        if isinstance(authorization, str):
            normalized = authorization.strip()
            if normalized:
                return normalized

    return None


def extract_request_id(ctx: Context | None) -> str | None:
    if ctx is None:
        return None

    request = getattr(getattr(ctx, "request_context", None), "request", None)
    state = getattr(request, "state", None)
    request_id = getattr(state, "request_id", None)
    if isinstance(request_id, str):
        normalized = request_id.strip()
        if normalized:
            return normalized

    return None


def build_webhook_headers(
    token: str | None,
    downstream_authorization: str | None = None,
    request_id: str | None = None,
    auth_header_name: str = "Authorization",
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers[auth_header_name] = f"Bearer {token}"
    if downstream_authorization:
        headers["X-Downstream-Authorization"] = downstream_authorization
    if request_id:
        headers["X-Request-Id"] = request_id
    return headers


def log_webhook_auth(tool_name: str, downstream_authorization: str | None, request_id: str | None = None) -> None:
    has_authorization, authorization_scheme, token_preview = summarize_authorization(downstream_authorization)
    logger.info(
        "n8n_webhook request_id=%s tool=%s downstream_authorization_present=%s downstream_authorization_scheme=%s downstream_authorization_preview=%s",
        request_id or "-",
        tool_name,
        has_authorization,
        authorization_scheme or "-",
        token_preview or "-",
    )


async def post_webhook(
    url: str,
    token: str | None,
    timeout_seconds: float,
    body: dict[str, Any],
    downstream_authorization: str | None = None,
    auth_header_name: str = "Authorization",
    tool_name: str = "n8n_webhook",
    request_id: str | None = None,
) -> dict[str, Any]:
    headers = build_webhook_headers(
        token,
        downstream_authorization,
        request_id=request_id,
        auth_header_name=auth_header_name,
    )
    log_webhook_auth(tool_name, downstream_authorization, request_id=request_id)

    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return response.json()


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if normalized.lower() in {"null", "none", "nil", "undefined"}:
        return None

    return normalized


def normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, dict):
        return {key: normalize_value(inner_value) for key, inner_value in value.items()}
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    return value


def coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, coerced))


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return bool(value)
