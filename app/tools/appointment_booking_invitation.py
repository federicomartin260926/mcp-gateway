from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.settings import get_settings
from app.tools._appointment_common import coerce_bool, coerce_int, normalize_text, normalize_value, post_webhook

logger = logging.getLogger(__name__)


class AppointmentBookingInvitationContactInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    email: str | None = None
    name: str | None = None


class AppointmentBookingInvitationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str | None = None
    contact: AppointmentBookingInvitationContactInput | None = None
    timezone: str | None = "Europe/Madrid"
    service_ref: str | None = None
    owner_ref: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    duration_minutes: int | None = 30
    notes: str | None = None
    conversation_id: str | None = None
    entrypoint_ref: str | None = None


def _empty_payload(message: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "created": False,
        "booking_url": None,
        "invitation": {},
        "message": message,
        "raw_summary": {},
        "error_code": error_code,
    }


def _normalize_contact(contact: Any) -> dict[str, Any] | None:
    if contact is None:
        return None

    normalized = contact.model_dump() if isinstance(contact, AppointmentBookingInvitationContactInput) else contact
    if not isinstance(normalized, dict):
        return None

    return {key: normalize_text(value) for key, value in normalized.items()}


def _normalize_success_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload("Invalid response from appointment booking invitation service.", "upstream_error")

    cleaned = normalize_value(payload)
    if isinstance(cleaned.get("result"), dict):
        cleaned = cleaned["result"]
    elif isinstance(cleaned.get("data"), dict):
        cleaned = cleaned["data"]

    invitation = cleaned.get("invitation") if isinstance(cleaned.get("invitation"), dict) else {}
    booking_url = cleaned.get("booking_url")
    if not isinstance(booking_url, str) or booking_url.strip() == "":
        booking_url = cleaned.get("url") if isinstance(cleaned.get("url"), str) else None
    if isinstance(booking_url, str):
        booking_url = normalize_text(booking_url)

    message = cleaned.get("message") if isinstance(cleaned.get("message"), str) and cleaned.get("message").strip() else "Booking invitation created."

    normalized = {
        "ok": coerce_bool(cleaned.get("ok"), default=True),
        "created": coerce_bool(cleaned.get("created"), default=True),
        "booking_url": booking_url,
        "invitation": invitation,
        "message": message,
        "raw_summary": cleaned.get("raw_summary") if isinstance(cleaned.get("raw_summary"), dict) else {},
    }
    if "error_code" in cleaned:
        normalized["error_code"] = cleaned["error_code"]
    return normalized


async def appointment_booking_invitation(
    tenant_id: str | None = None,
    contact: AppointmentBookingInvitationContactInput | dict[str, Any] | None = None,
    timezone: str | None = "Europe/Madrid",
    service_ref: str | None = None,
    owner_ref: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    duration_minutes: int | None = 30,
    notes: str | None = None,
    conversation_id: str | None = None,
    entrypoint_ref: str | None = None,
) -> dict[str, Any]:
    try:
        payload = AppointmentBookingInvitationInput(
            tenant_id=tenant_id,
            contact=contact,
            timezone=timezone,
            service_ref=service_ref,
            owner_ref=owner_ref,
            date_from=date_from,
            date_to=date_to,
            duration_minutes=duration_minutes,
            notes=notes,
            conversation_id=conversation_id,
            entrypoint_ref=entrypoint_ref,
        )
    except ValidationError:
        return _empty_payload("Request payload is invalid.", "validation_error")

    settings = get_settings()
    webhook_url = normalize_text(settings.appointment_booking_invitation_webhook_url)
    webhook_token = normalize_text(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.appointment_booking_invitation_timeout_seconds

    normalized_tenant_id = normalize_text(payload.tenant_id)
    normalized_timezone = normalize_text(payload.timezone) or "Europe/Madrid"
    normalized_service_ref = normalize_text(payload.service_ref)
    normalized_owner_ref = normalize_text(payload.owner_ref)
    normalized_date_from = normalize_text(payload.date_from)
    normalized_date_to = normalize_text(payload.date_to)
    normalized_duration_minutes = coerce_int(payload.duration_minutes, 30, 5, 480)
    normalized_notes = normalize_text(payload.notes)
    normalized_conversation_id = normalize_text(payload.conversation_id)
    normalized_entrypoint_ref = normalize_text(payload.entrypoint_ref)
    normalized_contact = _normalize_contact(payload.contact)

    if webhook_url is None:
        return _empty_payload("Appointment booking invitation service is not configured.", "not_configured")

    if normalized_tenant_id is None:
        return _empty_payload("tenant_id is required to create a booking invitation.", "validation_error")
    if not isinstance(normalized_contact, dict) or (normalize_text(normalized_contact.get("phone")) is None and normalize_text(normalized_contact.get("email")) is None):
        return _empty_payload("contact.phone or contact.email is required to create a booking invitation.", "validation_error")

    body = {
        "tool": "appointment_booking_invitation",
        "tenant_id": normalized_tenant_id,
        "contact": normalized_contact,
        "timezone": normalized_timezone,
        "service_ref": normalized_service_ref,
        "owner_ref": normalized_owner_ref,
        "date_from": normalized_date_from,
        "date_to": normalized_date_to,
        "duration_minutes": normalized_duration_minutes,
        "notes": normalized_notes,
        "conversation_id": normalized_conversation_id,
        "entrypoint_ref": normalized_entrypoint_ref,
        "source": "mcp-gateway",
    }

    try:
        upstream_payload = await post_webhook(webhook_url, webhook_token, timeout_seconds, body)
    except httpx.TimeoutException:
        return _empty_payload("Appointment booking invitation request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_payload("Appointment booking invitation service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_payload("Appointment booking invitation service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while creating booking invitation")
        return _empty_payload("Appointment booking invitation service is unavailable.", "upstream_error")

    return _normalize_success_payload(upstream_payload)
