from __future__ import annotations

import json
import importlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.tools.appointment_booking_invitation import appointment_booking_invitation
from app.tools.appointment_cancel import appointment_cancel
from app.tools.appointment_availability import appointment_availability
from app.tools.appointment_confirm import appointment_confirm
from app.tools.appointment_reschedule import appointment_reschedule
from app.tools.contact_context import contact_context
from app.tools.contact_context_mock import contact_context_mock
from app.tools.echo import echo
from app.tools.services_search import services_search
from app.tools._appointment_common import summarize_authorization

appointment_booking_invitation_module = importlib.import_module("app.tools.appointment_booking_invitation")
appointment_cancel_module = importlib.import_module("app.tools.appointment_cancel")
appointment_availability_module = importlib.import_module("app.tools.appointment_availability")
appointment_confirm_module = importlib.import_module("app.tools.appointment_confirm")
appointment_reschedule_module = importlib.import_module("app.tools.appointment_reschedule")
contact_context_module = importlib.import_module("app.tools.contact_context")
services_search_module = importlib.import_module("app.tools.services_search")
appointment_common_module = importlib.import_module("app.tools._appointment_common")

MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def decode_sse_json(response):
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        return response.json()

    payload_lines = [line.removeprefix("data: ").strip() for line in response.text.splitlines() if line.startswith("data: ")]
    if payload_lines:
        return json.loads(payload_lines[-1])

    return json.loads(response.text)


def make_context(authorization: str | None = None):
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization

    return SimpleNamespace(
        request_context=SimpleNamespace(
            request=SimpleNamespace(headers=headers),
        )
    )


def test_health_endpoint():
    client = TestClient(create_app(Settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "mcp-gateway"}


def test_info_endpoint_lists_tools():
    client = TestClient(create_app(Settings()))

    response = client.get("/info")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "mcp-gateway"
    assert payload["environment"] == "dev"
    assert "echo" in [tool["name"] for tool in payload["available_tools"]]
    assert "contact_context_mock" in [tool["name"] for tool in payload["available_tools"]]
    assert "contact_context" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_availability" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_events" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_confirm" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_reschedule" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_cancel" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_booking_invitation" in [tool["name"] for tool in payload["available_tools"]]
    assert "services_search" in [tool["name"] for tool in payload["available_tools"]]


def test_info_endpoint_lists_debug_tool_when_enabled():
    client = TestClient(create_app(Settings(MCP_ENABLE_DEBUG_TOOLS=True)))

    response = client.get("/info")

    assert response.status_code == 200
    payload = response.json()
    assert "debug_auth_context" in [tool["name"] for tool in payload["available_tools"]]


def test_mcp_discovery_and_tool_call_work_via_streamable_http():
    settings = Settings(MCP_ALLOWED_HOSTS="localhost,127.0.0.1,*.trycloudflare.com")
    app = create_app(settings)

    with TestClient(app, base_url="https://acknowledged-quote-welding-riverside.trycloudflare.com") as client:
        initialize_response = client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
            follow_redirects=False,
        )

        assert initialize_response.status_code == 200
        initialize_payload = decode_sse_json(initialize_response)
        assert initialize_payload["result"]["serverInfo"]["name"] == "mcp-gateway"

        tools_response = client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            follow_redirects=False,
        )

        assert tools_response.status_code == 200
        tools_payload = decode_sse_json(tools_response)
        tools = tools_payload["result"]["tools"]
        assert "echo" in [tool["name"] for tool in tools]
        assert "contact_context_mock" in [tool["name"] for tool in tools]
        assert "contact_context" in [tool["name"] for tool in tools]
        assert "appointment_availability" in [tool["name"] for tool in tools]
        assert "appointment_events" in [tool["name"] for tool in tools]
        assert "appointment_confirm" in [tool["name"] for tool in tools]
        assert "appointment_reschedule" in [tool["name"] for tool in tools]
        assert "appointment_cancel" in [tool["name"] for tool in tools]
        assert "appointment_booking_invitation" in [tool["name"] for tool in tools]
        assert "services_search" in [tool["name"] for tool in tools]

        call_response = client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "hello"}},
            },
            follow_redirects=False,
        )

        assert call_response.status_code == 200
        call_payload = decode_sse_json(call_response)
        assert "hello" in call_payload["result"]["content"][0]["text"]


