from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import Context
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from app.settings import get_settings
from app.tools._appointment_common import coerce_bool, extract_request_authorization, normalize_text, normalize_value, post_webhook

logger = logging.getLogger(__name__)


class HandoffRequestContactInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    email: str | None = None
    name: str | None = None
    external_id: str | None = None


class HandoffRequestConversationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    external_conversation_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("external_conversation_id", "external_id"),
    )
    channel: str | None = None
    status: str | None = None
    summary: str | None = None
    last_messages: list[str] | None = None


class HandoffRequestInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str | None = None
    contact: HandoffRequestContactInput | None = None
    conversation: HandoffRequestConversationInput | None = None
    reason: str | None = None
    priority: str | None = "normal"
    message: str | None = None
    metadata: dict[str, Any] | None = None


def _normalize_text_value(value: str | None) -> str | None:
    return normalize_text(value)


def _normalize_contact(contact: Any) -> dict[str, Any] | None:
    normalized = contact.model_dump() if isinstance(contact, HandoffRequestContactInput) else contact
    if not isinstance(normalized, dict):
        return None

    contact_payload = {
        "phone": _normalize_text_value(normalized.get("phone")),
        "email": _normalize_text_value(normalized.get("email")),
        "name": _normalize_text_value(normalized.get("name")),
        "external_id": _normalize_text_value(normalized.get("external_id")),
    }

    if all(value is None for value in contact_payload.values()):
        return None

    return contact_payload


def _normalize_messages(value: Any) -> list[str]:
    if isinstance(value, HandoffRequestConversationInput):
        value = value.last_messages

    if not isinstance(value, list):
        return []

    messages: list[str] = []
    for item in value[-8:]:
        if not isinstance(item, str):
            continue

        normalized = normalize_text(item)
        if normalized is not None:
            messages.append(normalized)

    return messages


def _normalize_conversation(conversation: Any) -> dict[str, Any] | None:
    normalized = conversation.model_dump() if isinstance(conversation, HandoffRequestConversationInput) else conversation
    if not isinstance(normalized, dict):
        return None

    conversation_payload = {
        "id": _normalize_text_value(normalized.get("id")),
        "external_conversation_id": _normalize_text_value(
            normalized.get("external_conversation_id") or normalized.get("external_id")
        ),
        "channel": _normalize_text_value(normalized.get("channel")),
        "status": _normalize_text_value(normalized.get("status")),
        "summary": _normalize_text_value(normalized.get("summary")),
        "last_messages": _normalize_messages(normalized.get("last_messages")),
    }

    if all(
        value is None or value == []
        for value in conversation_payload.values()
    ):
        return None

    return conversation_payload


def _normalize_priority(value: Any) -> str:
    if not isinstance(value, str):
        return "normal"

    normalized = value.strip().lower()
    if normalized in {"low", "normal", "high", "urgent"}:
        return normalized

    return "normal"


def _empty_payload(message: str, status: str) -> dict[str, Any]:
    return {
        "ok": False,
        "handoff_requested": False,
        "status": status,
        "message": message,
        "external_reference": None,
    }


def _normalize_success_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload("Invalid response from handoff request service.", "upstream_error")

    cleaned = normalize_value(payload)
    if isinstance(cleaned.get("result"), dict):
        cleaned = cleaned["result"]
    elif isinstance(cleaned.get("data"), dict):
        cleaned = cleaned["data"]

    ok = coerce_bool(cleaned.get("ok"), default=True)
    handoff_requested = coerce_bool(cleaned.get("handoff_requested"), default=ok)
    status = cleaned.get("status")
    if not isinstance(status, str) or status.strip() == "":
        status = "accepted" if ok and handoff_requested else "failed"
    elif status.strip().lower() == "requested":
        status = "accepted"
    else:
        status = status.strip().lower()

    message = cleaned.get("message")
    if not isinstance(message, str) or message.strip() == "":
        message = "Handoff registrado." if ok and handoff_requested else "Handoff no registrado."

    external_reference = cleaned.get("external_reference")
    if not isinstance(external_reference, str) or external_reference.strip() == "":
        external_reference = None

    return {
        "ok": ok,
        "handoff_requested": handoff_requested,
        "status": status,
        "message": message,
        "external_reference": external_reference,
    }


async def handoff_request(
    tenant_id: str | None = None,
    contact: HandoffRequestContactInput | dict[str, Any] | None = None,
    conversation: HandoffRequestConversationInput | dict[str, Any] | None = None,
    reason: str | None = None,
    priority: str | None = "normal",
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Register a human handoff request through n8n."""
    try:
        payload = HandoffRequestInput(
            tenant_id=tenant_id,
            contact=contact,
            conversation=conversation,
            reason=reason,
            priority=priority,
            message=message,
            metadata=metadata,
        )
    except ValidationError:
        return _empty_payload("Request payload is invalid.", "validation_error")

    settings = get_settings()
    webhook_url = _normalize_text_value(settings.handoff_request_webhook_url)
    webhook_token = _normalize_text_value(settings.handoff_request_webhook_token) or _normalize_text_value(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.handoff_request_timeout_seconds
    downstream_authorization = extract_request_authorization(ctx)

    normalized_tenant_id = _normalize_text_value(payload.tenant_id)
    if webhook_url is None:
        return _empty_payload("Handoff request service is not configured.", "not_configured")
    if normalized_tenant_id is None:
        return _empty_payload("tenant_id is required to create a handoff request.", "validation_error")
    normalized_reason = _normalize_text_value(payload.reason)
    if normalized_reason is None:
        return _empty_payload("reason is required to create a handoff request.", "validation_error")

    normalized_contact = _normalize_contact(payload.contact)
    normalized_conversation = _normalize_conversation(payload.conversation)
    normalized_message = _normalize_text_value(payload.message)
    normalized_priority = _normalize_priority(payload.priority)
    normalized_metadata = normalize_value(payload.metadata) if isinstance(payload.metadata, dict) else {}

    body = {
        "event": "sales_agent.handoff_requested",
        "tenant_id": normalized_tenant_id,
        "contact": normalized_contact,
        "conversation": normalized_conversation,
        "reason": normalized_reason,
        "priority": normalized_priority,
        "message": normalized_message,
        "metadata": {
            **normalized_metadata,
            "source": "mcp-gateway",
            "tool": "handoff_request",
        },
    }

    try:
        upstream_payload = await post_webhook(
            webhook_url,
            webhook_token,
            timeout_seconds,
            body,
            downstream_authorization=downstream_authorization,
            tool_name="handoff_request",
        )
    except httpx.TimeoutException:
        return _empty_payload("Handoff request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_payload("Handoff request service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_payload("Handoff request service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while creating handoff request")
        return _empty_payload("Handoff request service is unavailable.", "upstream_error")

    return _normalize_success_payload(upstream_payload)
