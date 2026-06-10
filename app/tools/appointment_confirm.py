from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict, ValidationError

from app.settings import get_settings
from app.tools._appointment_common import coerce_bool, extract_request_authorization, normalize_text, normalize_value, post_webhook

logger = logging.getLogger(__name__)


class AppointmentConfirmContactInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    email: str | None = None
    name: str | None = None


class AppointmentConfirmInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    timezone: str | None = None
    service_id: str | None = None
    service_ref: str | None = None
    owner_id: str | None = None
    owner_ref: str | None = None
    contact: AppointmentConfirmContactInput | None = None
    title: str | None = None
    notes: str | None = None
    conversation_id: str | None = None
    entrypoint_ref: str | None = None


def _empty_payload(message: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "confirmed": False,
        "status": error_code,
        "appointment": {},
        "message": message,
        "raw_summary": {},
        "error_code": error_code,
    }


def _normalize_contact(contact: Any) -> dict[str, Any] | None:
    if contact is None:
        return None

    normalized = contact.model_dump() if isinstance(contact, AppointmentConfirmContactInput) else contact
    if not isinstance(normalized, dict):
        return None

    return {key: normalize_text(value) for key, value in normalized.items()}


def _build_slot(
    start_at: str | None,
    end_at: str | None,
    owner_id: str | None,
    owner_ref: str | None,
) -> dict[str, Any] | None:
    if start_at is None and end_at is None and owner_id is None and owner_ref is None:
        return None

    slot: dict[str, Any] = {
        "start": start_at,
        "end": end_at,
    }
    owner: dict[str, Any] = {}
    if owner_id is not None:
        owner["id"] = owner_id
    elif owner_ref is not None:
        owner["id"] = owner_ref

    if owner_ref is not None and owner_ref != owner.get("id"):
        owner["ref"] = owner_ref

    if owner:
        slot["owner"] = owner

    return slot


def _normalize_success_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload("Invalid response from appointment confirm service.", "upstream_error")

    cleaned = normalize_value(payload)
    if isinstance(cleaned.get("result"), dict):
        cleaned = cleaned["result"]
    elif isinstance(cleaned.get("data"), dict):
        cleaned = cleaned["data"]

    appointment = cleaned.get("appointment") if isinstance(cleaned.get("appointment"), dict) else {}
    appointment_id = cleaned.get("appointment_id")
    if not isinstance(appointment_id, str) or appointment_id.strip() == "":
        appointment_id = appointment.get("id") if isinstance(appointment.get("id"), str) else None
    if isinstance(appointment_id, str):
        appointment_id = normalize_text(appointment_id)
        if appointment_id is not None and "id" not in appointment:
            appointment = dict(appointment)
            appointment["id"] = appointment_id
    message = cleaned.get("message") if isinstance(cleaned.get("message"), str) and cleaned.get("message").strip() else "Appointment confirmed."

    normalized = {
        "ok": coerce_bool(cleaned.get("ok"), default=True),
        "confirmed": coerce_bool(cleaned.get("confirmed"), default=True),
        "appointment": appointment,
        "message": message,
        "raw_summary": cleaned.get("raw_summary") if isinstance(cleaned.get("raw_summary"), dict) else {},
    }
    if "error_code" in cleaned:
        normalized["error_code"] = cleaned["error_code"]
    return normalized


