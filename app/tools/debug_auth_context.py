from __future__ import annotations

import logging
from typing import Any

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


def _extract_authorization(request_headers: Any) -> str | None:
    if request_headers is None:
        return None

    try:
        authorization = request_headers.get("Authorization", "")
    except Exception:
        return None

    if not isinstance(authorization, str):
        return None

    normalized = authorization.strip()
    return normalized or None


async def debug_auth_context(ctx: Context) -> dict[str, Any]:
    request = ctx.request_context.request
    authorization = _extract_authorization(getattr(request, "headers", None))
    has_authorization = authorization is not None

    authorization_scheme = None
    token_preview = None
    if authorization is not None:
        parts = authorization.split(None, 1)
        if len(parts) == 2:
            authorization_scheme = parts[0].capitalize()
            token_preview = _mask_token(parts[1])
        else:
            token_preview = _mask_token(authorization)

    logger.info(
        "debug_auth_context request_id=%s has_authorization=%s authorization_scheme=%s token_preview=%s",
        ctx.request_id,
        has_authorization,
        authorization_scheme or "-",
        token_preview or "-",
    )

    return {
        "has_authorization": has_authorization,
        "authorization_scheme": authorization_scheme,
        "token_preview": token_preview,
    }
