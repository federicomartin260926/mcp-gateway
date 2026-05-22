from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict

from app.settings import get_settings
from app.tools._appointment_common import extract_request_authorization, post_webhook

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


class AppointmentAvailabilityContactInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    email: str | None = None
    name: str | None = None


class AppointmentAvailabilityInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    timezone: str | None = "Europe/Madrid"
    duration_minutes: int | None = 30
    limit: int | None = 6
    service_ref: str | None = None
    owner_ref: str | None = None
    contact: AppointmentAvailabilityContactInput | None = None


def _empty_payload(timezone: str, message: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "available": False,
        "timezone": timezone,
        "slots": [],
        "message": message,
        "error_code": error_code,
    }


def _normalize_success_payload(payload: Any, fallback_timezone: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload(fallback_timezone, "Invalid response from appointment availability service.", "upstream_error")

    cleaned = _normalize_value(payload)
    if isinstance(cleaned.get("result"), dict):
        cleaned = cleaned["result"]
    elif isinstance(cleaned.get("data"), dict):
        cleaned = cleaned["data"]

    timezone = cleaned.get("timezone") if isinstance(cleaned.get("timezone"), str) and cleaned.get("timezone").strip() else fallback_timezone
    slots = cleaned.get("slots") if isinstance(cleaned.get("slots"), list) else []
    message = cleaned.get("message") if isinstance(cleaned.get("message"), str) and cleaned.get("message").strip() else "Appointment availability retrieved."

    normalized = {
        "ok": _coerce_bool(cleaned.get("ok"), default=True),
        "available": _coerce_bool(cleaned.get("available"), default=False),
        "timezone": timezone,
        "slots": slots,
        "message": message,
        "raw_summary": cleaned.get("raw_summary") if isinstance(cleaned.get("raw_summary"), dict) else {},
    }
    if "error_code" in cleaned:
        normalized["error_code"] = cleaned["error_code"]
    return normalized


async def _post_appointment_availability(
    url: str,
    token: str | None,
    timeout_seconds: float,
    body: dict[str, Any],
    downstream_authorization: str | None = None,
) -> dict[str, Any]:
    return await post_webhook(
        url,
        token,
        timeout_seconds,
        body,
        downstream_authorization=downstream_authorization,
        tool_name="appointment_availability",
    )


async def appointment_availability(
    tenant_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    timezone: str | None = "Europe/Madrid",
    duration_minutes: int | None = 30,
    limit: int | None = 6,
    service_ref: str | None = None,
    owner_ref: str | None = None,
    contact: AppointmentAvailabilityContactInput | dict[str, Any] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Get appointment availability slots for a tenant, date range and optional contact."""
    payload = AppointmentAvailabilityInput(
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
        timezone=timezone,
        duration_minutes=duration_minutes,
        limit=limit,
        service_ref=service_ref,
        owner_ref=owner_ref,
        contact=contact,
    )

    settings = get_settings()
    webhook_url = _normalize_text(settings.appointment_availability_webhook_url)
    webhook_token = _normalize_text(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.appointment_availability_timeout_seconds
    downstream_authorization = extract_request_authorization(ctx)

    normalized_timezone = _normalize_text(payload.timezone) or "Europe/Madrid"
    normalized_date_from = _normalize_text(payload.date_from)
    normalized_date_to = _normalize_text(payload.date_to)
    normalized_tenant_id = _normalize_text(payload.tenant_id)
    normalized_service_ref = _normalize_text(payload.service_ref)
    normalized_owner_ref = _normalize_text(payload.owner_ref)
    normalized_duration = _coerce_int(payload.duration_minutes, 30, 5, 240)
    normalized_limit = _coerce_int(payload.limit, 6, 1, 10)
    normalized_contact = payload.contact.model_dump() if isinstance(payload.contact, AppointmentAvailabilityContactInput) else payload.contact
    if isinstance(normalized_contact, dict):
        normalized_contact = {key: _normalize_text(value) for key, value in normalized_contact.items()}

    if webhook_url is None:
        return _empty_payload(
            normalized_timezone,
            "Appointment availability service is not configured.",
            "not_configured",
        )

    if normalized_date_from is None or normalized_date_to is None:
        return _empty_payload(
            normalized_timezone,
            "date_from and date_to are required to retrieve appointment availability.",
            "validation_error",
        )

    body = {
        "tool": "appointment_availability",
        "tenant_id": normalized_tenant_id,
        "date_from": normalized_date_from,
        "date_to": normalized_date_to,
        "timezone": normalized_timezone,
        "duration_minutes": normalized_duration,
        "limit": normalized_limit,
        "service_ref": normalized_service_ref,
        "owner_ref": normalized_owner_ref,
        "contact": normalized_contact if normalized_contact is not None else None,
        "source": "mcp-gateway",
    }

    try:
        upstream_payload = await _post_appointment_availability(
            webhook_url,
            webhook_token,
            timeout_seconds,
            body,
            downstream_authorization=downstream_authorization,
        )
    except httpx.TimeoutException:
        return _empty_payload(normalized_timezone, "Appointment availability request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_payload(normalized_timezone, "Appointment availability service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_payload(normalized_timezone, "Appointment availability service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while retrieving appointment availability")
        return _empty_payload(normalized_timezone, "Appointment availability service is unavailable.", "upstream_error")

    return _normalize_success_payload(upstream_payload, normalized_timezone)
