from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

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


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, coerced))


def _coerce_bool(value: Any, default: bool = False) -> bool:
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


class AppointmentEventsContactInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    email: str | None = None
    name: str | None = None


class AppointmentEventsInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    timezone: str | None = "Europe/Madrid"
    status: str | None = None
    limit: int | None = 5
    service_ref: str | None = None
    owner_ref: str | None = None
    contact: AppointmentEventsContactInput | None = None


def _empty_payload(message: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "found": False,
        "count": 0,
        "items": [],
        "message": message,
        "raw_summary": {},
        "error_code": error_code,
    }


def _normalize_success_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload("Invalid response from appointment events service.", "upstream_error")

    cleaned = _normalize_value(payload)
    if isinstance(cleaned.get("result"), dict):
        cleaned = cleaned["result"]
    elif isinstance(cleaned.get("data"), dict):
        cleaned = cleaned["data"]

    items = cleaned.get("items")
    if not isinstance(items, list):
        items = cleaned.get("events")
    if not isinstance(items, list):
        items = []

    count = cleaned.get("count")
    if not isinstance(count, int):
        count = len(items)

    found = cleaned.get("found")
    if found is None:
        found = count > 0

    message = cleaned.get("message")
    if not isinstance(message, str) or message.strip() == "":
        message = f"Se encontraron {count} cita(s)." if count > 0 else "No se encontraron citas."

    normalized = {
        "ok": _coerce_bool(cleaned.get("ok"), default=True),
        "found": _coerce_bool(found, default=count > 0),
        "count": count,
        "items": items,
        "message": message,
        "raw_summary": cleaned.get("raw_summary") if isinstance(cleaned.get("raw_summary"), dict) else {},
    }

    if "categories" in cleaned and isinstance(cleaned["categories"], list):
        normalized["categories"] = cleaned["categories"]

    if "error_code" in cleaned:
        normalized["error_code"] = cleaned["error_code"]

    return normalized


async def _post_appointment_events(url: str, token: str | None, timeout_seconds: float, body: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return response.json()


async def appointment_events(
    tenant_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    timezone: str | None = "Europe/Madrid",
    status: str | None = None,
    limit: int | None = 5,
    service_ref: str | None = None,
    owner_ref: str | None = None,
    contact: AppointmentEventsContactInput | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get appointment/calendar events for a tenant and optional contact, date range or filters."""
    payload = AppointmentEventsInput(
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
        timezone=timezone,
        status=status,
        limit=limit,
        service_ref=service_ref,
        owner_ref=owner_ref,
        contact=contact,
    )

    settings = get_settings()
    webhook_url = _normalize_text(settings.appointment_events_webhook_url)
    webhook_token = _normalize_text(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.appointment_events_timeout_seconds

    normalized_tenant_id = _normalize_text(payload.tenant_id)
    normalized_date_from = _normalize_text(payload.date_from)
    normalized_date_to = _normalize_text(payload.date_to)
    normalized_timezone = _normalize_text(payload.timezone) or "Europe/Madrid"
    normalized_status = _normalize_text(payload.status)
    normalized_service_ref = _normalize_text(payload.service_ref)
    normalized_owner_ref = _normalize_text(payload.owner_ref)
    normalized_limit = _coerce_int(payload.limit, 5, 1, 10)

    normalized_contact = payload.contact.model_dump() if isinstance(payload.contact, AppointmentEventsContactInput) else payload.contact
    if isinstance(normalized_contact, dict):
        normalized_contact = {key: _normalize_text(value) for key, value in normalized_contact.items()}

    if webhook_url is None:
        return _empty_payload("Appointment events service is not configured.", "not_configured")

    if normalized_tenant_id is None:
        return _empty_payload("tenant_id is required to retrieve appointment events.", "validation_error")

    body = {
        "tool": "appointment_events",
        "tenant_id": normalized_tenant_id,
        "date_from": normalized_date_from,
        "date_to": normalized_date_to,
        "timezone": normalized_timezone,
        "status": normalized_status,
        "limit": normalized_limit,
        "service_ref": normalized_service_ref,
        "owner_ref": normalized_owner_ref,
        "contact": normalized_contact if normalized_contact is not None else None,
        "source": "mcp-gateway",
    }

    try:
        upstream_payload = await _post_appointment_events(webhook_url, webhook_token, timeout_seconds, body)
    except httpx.TimeoutException:
        return _empty_payload("Appointment events request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_payload("Appointment events service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_payload("Appointment events service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while retrieving appointment events")
        return _empty_payload("Appointment events service is unavailable.", "upstream_error")

    return _normalize_success_payload(upstream_payload)
