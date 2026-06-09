from __future__ import annotations

import logging
from typing import Any

import httpx
from mcp.server.fastmcp import Context
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from app.settings import get_settings
from app.tools._appointment_common import coerce_bool, extract_request_authorization, normalize_text, normalize_value, post_webhook

logger = logging.getLogger(__name__)


class CrmContactSubmitContactInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    phone: str | None = None
    email: str | None = None
    whatsapp_name: str | None = Field(default=None, validation_alias=AliasChoices("whatsapp_name", "whatsappName"))


class CrmContactSubmitQualificationInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    is_qualified: bool | None = Field(default=None, validation_alias=AliasChoices("is_qualified", "isQualified"))
    service_interest: str | None = Field(default=None, validation_alias=AliasChoices("service_interest", "serviceInterest"))
    need: str | None = None
    urgency: str | None = None
    preferred_date: str | None = Field(default=None, validation_alias=AliasChoices("preferred_date", "preferredDate"))
    preferred_time: str | None = Field(default=None, validation_alias=AliasChoices("preferred_time", "preferredTime"))


class CrmContactSubmitConversationInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    summary: str | None = None
    last_message: str | None = Field(default=None, validation_alias=AliasChoices("last_message", "lastMessage"))
    intent: str | None = None
    needs_human: bool | None = Field(default=None, validation_alias=AliasChoices("needs_human", "needsHuman"))
    finished: bool | None = None


class CrmContactSubmitActionsInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    booking_requested: bool | None = Field(default=None, validation_alias=AliasChoices("booking_requested", "bookingRequested"))
    handoff_requested: bool | None = Field(default=None, validation_alias=AliasChoices("handoff_requested", "handoffRequested"))
    waitlist_requested: bool | None = Field(default=None, validation_alias=AliasChoices("waitlist_requested", "waitlistRequested"))


class CrmContactSubmitMetadataInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    origin: str | None = None
    sa_conversation_id: str | None = Field(default=None, validation_alias=AliasChoices("sa_conversation_id", "saConversationId"))
    service_slug: str | None = Field(default=None, validation_alias=AliasChoices("service_slug", "serviceSlug"))
    service_integration_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("service_integration_key", "serviceIntegrationKey"),
    )
    product_id: str | None = Field(default=None, validation_alias=AliasChoices("product_id", "productId"))
    utm_source: str | None = Field(default=None, validation_alias=AliasChoices("utm_source", "utmSource"))
    utm_medium: str | None = Field(default=None, validation_alias=AliasChoices("utm_medium", "utmMedium"))
    utm_campaign: str | None = Field(default=None, validation_alias=AliasChoices("utm_campaign", "utmCampaign"))
    utm_content: str | None = Field(default=None, validation_alias=AliasChoices("utm_content", "utmContent"))
    utm_term: str | None = Field(default=None, validation_alias=AliasChoices("utm_term", "utmTerm"))


class CrmContactSubmitInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contact: CrmContactSubmitContactInput | dict[str, Any] | None = None
    source: str | None = None
    channel: str | None = None
    external_conversation_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("external_conversation_id", "externalConversationId"),
    )
    entry_point_ref: str | None = Field(default=None, validation_alias=AliasChoices("entry_point_ref", "entryPointRef"))
    qualification: CrmContactSubmitQualificationInput | dict[str, Any] | None = None
    conversation: CrmContactSubmitConversationInput | dict[str, Any] | None = None
    actions: CrmContactSubmitActionsInput | dict[str, Any] | None = None
    metadata: CrmContactSubmitMetadataInput | dict[str, Any] | None = None


def _normalize_text_value(value: str | None) -> str | None:
    return normalize_text(value)


