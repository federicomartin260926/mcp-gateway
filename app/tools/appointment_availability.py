from __future__ import annotations

import logging
import re
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


def _looks_like_uuid(value: str) -> bool:
    return re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        value.strip(),
    ) is not None


def _looks_like_technical_ref(value: str) -> bool:
    normalized = value.strip()
    if normalized == "":
        return False

    if _looks_like_uuid(normalized):
        return True

    # Slugs, integration keys and email-like refs are considered technical/stable.
    if "@" in normalized:
        return True

    if re.fullmatch(r"[a-z0-9][a-z0-9._:-]*[a-z0-9]", normalized):
        return True

    return False


def _split_owner_ref_and_name(owner_ref: str | None, owner_name: str | None) -> tuple[str | None, str | None]:
    """Keep technical refs in owner_ref and move human names to owner_name.

    Older prompts/tool schemas exposed only owner_ref, so the LLM could send values like
    "María Gutiérrez" there. Downstream CRM availability expects technical owner IDs/refs,
    not human display names. This helper keeps backward compatibility while encouraging
    the new owner_name field.
    """
    normalized_ref = _normalize_text(owner_ref)
    normalized_name = _normalize_text(owner_name)

    if normalized_ref is None:
        return None, normalized_name

    if _looks_like_technical_ref(normalized_ref):
        return normalized_ref, normalized_name

    if normalized_name is None:
        return None, normalized_ref

    return normalized_ref, normalized_name


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
    timezone: str | None = None
    duration_minutes: int | None = 30
    limit: int | None = 50
    service_id: str | None = None
    service_ref: str | None = None
    owner_id: str | None = None
    owner_ref: str | None = None
    owner_name: str | None = None
    contact: AppointmentAvailabilityContactInput | None = None


def _empty_payload(timezone: str, message: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "available": False,
        "status": error_code,
        "timezone": timezone,
        "slots": [],
        "message": message,
        "error_code": error_code,
    }