async def appointment_confirm(
    tenant_id: str,
    start_at: str,
    end_at: str,
    timezone: str,
    contact: AppointmentConfirmContactInput,
    service_id: str = "",
    service_ref: str = "",
    owner_id: str = "",
    owner_ref: str = "",
    title: str | None = None,
    notes: str | None = None,
    conversation_id: str | None = None,
    entrypoint_ref: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Confirm an appointment through n8n for a tenant, contact and selected slot.

    Prefer `service_id` with the canonical UUID returned by `services_search`.
    Use `service_ref` only as a fallback with slug, integration key or external reference.
    Do not invent UUIDs or technical IDs: `service_id`, `service_ref`, `owner_id` and `owner_ref`
    must come from upstream tools or existing context.
    The slot must be complete: `tenant_id`, `start_at`, `end_at`, `timezone`, one service
    identifier, one owner identifier, and `contact.phone` or `contact.email`.
    Do not fall back silently to a default timezone.
    """
    try:
        payload = AppointmentConfirmInput(
            tenant_id=tenant_id,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            service_id=service_id,
            service_ref=service_ref,
            owner_id=owner_id,
            owner_ref=owner_ref,
            contact=contact,
            title=title,
            notes=notes,
            conversation_id=conversation_id,
            entrypoint_ref=entrypoint_ref,
        )
    except ValidationError:
        return _empty_payload("Request payload is invalid.", "validation_error")

    settings = get_settings()
    webhook_url = normalize_text(settings.appointment_confirm_webhook_url)
    webhook_token = normalize_text(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.appointment_confirm_timeout_seconds
    downstream_authorization = extract_request_authorization(ctx)

    normalized_tenant_id = normalize_text(payload.tenant_id)
    normalized_start_at = normalize_text(payload.start_at)
    normalized_end_at = normalize_text(payload.end_at)
    normalized_timezone = normalize_text(payload.timezone)
    normalized_service_id = normalize_text(payload.service_id)
    normalized_service_ref = normalize_text(payload.service_ref)
    normalized_owner_id = normalize_text(payload.owner_id)
    normalized_owner_ref = normalize_text(payload.owner_ref)
    normalized_contact = _normalize_contact(payload.contact)
    normalized_title = normalize_text(payload.title)
    normalized_notes = normalize_text(payload.notes)
    normalized_conversation_id = normalize_text(payload.conversation_id)
    normalized_entrypoint_ref = normalize_text(payload.entrypoint_ref)

    if webhook_url is None:
        return _empty_payload("Appointment confirm service is not configured.", "not_configured")

    missing_fields: list[str] = []
    if normalized_tenant_id is None:
        missing_fields.append("tenant_id")
    if normalized_start_at is None:
        missing_fields.append("start_at")
    if normalized_timezone is None:
        missing_fields.append("timezone")
    if normalized_end_at is None:
        missing_fields.append("end_at")
    if normalized_service_id is None and normalized_service_ref is None:
        missing_fields.append("service_id/service_ref")
    if normalized_owner_id is None and normalized_owner_ref is None:
        missing_fields.append("owner_id/owner_ref")
    if not isinstance(normalized_contact, dict) or (
        normalize_text(normalized_contact.get("phone")) is None and normalize_text(normalized_contact.get("email")) is None
    ):
        missing_fields.append("contact.phone or contact.email")

    if missing_fields:
        return _empty_payload(
            "Missing required fields to confirm an appointment: " + ", ".join(missing_fields) + ".",
            "validation_error",
        )

    body = {
        "tool": "appointment_confirm",
        "tenant_id": normalized_tenant_id,
        "slot": _build_slot(normalized_start_at, normalized_end_at, normalized_owner_id, normalized_owner_ref),
        "timezone": normalized_timezone,
        "service_id": normalized_service_id,
        "service_ref": normalized_service_ref,
        "owner_id": normalized_owner_id,
        "owner_ref": normalized_owner_ref,
        "contact": normalized_contact,
        "title": normalized_title,
        "notes": normalized_notes,
        "conversation_id": normalized_conversation_id,
        "entrypoint_ref": normalized_entrypoint_ref,
        "source": "mcp-gateway",
    }

    try:
        upstream_payload = await post_webhook(
            webhook_url,
            webhook_token,
            timeout_seconds,
            body,
            downstream_authorization=downstream_authorization,
            tool_name="appointment_confirm",
        )
    except httpx.TimeoutException:
        return _empty_payload("Appointment confirm request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_payload("Appointment confirm service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_payload("Appointment confirm service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while confirming appointment")
        return _empty_payload("Appointment confirm service is unavailable.", "upstream_error")

    return _normalize_success_payload(upstream_payload)
