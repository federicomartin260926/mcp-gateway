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


def _first_non_null(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


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


class ContactContextInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    email: str | None = None
    name: str | None = None
    tenant_id: str | None = None
    channel: str | None = None


def _empty_contact_payload(summary: str, error_code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": error_code,
        "found": False,
        "contact": {"found": False},
        "appointments": {
            "next": None,
            "items": [],
        },
        "open_opportunities": [],
        "sales": {},
        "flags": {
            "needs_human": False,
            "do_not_contact": False,
        },
        "message": summary,
        "summary": summary,
        "error_code": error_code,
    }


def _optional_normalized_value(value: Any) -> Any:
    if value is None:
        return None

    return _normalize_value(value)


def _coerce_branches(payload: dict[str, Any]) -> list[Any]:
    branches = payload.get("branches")
    if not isinstance(branches, list):
        return []

    normalized_branches = _normalize_value(branches)
    return normalized_branches if isinstance(normalized_branches, list) else []


def _coerce_contact(payload: dict[str, Any]) -> dict[str, Any]:
    contact = payload.get("contact")
    if contact is None:
        return {"found": False}
    if not isinstance(contact, dict):
        contact = {}

    legacy_contact = payload.get("lead")
    if not isinstance(legacy_contact, dict):
        legacy_contact = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}

    merged_contact = _normalize_value(contact)
    if not isinstance(merged_contact, dict):
        merged_contact = {}

    if merged_contact.get("name") is None:
        merged_contact["name"] = _first_non_null(contact.get("name"), legacy_contact.get("name"))

    if merged_contact.get("type") is None:
        if isinstance(payload.get("customer"), dict) or payload.get("customer") is True:
            merged_contact["type"] = "customer"
        elif isinstance(payload.get("lead"), dict) or payload.get("lead") is True:
            merged_contact["type"] = "lead"
        else:
            merged_contact["type"] = "unknown"
    if merged_contact.get("status") is None:
        merged_contact["status"] = _first_non_null(contact.get("status"), legacy_contact.get("status"))
    if merged_contact.get("stage") is None:
        merged_contact["stage"] = _first_non_null(contact.get("stage"), legacy_contact.get("stage"))
    if merged_contact.get("owner") is None:
        merged_contact["owner"] = _first_non_null(contact.get("owner"), legacy_contact.get("owner"))
    if merged_contact.get("last_interaction") is None:
        merged_contact["last_interaction"] = _first_non_null(contact.get("last_interaction"), legacy_contact.get("last_interaction"))

    contact_id = _first_non_null(
        merged_contact.get("id"),
        merged_contact.get("contact_id"),
        merged_contact.get("contactId"),
        contact.get("id"),
        contact.get("contact_id"),
        contact.get("contactId"),
        legacy_contact.get("id"),
        legacy_contact.get("contact_id"),
        legacy_contact.get("contactId"),
    )
    if contact_id is not None:
        merged_contact["id"] = contact_id

    last_branch = _first_non_null(
        merged_contact.get("last_branch"),
        merged_contact.get("lastBranch"),
        contact.get("last_branch"),
        contact.get("lastBranch"),
        legacy_contact.get("last_branch"),
        legacy_contact.get("lastBranch"),
    )
    if last_branch is not None:
        merged_contact["last_branch"] = last_branch

    merged_contact["found"] = True

    return merged_contact


def _coerce_appointments(payload: dict[str, Any]) -> dict[str, Any]:
    appointments = payload.get("appointments")
    if isinstance(appointments, dict):
        next_appointment = appointments.get("next")
        items = appointments.get("items") if isinstance(appointments.get("items"), list) else []
        return {"next": next_appointment, "items": items}

    next_appointment = payload.get("next_appointment")
    items = payload.get("appointments_list")
    if not isinstance(items, list):
        items = []

    if next_appointment is not None and not items:
        items = [next_appointment]

    return {"next": next_appointment, "items": items}


def _coerce_flags(payload: dict[str, Any]) -> dict[str, Any]:
    flags = payload.get("flags")
    if not isinstance(flags, dict):
        flags = {}

    return {
        "needs_human": _coerce_bool(flags.get("needs_human", payload.get("needs_human")), default=False),
        "do_not_contact": _coerce_bool(flags.get("do_not_contact", payload.get("do_not_contact")), default=False),
    }