def test_debug_auth_context_tool_reports_authorization_header():
    settings = Settings(MCP_ENABLE_DEBUG_TOOLS=True)
    app = create_app(settings)

    with TestClient(app, base_url="https://acknowledged-quote-welding-riverside.trycloudflare.com") as client:
        initialize_response = client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
            follow_redirects=False,
        )
        assert initialize_response.status_code == 200

        tools_response = client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            follow_redirects=False,
        )
        assert tools_response.status_code == 200
        tools_payload = decode_sse_json(tools_response)
        tools = tools_payload["result"]["tools"]
        assert "debug_auth_context" in [tool["name"] for tool in tools]

        call_response = client.post(
            "/mcp",
            headers={
                **MCP_HEADERS,
                "Authorization": "Bearer TEST_MCP_AUTH_TOKEN_123456",
            },
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "debug_auth_context", "arguments": {}},
            },
            follow_redirects=False,
        )

        assert call_response.status_code == 200
        call_payload = decode_sse_json(call_response)
        content = call_payload["result"]["content"]
        text = content[0]["text"] if isinstance(content, list) and content and isinstance(content[0], dict) else ""
        assert "has_authorization" in text
        assert "authorization_scheme" in text
        assert "token_preview" in text


def test_summarize_authorization_masks_token_preview():
    has_authorization, authorization_scheme, token_preview = summarize_authorization(
        "Bearer TEST_DOWNSTREAM_TOKEN_123456"
    )

    assert has_authorization is True
    assert authorization_scheme == "Bearer"
    assert token_preview == "TEST_D...3456"


def test_mcp_auth_disabled_allows_access_to_mcp_route():
    with TestClient(create_app(Settings()), base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
            follow_redirects=False,
        )

    assert response.status_code != 401


def test_mcp_auth_enabled_blocks_missing_token():
    with TestClient(create_app(Settings(MCP_AUTH_TOKEN="super-secret")), base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
            follow_redirects=False,
        )

    assert response.status_code == 401


def test_echo_tool_returns_expected_payload():
    assert echo("hello") == {"message": "hello", "echoed": True}


def test_contact_context_mock_returns_expected_payload():
    payload = contact_context_mock(phone="+34999999999", email="test@example.com")

    assert payload["found"] is True
    assert payload["contact"]["name"] == "Cliente Demo"
    assert payload["contact"]["status"] == "lead"
    assert payload["contact"]["stage"] == "new"


@pytest.mark.asyncio
async def test_appointment_availability_without_webhook_returns_not_configured(monkeypatch):
    monkeypatch.setattr(
        appointment_availability_module,
        "get_settings",
        lambda: Settings(APPOINTMENT_AVAILABILITY_WEBHOOK_URL=""),
    )

    payload = await appointment_availability(date_from="2026-05-11", date_to="2026-05-15")

    assert payload["ok"] is False
    assert payload["available"] is False
    assert payload["error_code"] == "not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "function", "settings_key", "kwargs", "flag_key"),
    [
        (
            appointment_confirm_module,
            appointment_confirm,
            "APPOINTMENT_CONFIRM_WEBHOOK_URL",
            {},
            "confirmed",
        ),
        (
            appointment_reschedule_module,
            appointment_reschedule,
            "APPOINTMENT_RESCHEDULE_WEBHOOK_URL",
            {},
            "rescheduled",
        ),
        (
            appointment_cancel_module,
            appointment_cancel,
            "APPOINTMENT_CANCEL_WEBHOOK_URL",
            {},
            "cancelled",
        ),
        (
            appointment_booking_invitation_module,
            appointment_booking_invitation,
            "APPOINTMENT_BOOKING_INVITATION_WEBHOOK_URL",
            {},
            "created",
        ),
    ],
)
async def test_appointment_actions_without_webhook_return_not_configured(monkeypatch, module, function, settings_key, kwargs, flag_key):
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: Settings(**{settings_key: ""}),
    )

    payload = await function(**kwargs)

    assert payload["ok"] is False
    assert payload["error_code"] == "not_configured"
    assert payload[flag_key] is False


