from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict, ValidationError

from app.settings import get_settings
from app.tools._appointment_common import coerce_bool, extract_request_authorization, normalize_text, normalize_value, post_webhook

logger = logging.getLogger(__name__)


class AppointmentCancelContactInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    email: str | None = None
    name: str | None = None


class AppointmentCancelInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str | None = None
    appointment_id: str | None = None
    contact: AppointmentCancelContactInput | None = None
    reason: str | None = None
    cancelled_by: str | None = "sales-agent"
    conversation_id: str | None = None
    entrypoint_ref: str | None = None


def _empty_payload(message: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "cancelled": False,
        "appointment": {},
        "message": message,
        "raw_summary": {},
        "error_code": error_code,
    }


def _normalize_contact(contact: Any) -> dict[str, Any] | None:
    if contact is None:
        return None

    normalized = contact.model_dump() if isinstance(contact, AppointmentCancelContactInput) else contact
    if not isinstance(normalized, dict):
        return None

    return {key: normalize_text(value) for key, value in normalized.items()}


def _normalize_success_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload("Invalid response from appointment cancel service.", "upstream_error")

    cleaned = normalize_value(payload)
    if isinstance(cleaned.get("result"), dict):
        cleaned = cleaned["result"]
    elif isinstance(cleaned.get("data"), dict):
        cleaned = cleaned["data"]

    appointment = cleaned.get("appointment") if isinstance(cleaned.get("appointment"), dict) else {}
    message = cleaned.get("message") if isinstance(cleaned.get("message"), str) and cleaned.get("message").strip() else "Appointment cancelled."

    normalized = {
        "ok": coerce_bool(cleaned.get("ok"), default=True),
        "cancelled": coerce_bool(cleaned.get("cancelled"), default=True),
        "appointment": appointment,
        "message": message,
        "raw_summary": cleaned.get("raw_summary") if isinstance(cleaned.get("raw_summary"), dict) else {},
    }
    if "error_code" in cleaned:
        normalized["error_code"] = cleaned["error_code"]
    return normalized


async def appointment_cancel(
    tenant_id: str | None = None,
    appointment_id: str | None = None,
    contact: AppointmentCancelContactInput | dict[str, Any] | None = None,
    reason: str | None = None,
    cancelled_by: str | None = "sales-agent",
    conversation_id: str | None = None,
    entrypoint_ref: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    try:
        payload = AppointmentCancelInput(
            tenant_id=tenant_id,
            appointment_id=appointment_id,
            contact=contact,
            reason=reason,
            cancelled_by=cancelled_by,
            conversation_id=conversation_id,
            entrypoint_ref=entrypoint_ref,
        )
    except ValidationError:
        return _empty_payload("Request payload is invalid.", "validation_error")

    settings = get_settings()
    webhook_url = normalize_text(settings.appointment_cancel_webhook_url)
    webhook_token = normalize_text(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.appointment_cancel_timeout_seconds
    downstream_authorization = extract_request_authorization(ctx)

    normalized_tenant_id = normalize_text(payload.tenant_id)
    normalized_appointment_id = normalize_text(payload.appointment_id)
    normalized_contact = _normalize_contact(payload.contact)
    normalized_reason = normalize_text(payload.reason)
    normalized_cancelled_by = normalize_text(payload.cancelled_by) or "sales-agent"
    normalized_conversation_id = normalize_text(payload.conversation_id)
    normalized_entrypoint_ref = normalize_text(payload.entrypoint_ref)

    if webhook_url is None:
        return _empty_payload("Appointment cancel service is not configured.", "not_configured")

    if normalized_tenant_id is None:
        return _empty_payload("tenant_id is required to cancel an appointment.", "validation_error")
    if normalized_appointment_id is None:
        return _empty_payload("appointment_id is required to cancel an appointment.", "validation_error")

    body = {
        "tool": "appointment_cancel",
        "tenant_id": normalized_tenant_id,
        "appointment_id": normalized_appointment_id,
        "contact": normalized_contact,
        "reason": normalized_reason,
        "cancelled_by": normalized_cancelled_by,
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
            tool_name="appointment_cancel",
        )
    except httpx.TimeoutException:
        return _empty_payload("Appointment cancel request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_payload("Appointment cancel service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_payload("Appointment cancel service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while cancelling appointment")
        return _empty_payload("Appointment cancel service is unavailable.", "upstream_error")

    return _normalize_success_payload(upstream_payload)
