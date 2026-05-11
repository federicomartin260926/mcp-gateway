from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.settings import get_settings

logger = logging.getLogger(__name__)


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if normalized.lower() in {"null", "none", "nil", "undefined"}:
        return None

    return normalized


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, dict):
        return {key: _normalize_value(inner_value) for key, inner_value in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _coerce_bool(value: Any, default: bool | None = False) -> bool | None:
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


def _coerce_limit(value: Any, default: int, minimum: int, maximum: int) -> tuple[int, bool]:
    if value is None:
        return default, False
    if isinstance(value, bool):
        return default, True
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default, True
    return max(minimum, min(maximum, coerced)), False


class ServicesSearchInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str | None = None
    query: str | None = None
    bookable: bool | None = None
    active: bool | None = True
    category: str | None = None
    limit: int | None = 10


def _empty_payload(message: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "found": False,
        "count": 0,
        "items": [],
        "categories": [],
        "message": message,
        "raw_summary": {},
        "error_code": error_code,
    }


def _normalize_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    items: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            items.append(_normalize_value(item))
    return items


def _normalize_success_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload("Invalid response from services search service.", "upstream_error")

    cleaned = _normalize_value(payload)
    if isinstance(cleaned.get("result"), dict):
        cleaned = cleaned["result"]
    elif isinstance(cleaned.get("data"), dict):
        cleaned = cleaned["data"]

    items = _normalize_items(cleaned.get("items"))
    categories = _normalize_items(cleaned.get("categories"))
    message = cleaned.get("message") if isinstance(cleaned.get("message"), str) and cleaned.get("message").strip() else "Services search retrieved."
    count = cleaned.get("count")
    if not isinstance(count, int):
        count = len(items)

    normalized = {
        "ok": _coerce_bool(cleaned.get("ok"), default=True),
        "found": _coerce_bool(cleaned.get("found"), default=bool(items)),
        "count": count,
        "items": items,
        "categories": categories,
        "message": message,
        "raw_summary": cleaned.get("raw_summary") if isinstance(cleaned.get("raw_summary"), dict) else {},
    }
    if "error_code" in cleaned:
        normalized["error_code"] = cleaned["error_code"]
    return normalized


async def _post_services_search(url: str, token: str | None, timeout_seconds: float, body: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return response.json()


async def services_search(
    tenant_id: str | None = None,
    query: str | None = None,
    bookable: bool | None = None,
    active: bool | None = True,
    category: str | None = None,
    limit: int | None = 10,
) -> dict[str, Any]:
    """Search services and products in the CRM through n8n."""
    if isinstance(limit, bool):
        return _empty_payload("limit must be a valid integer.", "validation_error")

    try:
        payload = ServicesSearchInput(
            tenant_id=tenant_id,
            query=query,
            bookable=bookable,
            active=active,
            category=category,
            limit=limit,
        )
    except ValidationError:
        return _empty_payload("Request payload is invalid.", "validation_error")

    settings = get_settings()
    webhook_url = _normalize_text(settings.services_search_webhook_url)
    webhook_token = _normalize_text(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.services_search_timeout_seconds

    normalized_tenant_id = _normalize_text(payload.tenant_id)
    normalized_query = _normalize_text(payload.query)
    normalized_category = _normalize_text(payload.category)
    normalized_bookable = None if payload.bookable is None else _coerce_bool(payload.bookable, default=None)
    normalized_active = _coerce_bool(payload.active, default=True)

    if webhook_url is None:
        return _empty_payload("Services search tool is not configured.", "not_configured")

    normalized_limit, limit_invalid = _coerce_limit(payload.limit, 10, 1, 30)
    if limit_invalid:
        return _empty_payload("limit must be a valid integer.", "validation_error")

    body = {
        "tool": "services_search",
        "tenant_id": normalized_tenant_id,
        "query": normalized_query,
        "bookable": normalized_bookable,
        "active": normalized_active,
        "category": normalized_category,
        "limit": normalized_limit,
        "source": "mcp-gateway",
    }

    try:
        upstream_payload = await _post_services_search(webhook_url, webhook_token, timeout_seconds, body)
    except httpx.TimeoutException:
        return _empty_payload("Services search request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_payload("Services search service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_payload("Services search service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while searching services")
        return _empty_payload("Services search service is unavailable.", "upstream_error")

    normalized_response = _normalize_success_payload(upstream_payload)
    if "error_code" not in normalized_response and not normalized_response["ok"]:
        normalized_response["error_code"] = "upstream_error"
    return normalized_response