@pytest.mark.asyncio
async def test_appointment_confirm_posts_expected_slot_payload(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "confirmed": True,
                "appointment_id": "appointment-1",
                "message": "Appointment confirmed.",
                "raw_summary": {"status": "confirmed"},
            },
        )

    monkeypatch.setattr(
        appointment_confirm_module,
        "get_settings",
        lambda: Settings(
            APPOINTMENT_CONFIRM_WEBHOOK_URL="https://n8n.example/webhook",
            N8N_WEBHOOK_BEARER_TOKEN="secret-token",
            APPOINTMENT_CONFIRM_TIMEOUT_SECONDS=9,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await appointment_confirm(
        tenant_id=" 019dddb7-db7b-7cdd-963e-4294476ba1e7 ",
        start_at=" 2026-05-20T10:00:00+02:00 ",
        end_at=" 2026-05-20T10:30:00+02:00 ",
        timezone=" Europe/Madrid ",
        service_ref=" null ",
        owner_ref=" 019c33aa-5f3d-729d-933e-3a8c28a2e66d ",
        contact={
            "phone": " +34611949358 ",
            "email": " undefined ",
            "name": " Lucia Garcia ",
        },
        title=" Llamada comercial ",
        notes=" Prueba directa n8n appointment_confirm ",
        conversation_id=" conv-1 ",
        entrypoint_ref=" ref-1 ",
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["url"] == "https://n8n.example/webhook"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "X-N8N-Webhook-Token": "Bearer secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert captured["json"] == {
        "tool": "appointment_confirm",
        "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
        "slot": {
            "start": "2026-05-20T10:00:00+02:00",
            "end": "2026-05-20T10:30:00+02:00",
            "owner": {
                "id": "019c33aa-5f3d-729d-933e-3a8c28a2e66d",
            },
        },
        "timezone": "Europe/Madrid",
        "service_ref": None,
        "contact": {
            "phone": "+34611949358",
            "email": None,
            "name": "Lucia Garcia",
        },
        "title": "Llamada comercial",
        "notes": "Prueba directa n8n appointment_confirm",
        "conversation_id": "conv-1",
        "entrypoint_ref": "ref-1",
        "source": "mcp-gateway",
    }
    assert payload["ok"] is True
    assert payload["confirmed"] is True
    assert payload["appointment"]["id"] == "appointment-1"
    assert payload["message"] == "Appointment confirmed."


@pytest.mark.asyncio
async def test_appointment_availability_requires_date_from_and_date_to(monkeypatch):
    monkeypatch.setattr(
        appointment_availability_module,
        "get_settings",
        lambda: Settings(APPOINTMENT_AVAILABILITY_WEBHOOK_URL="https://n8n.example/webhook"),
    )

    missing_date_from = await appointment_availability(date_from=None, date_to="2026-05-15")
    missing_date_to = await appointment_availability(date_from="2026-05-11", date_to=None)

    assert missing_date_from["error_code"] == "validation_error"
    assert missing_date_to["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_appointment_availability_posts_expected_payload(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "available": True,
                "timezone": "Europe/Madrid",
                "slots": [
                    {
                        "start": "2026-05-11T09:00:00+02:00",
                        "end": "2026-05-11T09:30:00+02:00",
                        "label": None,
                        "owner": {
                            "id": "019c33aa-5f3d-729d-933e-3a8c28a2e66d",
                            "name": "Carla",
                            "email": "agente@gmail.com",
                            "preferred": False,
                        },
                    }
                ],
                "message": "Hay 6 hueco(s) disponible(s) de 6 encontrados.",
                "raw_summary": {
                    "mode": "multi_owner",
                    "durationMinutes": 30,
                    "ownersCount": 3,
                    "totalSlots": 6,
                    "returnedSlots": 6,
                    "preferredOwnerId": None,
                    "preferredOwnerName": None,
                },
            },
        )

    monkeypatch.setattr(
        appointment_availability_module,
        "get_settings",
        lambda: Settings(
            APPOINTMENT_AVAILABILITY_WEBHOOK_URL="https://n8n.example/webhook",
            N8N_WEBHOOK_BEARER_TOKEN="secret-token",
            APPOINTMENT_AVAILABILITY_TIMEOUT_SECONDS=9,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await appointment_availability(
        tenant_id="019dddb7-db7b-7cdd-963e-4294476ba1e7",
        date_from="2026-05-11",
        date_to="2026-05-15",
        timezone="  ",
        duration_minutes=30,
        limit=6,
        service_ref="null",
        owner_ref="",
        contact={
            "phone": " +34611949358 ",
            "email": "null",
            "name": " Lucia Garcia ",
        },
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["url"] == "https://n8n.example/webhook"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "X-N8N-Webhook-Token": "Bearer secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert captured["json"] == {
        "tool": "appointment_availability",
        "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
        "date_from": "2026-05-11",
        "date_to": "2026-05-15",
        "timezone": "Europe/Madrid",
        "duration_minutes": 30,
        "limit": 6,
        "service_ref": None,
        "owner_ref": None,
        "contact": {
            "phone": "+34611949358",
            "email": None,
            "name": "Lucia Garcia",
        },
        "source": "mcp-gateway",
    }
    assert payload["ok"] is True
    assert payload["available"] is True
    assert payload["timezone"] == "Europe/Madrid"
    assert payload["slots"][0]["owner"]["name"] == "Carla"
    assert payload["message"].startswith("Hay 6")


@pytest.mark.asyncio
async def test_contact_context_without_webhook_returns_not_configured(monkeypatch):
    monkeypatch.setattr(contact_context_module, "get_settings", lambda: Settings(CONTACT_CONTEXT_WEBHOOK_URL=""))

    payload = await contact_context(phone="+34123456789")

    assert payload["found"] is False
    assert payload["error_code"] == "not_configured"


@pytest.mark.asyncio
async def test_contact_context_without_phone_or_email_returns_validation_error(monkeypatch):
    monkeypatch.setattr(
        contact_context_module,
        "get_settings",
        lambda: Settings(CONTACT_CONTEXT_WEBHOOK_URL="https://n8n.example/webhook"),
    )

    payload = await contact_context(name="Cliente Demo")

    assert payload["found"] is False
    assert payload["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_contact_context_posts_expected_payload(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "found": True,
                "contact": {
                    "name": "Cliente Demo",
                    "type": "lead",
                    "status": "lead",
                    "stage": "new",
                },
                "summary": "Cliente demo",
            },
        )

    monkeypatch.setattr(
        contact_context_module,
        "get_settings",
        lambda: Settings(
            CONTACT_CONTEXT_WEBHOOK_URL="https://n8n.example/webhook",
            N8N_WEBHOOK_BEARER_TOKEN="secret-token",
            CONTACT_CONTEXT_TIMEOUT_SECONDS=7,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await contact_context(
        phone=" +34999999999 ",
        email="null",
        name="  Cliente Demo  ",
        tenant_id=" tenant-1 ",
        channel=" whatsapp ",
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["url"] == "https://n8n.example/webhook"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "X-N8N-Webhook-Token": "Bearer secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert captured["json"] == {
        "tool": "contact_context",
        "tenant_id": "tenant-1",
        "contact": {
            "phone": "+34999999999",
            "email": None,
            "name": "Cliente Demo",
        },
        "channel": "whatsapp",
        "source": "mcp-gateway",
    }
    assert payload["found"] is True
    assert payload["contact"]["name"] == "Cliente Demo"


@pytest.mark.asyncio
async def test_contact_context_timeout_returns_timeout_error(monkeypatch):
    request = httpx.Request("POST", "https://n8n.example/webhook")

    async def fake_post(self, url, json=None, headers=None):
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(
        contact_context_module,
        "get_settings",
        lambda: Settings(CONTACT_CONTEXT_WEBHOOK_URL="https://n8n.example/webhook"),
    )
    monkeypatch.setattr(contact_context_module.httpx.AsyncClient, "post", fake_post)

    payload = await contact_context(phone="+34999999999")

    assert payload["found"] is False
    assert payload["error_code"] == "timeout"


@pytest.mark.asyncio
async def test_appointment_availability_timeout_returns_timeout_error(monkeypatch):
    request = httpx.Request("POST", "https://n8n.example/webhook")

    async def fake_post(self, url, json=None, headers=None):
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(
        appointment_availability_module,
        "get_settings",
        lambda: Settings(APPOINTMENT_AVAILABILITY_WEBHOOK_URL="https://n8n.example/webhook"),
    )
    monkeypatch.setattr(appointment_availability_module.httpx.AsyncClient, "post", fake_post)

    payload = await appointment_availability(date_from="2026-05-11", date_to="2026-05-15")

    assert payload["ok"] is False
    assert payload["error_code"] == "timeout"


@pytest.mark.asyncio
async def test_services_search_without_webhook_returns_not_configured(monkeypatch):
    monkeypatch.setattr(
        services_search_module,
        "get_settings",
        lambda: Settings(SERVICES_SEARCH_WEBHOOK_URL=""),
    )

    payload = await services_search(query="whatsapp")

    assert payload["ok"] is False
    assert payload["found"] is False
    assert payload["error_code"] == "not_configured"


@pytest.mark.asyncio
async def test_services_search_rejects_invalid_limit(monkeypatch):
    monkeypatch.setattr(
        services_search_module,
        "get_settings",
        lambda: Settings(SERVICES_SEARCH_WEBHOOK_URL="https://n8n.example/webhook"),
    )

    payload = await services_search(limit=True)

    assert payload["ok"] is False
    assert payload["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_services_search_posts_expected_payload(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "found": True,
                "count": 4,
                "items": [
                    {
                        "id": "service-1",
                        "name": "WhatsApp Automation",
                        "slug": "whatsapp-automation",
                        "integration_key": "wa-automation",
                        "description": "Servicio demo",
                        "base_price_cents": 120000,
                        "currency": "EUR",
                        "category": {
                            "id": "cat-1",
                            "name": "Automatización",
                            "slug": "automation",
                        },
                        "is_bookable": False,
                        "is_billable": True,
                        "duration_minutes": None,
                        "buffer_before_minutes": 0,
                        "buffer_after_minutes": 0,
                        "active": True,
                    }
                ],
                "categories": [],
                "message": "4 services found",
                "raw_summary": {},
            },
        )

    monkeypatch.setattr(
        services_search_module,
        "get_settings",
        lambda: Settings(
            SERVICES_SEARCH_WEBHOOK_URL="https://n8n.example/webhook",
            N8N_WEBHOOK_BEARER_TOKEN="secret-token",
            SERVICES_SEARCH_TIMEOUT_SECONDS=11,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await services_search(
        tenant_id=" 019dddb7-db7b-7cdd-963e-4294476ba1e7 ",
        query=" whatsapp ",
        bookable=None,
        active=True,
        category=" null ",
        limit=30,
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["url"] == "https://n8n.example/webhook"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "X-N8N-Webhook-Token": "Bearer secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert captured["json"] == {
        "tool": "services_search",
        "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
        "query": "whatsapp",
        "bookable": None,
        "active": True,
        "category": None,
        "limit": 30,
        "source": "mcp-gateway",
    }
    assert payload["ok"] is True
    assert payload["found"] is True
    assert payload["count"] == 4
    assert payload["items"][0]["category"]["name"] == "Automatización"


@pytest.mark.asyncio
async def test_services_search_timeout_returns_timeout_error(monkeypatch):
    request = httpx.Request("POST", "https://n8n.example/webhook")

    async def fake_post(self, url, json=None, headers=None):
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(
        services_search_module,
        "get_settings",
        lambda: Settings(SERVICES_SEARCH_WEBHOOK_URL="https://n8n.example/webhook"),
    )
    monkeypatch.setattr(services_search_module.httpx.AsyncClient, "post", fake_post)

    payload = await services_search(query="whatsapp")

    assert payload["ok"] is False
    assert payload["error_code"] == "timeout"