def _normalize_value_tree(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    return normalize_value(value)


def _to_camel_case_key(key: str) -> str:
    if "_" not in key:
        return key

    parts = key.split("_")
    first = parts[0]
    tail = "".join(part[:1].upper() + part[1:] for part in parts[1:] if part)
    return f"{first}{tail}"


def _camelize_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {_to_camel_case_key(key): _camelize_keys(inner_value) for key, inner_value in value.items()}
    if isinstance(value, list):
        return [_camelize_keys(item) for item in value]
    return value


def _empty_payload(message: str, status: str, error: str | None = None) -> dict[str, Any]:
    payload = {
        "ok": False,
        "submitted": False,
        "status": status,
        "message": message,
        "crm_result": None,
    }
    if error is not None:
        payload["error"] = error
    return payload


def _resolve_service_token(settings: Any) -> tuple[str | None, str]:
    override_token = _normalize_text_value(settings.crm_contact_submit_webhook_token)
    if override_token is not None:
        return override_token, "crm_contact_submit_webhook_token"

    generic_token = _normalize_text_value(settings.n8n_webhook_bearer_token)
    if generic_token is not None:
        return generic_token, "n8n_webhook_bearer_token"

    return None, "missing"


def _normalize_contact(contact: Any) -> dict[str, Any] | None:
    normalized = _normalize_value_tree(contact)
    if not isinstance(normalized, dict):
        return None

    contact_payload = {
        "name": _normalize_text_value(normalized.get("name")),
        "phone": _normalize_text_value(normalized.get("phone")),
        "email": _normalize_text_value(normalized.get("email")),
        "whatsapp_name": _normalize_text_value(
            normalized.get("whatsapp_name") or normalized.get("whatsappName")
        ),
    }

    if all(value is None for value in contact_payload.values()):
        return None

    return contact_payload


def _normalize_optional_section(section: Any) -> dict[str, Any] | None:
    normalized = _normalize_value_tree(section)
    if not isinstance(normalized, dict):
        return None

    if all(value is None for value in normalized.values()):
        return None

    return normalized


def _normalize_upstream_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload("CRM contact submit service returned an invalid response.", "upstream_error", "invalid_response")

    cleaned = normalize_value(payload)
    crm_result = cleaned.get("crm_result")
    if not isinstance(crm_result, dict):
        if isinstance(cleaned.get("result"), dict):
            crm_result = cleaned["result"]
        elif isinstance(cleaned.get("data"), dict):
            crm_result = cleaned["data"]
        else:
            wrapper_keys = {"ok", "submitted", "status", "message", "error", "crm_result", "result", "data"}
            crm_result = {key: value for key, value in cleaned.items() if key not in wrapper_keys}

    ok = coerce_bool(cleaned.get("ok"), default=True)
    submitted = coerce_bool(cleaned.get("submitted"), default=ok)
    status = cleaned.get("status")
    if not isinstance(status, str) or status.strip() == "":
        status = "accepted" if ok and submitted else "failed"
    else:
        status = status.strip().lower()

    message = cleaned.get("message")
    if not isinstance(message, str) or message.strip() == "":
        message = "CRM contact context submitted." if ok and submitted else "CRM contact submit failed."

    error = cleaned.get("error")
    if not isinstance(error, str) or error.strip() == "":
        error = None

    normalized = {
        "ok": ok,
        "submitted": submitted,
        "status": status,
        "message": message,
        "crm_result": crm_result if isinstance(crm_result, dict) else None,
    }
    if error is not None:
        normalized["error"] = error
    return normalized


async def crm_contact_submit(
    contact: CrmContactSubmitContactInput | dict[str, Any] | None = None,
    source: str | None = None,
    channel: str | None = None,
    external_conversation_id: str | None = None,
    entry_point_ref: str | None = None,
    qualification: CrmContactSubmitQualificationInput | dict[str, Any] | None = None,
    conversation: CrmContactSubmitConversationInput | dict[str, Any] | None = None,
    actions: CrmContactSubmitActionsInput | dict[str, Any] | None = None,
    metadata: CrmContactSubmitMetadataInput | dict[str, Any] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Submit commercial context for a contact/conversation to CRM through n8n."""
    try:
        payload = CrmContactSubmitInput(
            contact=contact,
            source=source,
            channel=channel,
            external_conversation_id=external_conversation_id,
            entry_point_ref=entry_point_ref,
            qualification=qualification,
            conversation=conversation,
            actions=actions,
            metadata=metadata,
        )
    except ValidationError:
        return _empty_payload("Request payload is invalid.", "validation_error", "validation_error")

    settings = get_settings()
    webhook_url = _normalize_text_value(settings.crm_contact_submit_webhook_url)
    webhook_token, webhook_token_source = _resolve_service_token(settings)
    timeout_seconds = settings.crm_contact_submit_timeout_seconds
    downstream_authorization = extract_request_authorization(ctx)

    logger.info(
        "crm_contact_submit start webhook_configured=%s service_auth_configured=%s service_auth_source=%s downstream_authorization_present=%s",
        webhook_url is not None,
        webhook_token is not None,
        webhook_token_source,
        downstream_authorization is not None,
    )

    if webhook_url is None:
        return _empty_payload("CRM contact submit webhook is not configured.", "not_configured")

    normalized_contact = _normalize_contact(payload.contact)
    if normalized_contact is None:
        return _empty_payload("contact is required to submit CRM context.", "validation_error", "validation_error")

    normalized_phone = normalized_contact.get("phone")
    normalized_email = normalized_contact.get("email")
    if normalized_phone is None and normalized_email is None:
        return _empty_payload(
            "contact.phone or contact.email is required to submit CRM context.",
            "validation_error",
            "validation_error",
        )

    normalized_source = _normalize_text_value(payload.source)
    normalized_channel = _normalize_text_value(payload.channel)
    normalized_external_conversation_id = _normalize_text_value(payload.external_conversation_id)
    normalized_entry_point_ref = _normalize_text_value(payload.entry_point_ref)
    normalized_qualification = _normalize_optional_section(payload.qualification)
    normalized_conversation = _normalize_optional_section(payload.conversation)
    normalized_actions = _normalize_optional_section(payload.actions)
    normalized_metadata = _normalize_optional_section(payload.metadata) or {}

    crm_payload = _camelize_keys(
        {
            "source": normalized_source,
            "channel": normalized_channel,
            "external_conversation_id": normalized_external_conversation_id,
            "entry_point_ref": normalized_entry_point_ref,
            "contact": normalized_contact,
            "qualification": normalized_qualification,
            "conversation": normalized_conversation,
            "actions": normalized_actions,
            "metadata": normalized_metadata,
        }
    )

    body = {
        "event": "sales_agent.crm_contact_submit",
        "tool": "crm_contact_submit",
        "source": "mcp-gateway",
        "channel": normalized_channel,
        "contact": normalized_contact,
        "crm_payload": crm_payload,
    }

    try:
        upstream_payload = await post_webhook(
            webhook_url,
            webhook_token,
            timeout_seconds,
            body,
            downstream_authorization=downstream_authorization,
            tool_name="crm_contact_submit",
        )
        logger.info(
            "crm_contact_submit upstream success status_code=%s downstream_authorization_present=%s",
            200,
            downstream_authorization is not None,
        )
    except httpx.TimeoutException:
        logger.warning("crm_contact_submit upstream timeout")
        return _empty_payload("CRM contact submit request timed out.", "timeout", "timeout")
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        logger.warning(
            "crm_contact_submit upstream http error status_code=%s error=%s",
            status_code if status_code is not None else "-",
            exc.__class__.__name__,
        )
        return _empty_payload("CRM contact submit service returned an error.", "failed", "upstream_http_error")
    except httpx.RequestError as exc:
        logger.warning(
            "crm_contact_submit upstream request error error=%s",
            exc.__class__.__name__,
        )
        return _empty_payload("CRM contact submit service is unavailable.", "upstream_error", "upstream_error")
    except Exception:
        logger.exception("crm_contact_submit unexpected error")
        return _empty_payload("CRM contact submit service failed unexpectedly.", "upstream_error", "unexpected_error")

    normalized_upstream = _normalize_upstream_response(upstream_payload)
    if normalized_upstream["ok"] and normalized_upstream["submitted"]:
        normalized_upstream["status"] = "accepted"
    elif normalized_upstream["status"] == "accepted":
        normalized_upstream["status"] = "failed"

    return normalized_upstream