def _build_business_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    timezone = payload.get("timezone")
    timezone_source = payload.get("timezone_source")
    branch = _optional_normalized_value(payload.get("branch"))
    branches = _coerce_branches(payload)
    needs_branch_selection = _coerce_bool(payload.get("needs_branch_selection"), default=False)

    if (
        timezone is None
        and timezone_source is None
        and branch is None
        and not branches
        and not needs_branch_selection
    ):
        return None

    return {
        "timezone": timezone,
        "timezone_source": timezone_source,
        "branch": branch,
        "branches": branches,
        "needs_branch_selection": needs_branch_selection,
    }


def _normalize_success_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_contact_payload("Invalid response from contact context service.", "upstream_error")

    cleaned = _normalize_value(payload)
    contact = _coerce_contact(cleaned)
    found = bool(contact.get("found"))
    ok = _coerce_bool(cleaned.get("ok"), default=True)
    status = cleaned.get("status")
    summary = cleaned.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        contact_name = contact.get("name") or "Unknown contact"
        status = contact.get("status")
        if status:
            summary = f"Contact {contact_name} is in status {status}."
        else:
            summary = f"Contact context found for {contact_name}."

    normalized = {
        "ok": ok,
        "status": status if isinstance(status, str) and status.strip() else ("ok" if ok else "upstream_error"),
        "found": found,
        "tenant": _optional_normalized_value(cleaned.get("tenant")),
        "contact": contact,
        "timezone": cleaned.get("timezone"),
        "timezone_source": cleaned.get("timezone_source"),
        "branch": _optional_normalized_value(cleaned.get("branch")),
        "branches": _coerce_branches(cleaned),
        "needs_branch_selection": _coerce_bool(cleaned.get("needs_branch_selection"), default=False),
        "appointments": _coerce_appointments(cleaned),
        "open_opportunities": cleaned.get("open_opportunities") if isinstance(cleaned.get("open_opportunities"), list) else [],
        "sales": cleaned.get("sales") if isinstance(cleaned.get("sales"), dict) else {},
        "flags": _coerce_flags(cleaned),
        "summary": summary,
    }
    business_context = _build_business_context(cleaned)
    if business_context is not None:
        normalized["business_context"] = business_context
    if "message" in cleaned and isinstance(cleaned["message"], str):
        normalized["message"] = cleaned["message"]
    if "error_code" in cleaned and not normalized["found"]:
        normalized["error_code"] = cleaned["error_code"]
    return normalized


async def _post_contact_context(
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
        tool_name="contact_context",
    )


async def contact_context(
    phone: str | None = None,
    email: str | None = None,
    name: str | None = None,
    tenant_id: str | None = None,
    channel: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Get commercial and operational context for a contact and tenant before agenda actions."""
    payload = ContactContextInput(phone=phone, email=email, name=name, tenant_id=tenant_id, channel=channel)
    settings = get_settings()
    webhook_url = _normalize_text(settings.contact_context_webhook_url)
    webhook_token = _normalize_text(settings.n8n_webhook_bearer_token)
    timeout_seconds = settings.contact_context_timeout_seconds
    downstream_authorization = extract_request_authorization(ctx)

    if webhook_url is None:
        return _empty_contact_payload("Contact context tool is not configured.", "not_configured")

    normalized_phone = _normalize_text(payload.phone)
    normalized_email = _normalize_text(payload.email)
    normalized_name = _normalize_text(payload.name)
    normalized_tenant_id = _normalize_text(payload.tenant_id)
    normalized_channel = _normalize_text(payload.channel)

    if normalized_phone is None and normalized_email is None:
        return _empty_contact_payload(
            "Phone or email is required to retrieve contact context.",
            "validation_error",
        )

    body = {
        "tool": "contact_context",
        "tenant_id": normalized_tenant_id,
        "contact": {
            "phone": normalized_phone,
            "email": normalized_email,
            "name": normalized_name,
        },
        "channel": normalized_channel,
        "source": "mcp-gateway",
    }

    try:
        upstream_payload = await _post_contact_context(
            webhook_url,
            webhook_token,
            timeout_seconds,
            body,
            downstream_authorization=downstream_authorization,
        )
    except httpx.TimeoutException:
        return _empty_contact_payload("Contact context request timed out.", "timeout")
    except httpx.HTTPStatusError:
        return _empty_contact_payload("Contact context service returned an error.", "upstream_error")
    except httpx.RequestError:
        return _empty_contact_payload("Contact context service is unavailable.", "upstream_error")
    except Exception:
        logger.exception("Unexpected error while retrieving contact context")
        return _empty_contact_payload("Contact context service is unavailable.", "upstream_error")

    normalized_response = _normalize_success_payload(upstream_payload)
    if "error_code" not in normalized_response and not normalized_response.get("ok", True):
        normalized_response["error_code"] = "upstream_error"
    return normalized_response