def _normalize_success_payload(
    payload: Any,
    fallback_timezone: str,
    requested_limit: int | None = None,
    requested_service_id: str | None = None,
    requested_service_ref: str | None = None,
    requested_owner_id: str | None = None,
    requested_owner_ref: str | None = None,
    requested_owner_name: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload(fallback_timezone, "Invalid response from appointment availability service.", "upstream_error")

    cleaned = _normalize_value(payload)
    if isinstance(cleaned.get("result"), dict):
        cleaned = cleaned["result"]
    elif isinstance(cleaned.get("data"), dict):
        cleaned = cleaned["data"]

    cleaned_timezone = cleaned.get("timezone")
    business_timezone = cleaned.get("businessTimezone") or cleaned.get("business_timezone")
    timezone = (
        cleaned_timezone
        if isinstance(cleaned_timezone, str) and cleaned_timezone.strip()
        else business_timezone
        if isinstance(business_timezone, str) and business_timezone.strip()
        else fallback_timezone
        if isinstance(fallback_timezone, str) and fallback_timezone.strip()
        else ""
    )
    slots = cleaned.get("slots") if isinstance(cleaned.get("slots"), list) else []
    if requested_limit is not None:
        slots = slots[:requested_limit]
    message = cleaned.get("message") if isinstance(cleaned.get("message"), str) and cleaned.get("message").strip() else "Appointment availability retrieved."
    raw_summary = cleaned.get("raw_summary") if isinstance(cleaned.get("raw_summary"), dict) else {}
    raw_total_slots = _coerce_int(raw_summary.get("totalSlots"), len(slots), 0, 1_000_000)

    returned_slots = len(slots)
    truncated = raw_total_slots > returned_slots

    normalized = {
        "ok": _coerce_bool(cleaned.get("ok"), default=True),
        "available": _coerce_bool(cleaned.get("available"), default=raw_total_slots > 0),
        "timezone": timezone,
        "slots": slots,
        "message": message,
        "raw_summary": {
            **raw_summary,
            "mode": raw_summary.get("mode") if raw_summary.get("mode") is not None else cleaned.get("mode"),
            "durationMinutes": raw_summary.get("durationMinutes")
            if raw_summary.get("durationMinutes") is not None
            else cleaned.get("durationMinutes"),
            "ownersCount": raw_summary.get("ownersCount")
            if raw_summary.get("ownersCount") is not None
            else cleaned.get("ownersCount"),
            "totalSlots": raw_total_slots,
            "returnedSlots": returned_slots,
            "truncated": truncated,
            "serviceId": raw_summary.get("serviceId") if raw_summary.get("serviceId") is not None else requested_service_id,
            "serviceRef": raw_summary.get("serviceRef") if raw_summary.get("serviceRef") is not None else requested_service_ref,
            "ownerId": raw_summary.get("ownerId") if raw_summary.get("ownerId") is not None else requested_owner_id,
            "ownerRef": raw_summary.get("ownerRef") if raw_summary.get("ownerRef") is not None else requested_owner_ref,
            "ownerName": raw_summary.get("ownerName") if raw_summary.get("ownerName") is not None else requested_owner_name,
            "requestedLimit": requested_limit,
        },
    }

    owner_resolution = cleaned.get("ownerResolution") or cleaned.get("owner_resolution")
    if isinstance(owner_resolution, dict):
        normalized["ownerResolution"] = owner_resolution

    status = cleaned.get("status")
    if isinstance(status, str) and status.strip():
        normalized["status"] = status.strip()

    if "error_code" in cleaned:
        normalized["error_code"] = cleaned["error_code"]

    timezone_source = cleaned.get("timezone_source")
    if not isinstance(timezone_source, str) or not timezone_source.strip():
        timezone_source = cleaned.get("timezoneSource")
    if not isinstance(timezone_source, str) or not timezone_source.strip():
        timezone_source = cleaned.get("businessTimezoneSource")
    if not isinstance(timezone_source, str) or not timezone_source.strip():
        timezone_source = cleaned.get("business_timezone_source")
    if isinstance(timezone_source, str) and timezone_source.strip():
        normalized["timezone_source"] = timezone_source.strip()

    business_timezone_source = cleaned.get("businessTimezoneSource")
    if not isinstance(business_timezone_source, str) or not business_timezone_source.strip():
        business_timezone_source = cleaned.get("business_timezone_source")
    if isinstance(business_timezone_source, str) and business_timezone_source.strip():
        normalized["business_timezone_source"] = business_timezone_source.strip()

    if isinstance(business_timezone, str) and business_timezone.strip():
        normalized["business_timezone"] = business_timezone.strip()

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
    *,
    timezone: str | None = None,
    duration_minutes: int | None = 30,
    limit: int | None = 50,
    service_id: str | None = None,
    service_ref: str | None = None,
    owner_id: str | None = None,
    owner_ref: str | None = None,
    owner_name: str | None = None,
    contact: AppointmentAvailabilityContactInput | dict[str, Any] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Get appointment availability slots for a tenant, date range and optional contact.

    Prefer `service_id` with the canonical UUID returned by `services_search`.
    Use `service_ref` only as a fallback with slug, integration key or external reference.

    Owner filtering:
    - Prefer `owner_id` when the canonical owner UUID is known from previous slots,
      availability results or structured context.
    - Use `owner_ref` only for a stable technical reference, such as a slug, email-like
      integration key or external reference. Do not put human display names in owner_ref.
    - Use `owner_name` for human names mentioned by the user, such as "María", "Mary",
      "María Gutiérrez" or "Claudia". The downstream CRM/n8n layer may resolve it against
      bookable active owners for the tenant/service and can return slots for all matches.

    `timezone` is optional. Do not invent it. If omitted, downstream CRM resolves the business
    timezone from tenant/branch configuration. Use it only when the caller has an explicit
    reliable timezone context.
    """
    safe_owner_ref, safe_owner_name = _split_owner_ref_and_name(owner_ref, owner_name)

    payload = AppointmentAvailabilityInput(
        tenant_id=tenant_id,
        date_from=date_from,
        date_to=date_to,
        timezone=timezone,
        duration_minutes=duration_minutes,
        limit=limit,
        service_id=service_id,
        service_ref=service_ref,
        owner_id=owner_id,
        owner_ref=safe_owner_ref,
        owner_name=safe_owner_name,
        contact=contact,
    )

    settings = get_settings()
    webhook_url = _normalize_text(settings.appointment_availability_webhook_url)
    webhook_token = _normalize_text(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.appointment_availability_timeout_seconds
    downstream_authorization = extract_request_authorization(ctx)

    normalized_timezone = _normalize_text(payload.timezone)
    normalized_date_from = _normalize_text(payload.date_from)
    normalized_date_to = _normalize_text(payload.date_to)
    normalized_tenant_id = _normalize_text(payload.tenant_id)
    normalized_service_ref = _normalize_text(payload.service_ref)
    normalized_service_id = _normalize_text(payload.service_id)
    normalized_owner_id = _normalize_text(payload.owner_id)
    normalized_owner_ref, normalized_owner_name = _split_owner_ref_and_name(
        payload.owner_ref,
        payload.owner_name,
    )
    normalized_duration = _coerce_int(payload.duration_minutes, 30, 5, 240)
    normalized_limit = _coerce_int(payload.limit, 50, 1, 150)
    response_timezone = normalized_timezone or ""
    normalized_contact = payload.contact.model_dump() if isinstance(payload.contact, AppointmentAvailabilityContactInput) else payload.contact
    if isinstance(normalized_contact, dict):
        normalized_contact = {key: _normalize_text(value) for key, value in normalized_contact.items()}

    if webhook_url is None:
        return _empty_payload(
            response_timezone,
            "Appointment availability service is not configured.",
            "not_configured",
        )

    if normalized_date_from is None or normalized_date_to is None:
        return _empty_payload(
            response_timezone,
            "date_from and date_to are required to retrieve appointment availability.",
            "validation_error",
        )

    body = {
        "tool": "appointment_availability",
        "tenant_id": normalized_tenant_id,
        "date_from": normalized_date_from,
        "date_to": normalized_date_to,
        "duration_minutes": normalized_duration,
        "limit": normalized_limit,
        "service_id": normalized_service_id,
        "service_ref": normalized_service_ref,
        "owner_id": normalized_owner_id,
        "owner_ref": normalized_owner_ref,
        "owner_name": normalized_owner_name,
        "contact": normalized_contact if normalized_contact is not None else None,
        "source": "mcp-gateway",
    }
    if normalized_timezone is not None:
        body["timezone"] = normalized_timezone

    try:
        upstream_payload = await _post_appointment_availability(
            webhook_url,
            webhook_token,
            timeout_seconds,
            body,
            downstream_authorization=downstream_authorization,
        )
    except httpx.TimeoutException:
        return _empty_payload(response_timezone, "Appointment availability request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_payload(response_timezone, "Appointment availability service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_payload(response_timezone, "Appointment availability service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while retrieving appointment availability")
        return _empty_payload(response_timezone, "Appointment availability service is unavailable.", "upstream_error")

    return _normalize_success_payload(
        upstream_payload,
        response_timezone,
        requested_limit=normalized_limit,
        requested_service_id=normalized_service_id,
        requested_service_ref=normalized_service_ref,
        requested_owner_id=normalized_owner_id,
        requested_owner_ref=normalized_owner_ref,
        requested_owner_name=normalized_owner_name,
    )
