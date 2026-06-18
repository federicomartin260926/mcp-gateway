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
from app.tools.appointment_events import appointment_events
from app.tools.appointment_reschedule import appointment_reschedule
from app.tools.contact_context import contact_context
from app.tools.crm_contact_submit import crm_contact_submit
from app.tools.handoff_request import handoff_request
from app.tools.contact_context_mock import contact_context_mock
from app.tools.echo import echo
from app.tools.services_search import services_search
from app.tools._appointment_common import summarize_authorization

appointment_booking_invitation_module = importlib.import_module("app.tools.appointment_booking_invitation")
appointment_cancel_module = importlib.import_module("app.tools.appointment_cancel")
appointment_availability_module = importlib.import_module("app.tools.appointment_availability")
appointment_confirm_module = importlib.import_module("app.tools.appointment_confirm")
appointment_events_module = importlib.import_module("app.tools.appointment_events")
appointment_reschedule_module = importlib.import_module("app.tools.appointment_reschedule")
contact_context_module = importlib.import_module("app.tools.contact_context")
crm_contact_submit_module = importlib.import_module("app.tools.crm_contact_submit")
handoff_request_module = importlib.import_module("app.tools.handoff_request")
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


def _tool_input_properties(tools, tool_name: str) -> dict[str, object]:
    tool = next(tool for tool in tools if tool["name"] == tool_name)
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            return properties
    return {}


def make_context(authorization: str | None = None, request_id: str | None = None):
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization

    request = SimpleNamespace(headers=headers)
    if request_id is not None:
        request.state = SimpleNamespace(request_id=request_id)

    return SimpleNamespace(
        request_context=SimpleNamespace(
            request=request,
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
    assert "crm_contact_submit" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_availability" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_events" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_confirm" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_reschedule" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_cancel" in [tool["name"] for tool in payload["available_tools"]]
    assert "appointment_booking_invitation" in [tool["name"] for tool in payload["available_tools"]]
    assert "services_search" in [tool["name"] for tool in payload["available_tools"]]
    assert "handoff_request" in [tool["name"] for tool in payload["available_tools"]]


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
        assert "crm_contact_submit" in [tool["name"] for tool in tools]
        assert "appointment_availability" in [tool["name"] for tool in tools]
        assert "appointment_events" in [tool["name"] for tool in tools]
        assert "appointment_confirm" in [tool["name"] for tool in tools]
        assert "appointment_reschedule" in [tool["name"] for tool in tools]
        assert "appointment_cancel" in [tool["name"] for tool in tools]
        assert "appointment_booking_invitation" in [tool["name"] for tool in tools]
        assert "services_search" in [tool["name"] for tool in tools]
        assert "handoff_request" in [tool["name"] for tool in tools]
        availability_properties = _tool_input_properties(tools, "appointment_availability")
        events_properties = _tool_input_properties(tools, "appointment_events")
        confirm_properties = _tool_input_properties(tools, "appointment_confirm")
        reschedule_properties = _tool_input_properties(tools, "appointment_reschedule")
        booking_properties = _tool_input_properties(tools, "appointment_booking_invitation")
        confirm_schema = next(tool for tool in tools if tool["name"] == "appointment_confirm").get("inputSchema", {})
        assert "service_id" in availability_properties
        assert "service_ref" in availability_properties
        assert availability_properties["timezone"].get("default") is None
        assert events_properties["timezone"].get("default") is None
        assert "service_id" in confirm_properties
        assert "service_ref" in confirm_properties
        assert "owner_id" in confirm_properties
        assert "owner_ref" in confirm_properties
        assert "timezone" in confirm_properties
        assert confirm_properties["timezone"].get("default") is None
        assert reschedule_properties["timezone"].get("default") is None
        assert booking_properties["timezone"].get("default") is None
        assert confirm_schema.get("required") == ["tenant_id", "start_at", "end_at", "timezone", "contact"]
        assert "anyOf" not in confirm_schema.get("properties", {}).get("contact", {})
        assert "service_id" in booking_properties
        assert "service_ref" in booking_properties

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

    payload = await appointment_availability(
        date_from="2026-05-11",
        date_to="2026-05-15",
        timezone="Atlantic/Canary",
    )

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
            {
                "tenant_id": "tenant-1",
                "start_at": "2026-05-20T10:00:00+02:00",
                "end_at": "2026-05-20T10:30:00+02:00",
                "timezone": "Europe/Madrid",
                "contact": {"phone": "+34999999999"},
            },
            "confirmed",
        ),
        (
            appointment_reschedule_module,
            appointment_reschedule,
            "APPOINTMENT_RESCHEDULE_WEBHOOK_URL",
            {
                "tenant_id": "tenant-1",
                "appointment_id": "appointment-1",
                "new_start_at": "2026-05-20T10:00:00+00:00",
                "timezone": "Atlantic/Canary",
            },
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
            {
                "tenant_id": "tenant-1",
                "contact": {"phone": "+34999999999"},
                "timezone": "Atlantic/Canary",
            },
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
        timezone=" Atlantic/Canary ",
        service_id=" 019e8ce0-0864-7720-af82-a5c98df2d2dd ",
        service_ref=" null ",
        owner_id=" 019c33aa-5f3d-729d-933e-3a8c28a2e66d ",
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
        "Authorization": "Bearer secret-token",
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
        "timezone": "Atlantic/Canary",
        "service_id": "019e8ce0-0864-7720-af82-a5c98df2d2dd",
        "service_ref": None,
        "owner_id": "019c33aa-5f3d-729d-933e-3a8c28a2e66d",
        "owner_ref": "019c33aa-5f3d-729d-933e-3a8c28a2e66d",
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
async def test_appointment_confirm_prefers_owner_id_in_slot_and_body(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
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
            },
        )

    monkeypatch.setattr(
        appointment_confirm_module,
        "get_settings",
        lambda: Settings(APPOINTMENT_CONFIRM_WEBHOOK_URL="https://n8n.example/webhook"),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await appointment_confirm(
        tenant_id="tenant-1",
        start_at="2026-05-20T10:00:00+02:00",
        end_at="2026-05-20T10:30:00+02:00",
        timezone="Europe/Madrid",
        service_id="service-1",
        owner_id="owner-1",
        contact={"phone": "+34999999999"},
    )

    assert payload["ok"] is True
    assert captured["json"]["owner_id"] == "owner-1"
    assert captured["json"]["slot"]["owner"]["id"] == "owner-1"
    assert "ref" not in captured["json"]["slot"]["owner"]


@pytest.mark.asyncio
async def test_appointment_confirm_keeps_owner_ref_compatibility(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["json"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "confirmed": True,
                "appointment_id": "appointment-1",
                "message": "Appointment confirmed.",
            },
        )

    monkeypatch.setattr(
        appointment_confirm_module,
        "get_settings",
        lambda: Settings(APPOINTMENT_CONFIRM_WEBHOOK_URL="https://n8n.example/webhook"),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await appointment_confirm(
        tenant_id="tenant-1",
        start_at="2026-05-20T10:00:00+02:00",
        end_at="2026-05-20T10:30:00+02:00",
        timezone="Europe/Madrid",
        service_ref="service-slug",
        owner_ref="owner-slug",
        contact={"phone": "+34999999999"},
    )

    assert payload["ok"] is True
    assert captured["json"]["service_ref"] == "service-slug"
    assert captured["json"]["owner_ref"] == "owner-slug"
    assert captured["json"]["slot"]["owner"]["id"] == "owner-slug"
    assert "ref" not in captured["json"]["slot"]["owner"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, expected_fragment",
    [
        (
            {
                "tenant_id": None,
                "start_at": "2026-05-20T10:00:00+02:00",
                "end_at": "2026-05-20T10:30:00+02:00",
                "timezone": "Europe/Madrid",
                "service_id": "service-1",
                "owner_id": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "tenant_id",
        ),
        (
            {
                "tenant_id": "tenant-1",
                "start_at": None,
                "end_at": "2026-05-20T10:30:00+02:00",
                "timezone": "Europe/Madrid",
                "service_id": "service-1",
                "owner_id": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "start_at",
        ),
        (
            {
                "tenant_id": "tenant-1",
                "start_at": "2026-05-20T10:00:00+02:00",
                "end_at": None,
                "timezone": "Europe/Madrid",
                "service_id": "service-1",
                "owner_id": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "end_at",
        ),
        (
            {
                "tenant_id": "tenant-1",
                "start_at": "2026-05-20T10:00:00+02:00",
                "end_at": "2026-05-20T10:30:00+02:00",
                "timezone": " ",
                "service_id": "service-1",
                "owner_id": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "timezone",
        ),
        (
            {
                "tenant_id": "tenant-1",
                "start_at": "2026-05-20T10:00:00+02:00",
                "end_at": "2026-05-20T10:30:00+02:00",
                "timezone": "Europe/Madrid",
                "service_id": None,
                "service_ref": None,
                "owner_id": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "service_id/service_ref",
        ),
        (
            {
                "tenant_id": "tenant-1",
                "start_at": "2026-05-20T10:00:00+02:00",
                "end_at": "2026-05-20T10:30:00+02:00",
                "timezone": "Europe/Madrid",
                "service_id": "service-1",
                "owner_id": None,
                "owner_ref": None,
                "contact": {"phone": "+34999999999"},
            },
            "owner_id/owner_ref",
        ),
        (
            {
                "tenant_id": "tenant-1",
                "start_at": "2026-05-20T10:00:00+02:00",
                "end_at": "2026-05-20T10:30:00+02:00",
                "timezone": "Europe/Madrid",
                "service_id": "service-1",
                "owner_id": "owner-1",
                "contact": {"name": "Lucia Garcia"},
            },
            "contact.phone or contact.email",
        ),
    ],
)
async def test_appointment_confirm_rejects_missing_required_slot_data_without_calling_upstream(monkeypatch, kwargs, expected_fragment):
    called = False

    async def fake_post(self, url, json=None, headers=None):
        nonlocal called
        called = True
        raise AssertionError("upstream call should not happen when appointment_confirm validation fails")

    monkeypatch.setattr(
        appointment_confirm_module,
        "get_settings",
        lambda: Settings(
            APPOINTMENT_CONFIRM_WEBHOOK_URL="https://n8n.example/webhook",
            N8N_WEBHOOK_BEARER_TOKEN="secret-token",
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await appointment_confirm(**kwargs)

    assert called is False
    assert payload["ok"] is False
    assert payload["confirmed"] is False
    assert payload["status"] == "validation_error"
    assert payload["error_code"] == "validation_error"
    assert expected_fragment in payload["message"]


@pytest.mark.asyncio
async def test_appointment_availability_requires_date_from_and_date_to(monkeypatch):
    monkeypatch.setattr(
        appointment_availability_module,
        "get_settings",
        lambda: Settings(APPOINTMENT_AVAILABILITY_WEBHOOK_URL="https://n8n.example/webhook"),
    )

    missing_date_from = await appointment_availability(date_from=None, date_to="2026-05-15", timezone="Atlantic/Canary")
    missing_date_to = await appointment_availability(date_from="2026-05-11", date_to=None, timezone="Atlantic/Canary")

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
                "timezone": "Atlantic/Canary",
                "timezoneSource": "tenant_branch",
                "businessTimezone": "Atlantic/Canary",
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
                    "truncated": False,
                    "serviceId": "019e8ce0-0864-7720-af82-a5c98df2d2dd",
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
        duration_minutes=30,
        limit=100,
        service_id="019e8ce0-0864-7720-af82-a5c98df2d2dd",
        service_ref="maria-laser-axilas",
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
        "Authorization": "Bearer secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert captured["json"] == {
        "tool": "appointment_availability",
        "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
        "date_from": "2026-05-11",
        "date_to": "2026-05-15",
        "duration_minutes": 30,
        "limit": 100,
        "service_id": "019e8ce0-0864-7720-af82-a5c98df2d2dd",
        "service_ref": "maria-laser-axilas",
        "owner_id": None,
        "owner_ref": None,
        "owner_name": None,
        "contact": {
            "phone": "+34611949358",
            "email": None,
            "name": "Lucia Garcia",
        },
        "source": "mcp-gateway",
    }
    assert "timezone" not in captured["json"]
    assert payload["ok"] is True
    assert payload["available"] is True
    assert payload["timezone"] == "Atlantic/Canary"
    assert payload["timezone_source"] == "tenant_branch"
    assert payload["business_timezone"] == "Atlantic/Canary"
    assert payload["slots"][0]["owner"]["name"] == "Carla"
    assert payload["message"].startswith("Hay 6")
    assert payload["raw_summary"]["totalSlots"] == 6
    assert payload["raw_summary"]["returnedSlots"] == 1
    assert payload["raw_summary"]["truncated"] is True
    assert payload["raw_summary"]["serviceId"] == "019e8ce0-0864-7720-af82-a5c98df2d2dd"


@pytest.mark.asyncio
async def test_appointment_availability_marks_truncation_when_more_slots_exist(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["json"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "available": True,
                "timezone": "Europe/Madrid",
                "slots": [
                    {
                        "start": "2026-06-10T09:00:00+02:00",
                        "end": "2026-06-10T09:15:00+02:00",
                        "label": None,
                        "owner": {
                            "id": "019c33aa-5f3d-729d-933e-3a8c28a2e66d",
                            "name": "Carla",
                            "email": "agente@gmail.com",
                            "preferred": False,
                        },
                    },
                    {
                        "start": "2026-06-10T12:00:00+02:00",
                        "end": "2026-06-10T12:15:00+02:00",
                        "label": None,
                        "owner": {
                            "id": "019c33aa-5f3d-729d-933e-3a8c28a2e66d",
                            "name": "Carla",
                            "email": "agente@gmail.com",
                            "preferred": False,
                        },
                    },
                ],
                "message": "Hay 2 hueco(s) disponible(s) de 12 encontrados.",
                "raw_summary": {
                    "mode": "multi_owner",
                    "durationMinutes": 15,
                    "ownersCount": 2,
                    "totalSlots": 12,
                    "returnedSlots": 2,
                    "truncated": True,
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
        date_from="2026-06-10T14:00:00+02:00",
        date_to="2026-06-10T21:00:00+02:00",
        timezone="Europe/Madrid",
        duration_minutes=15,
        limit=100,
        service_id="019e8ce0-0864-7720-af82-a5c98df2d2dd",
        service_ref="maria-laser-axilas",
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["json"]["limit"] == 100
    assert payload["ok"] is True
    assert payload["available"] is True
    assert payload["raw_summary"]["totalSlots"] == 12
    assert payload["raw_summary"]["returnedSlots"] == 2
    assert payload["raw_summary"]["truncated"] is True
    assert payload["raw_summary"]["serviceId"] == "019e8ce0-0864-7720-af82-a5c98df2d2dd"


@pytest.mark.asyncio
async def test_appointment_booking_invitation_posts_expected_payload(monkeypatch):
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
                "created": True,
                "booking_url": "https://booking.example/invite/abc",
                "message": "Booking invitation created.",
                "raw_summary": {"status": "created"},
            },
        )

    monkeypatch.setattr(
        appointment_booking_invitation_module,
        "get_settings",
        lambda: Settings(
            APPOINTMENT_BOOKING_INVITATION_WEBHOOK_URL="https://n8n.example/webhook",
            N8N_WEBHOOK_BEARER_TOKEN="secret-token",
            APPOINTMENT_BOOKING_INVITATION_TIMEOUT_SECONDS=9,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await appointment_booking_invitation(
        tenant_id=" 019dddb7-db7b-7cdd-963e-4294476ba1e7 ",
        contact={
            "phone": " +34611949358 ",
            "email": " undefined ",
            "name": " Lucia Garcia ",
        },
        timezone=" Europe/Madrid ",
        service_id=" 019e8ce0-0864-7720-af82-a5c98df2d2dd ",
        service_ref=" maria-laser-cuerpo-entero ",
        owner_ref=" 019c33aa-5f3d-729d-933e-3a8c28a2e66d ",
        date_from=" 2026-05-11 ",
        date_to=" 2026-05-15 ",
        duration_minutes=30,
        notes=" Seguimiento de reserva ",
        conversation_id=" conv-1 ",
        entrypoint_ref=" ref-1 ",
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["url"] == "https://n8n.example/webhook"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert captured["json"] == {
        "tool": "appointment_booking_invitation",
        "tenant_id": "019dddb7-db7b-7cdd-963e-4294476ba1e7",
        "contact": {
            "phone": "+34611949358",
            "email": None,
            "name": "Lucia Garcia",
        },
        "timezone": "Europe/Madrid",
        "service_id": "019e8ce0-0864-7720-af82-a5c98df2d2dd",
        "service_ref": "maria-laser-cuerpo-entero",
        "owner_ref": "019c33aa-5f3d-729d-933e-3a8c28a2e66d",
        "date_from": "2026-05-11",
        "date_to": "2026-05-15",
        "duration_minutes": 30,
        "notes": "Seguimiento de reserva",
        "conversation_id": "conv-1",
        "entrypoint_ref": "ref-1",
        "source": "mcp-gateway",
    }
    assert payload["ok"] is True
    assert payload["created"] is True
    assert payload["booking_url"] == "https://booking.example/invite/abc"
    assert payload["message"] == "Booking invitation created."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "function, module, settings_key, kwargs, expected_message_fragment",
    [
        (
            appointment_events,
            appointment_events_module,
            "APPOINTMENT_EVENTS_WEBHOOK_URL",
            {
                "tenant_id": "tenant-1",
                "date_from": "2026-05-11",
                "date_to": "2026-05-15",
                "timezone": None,
                "service_ref": "service-slug",
                "owner_ref": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "timezone",
        ),
        (
            appointment_reschedule,
            appointment_reschedule_module,
            "APPOINTMENT_RESCHEDULE_WEBHOOK_URL",
            {
                "tenant_id": "tenant-1",
                "appointment_id": "appointment-1",
                "new_start_at": "2026-05-20T10:00:00+00:00",
                "new_end_at": "2026-05-20T10:30:00+00:00",
                "timezone": None,
                "service_ref": "service-slug",
                "owner_ref": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "timezone",
        ),
        (
            appointment_booking_invitation,
            appointment_booking_invitation_module,
            "APPOINTMENT_BOOKING_INVITATION_WEBHOOK_URL",
            {
                "tenant_id": "tenant-1",
                "contact": {"phone": "+34999999999"},
                "timezone": None,
                "service_ref": "service-slug",
                "owner_ref": "owner-1",
                "date_from": "2026-05-11",
                "date_to": "2026-05-15",
            },
            "timezone",
        ),
    ],
)
async def test_agenda_tools_reject_missing_timezone_without_calling_upstream(
    monkeypatch,
    function,
    module,
    settings_key,
    kwargs,
    expected_message_fragment,
):
    called = False

    async def fake_post(self, url, json=None, headers=None):
        nonlocal called
        called = True
        raise AssertionError("upstream call should not happen when timezone is missing")

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: Settings(**{settings_key: "https://n8n.example/webhook", "N8N_WEBHOOK_BEARER_TOKEN": "secret-token"}),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await function(**kwargs)

    assert called is False
    assert payload["ok"] is False
    assert payload["status"] == "validation_error"
    assert payload["error_code"] == "validation_error"
    assert expected_message_fragment in payload["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "function, module, settings_key, kwargs, expected_body_timezone",
    [
        (
            appointment_events,
            appointment_events_module,
            "APPOINTMENT_EVENTS_WEBHOOK_URL",
            {
                "tenant_id": "tenant-1",
                "date_from": "2026-05-11",
                "date_to": "2026-05-15",
                "timezone": "Atlantic/Canary",
                "service_ref": "service-slug",
                "owner_ref": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "Atlantic/Canary",
        ),
        (
            appointment_reschedule,
            appointment_reschedule_module,
            "APPOINTMENT_RESCHEDULE_WEBHOOK_URL",
            {
                "tenant_id": "tenant-1",
                "appointment_id": "appointment-1",
                "new_start_at": "2026-05-20T10:00:00+00:00",
                "new_end_at": "2026-05-20T10:30:00+00:00",
                "timezone": "Atlantic/Canary",
                "service_ref": "service-slug",
                "owner_ref": "owner-1",
                "contact": {"phone": "+34999999999"},
            },
            "Atlantic/Canary",
        ),
    ],
)
async def test_agenda_tools_forward_explicit_timezone_exactly(
    monkeypatch,
    function,
    module,
    settings_key,
    kwargs,
    expected_body_timezone,
):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["json"] = json
        return httpx.Response(200, request=httpx.Request("POST", url), json={"ok": True, "found": True, "rescheduled": True, "message": "ok"})

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: Settings(**{settings_key: "https://n8n.example/webhook", "N8N_WEBHOOK_BEARER_TOKEN": "secret-token"}),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await function(**kwargs)

    assert captured["json"]["timezone"] == expected_body_timezone
    assert payload["ok"] is True


@pytest.mark.asyncio
async def test_contact_context_without_webhook_returns_not_configured(monkeypatch):
    monkeypatch.setattr(contact_context_module, "get_settings", lambda: Settings(CONTACT_CONTEXT_WEBHOOK_URL=""))

    payload = await contact_context(phone="+34123456789")

    assert payload["ok"] is False
    assert payload["status"] == "not_configured"
    assert payload["found"] is False
    assert payload["error_code"] == "not_configured"
    assert payload["message"] == "Contact context tool is not configured."


@pytest.mark.asyncio
async def test_contact_context_without_phone_or_email_returns_validation_error(monkeypatch):
    monkeypatch.setattr(
        contact_context_module,
        "get_settings",
        lambda: Settings(CONTACT_CONTEXT_WEBHOOK_URL="https://n8n.example/webhook"),
    )

    payload = await contact_context(name="Cliente Demo")

    assert payload["ok"] is False
    assert payload["status"] == "validation_error"
    assert payload["found"] is False
    assert payload["error_code"] == "validation_error"
    assert payload["message"] == "Phone or email is required to retrieve contact context."


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
        "Authorization": "Bearer secret-token",
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
    assert "Authorization" not in payload
    assert "X-Downstream-Authorization" not in payload


@pytest.mark.asyncio
async def test_contact_context_normalizes_business_context_and_contact_identity(monkeypatch):
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
                "status": "ok",
                "tenant": {"id": "tenant-1"},
                "found": True,
                "contact": {
                    "name": "Cliente Demo",
                    "id": "contact-1",
                    "last_branch": {"id": "branch-1", "name": "Centro"},
                    "status": "lead",
                },
                "timezone": "Europe/Madrid",
                "timezone_source": "crm_tenant",
                "branch": {"id": "branch-1", "name": "Centro"},
                "branches": [
                    {"id": "branch-1", "name": "Centro"},
                    {"id": "branch-2", "name": "Norte"},
                ],
                "needs_branch_selection": True,
                "appointments": {"next": None, "items": []},
                "open_opportunities": [],
                "sales": {},
                "flags": {},
                "summary": "Contexto comercial listo",
            },
        )

    monkeypatch.setattr(
        contact_context_module,
        "get_settings",
        lambda: Settings(
            CONTACT_CONTEXT_WEBHOOK_URL="https://n8n.example/webhook",
            N8N_WEBHOOK_BEARER_TOKEN="secret-token",
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await contact_context(
        phone="+34999999999",
        tenant_id="tenant-1",
        channel="whatsapp",
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["tenant"] == {"id": "tenant-1"}
    assert payload["found"] is True
    assert payload["contact"]["found"] is True
    assert payload["contact"]["id"] == "contact-1"
    assert payload["contact"]["last_branch"] == {"id": "branch-1", "name": "Centro"}
    assert payload["timezone"] == "Europe/Madrid"
    assert payload["timezone_source"] == "crm_tenant"
    assert payload["branch"] == {"id": "branch-1", "name": "Centro"}
    assert payload["branches"] == [
        {"id": "branch-1", "name": "Centro"},
        {"id": "branch-2", "name": "Norte"},
    ]
    assert payload["needs_branch_selection"] is True
    assert payload["business_context"] == {
        "timezone": "Europe/Madrid",
        "timezone_source": "crm_tenant",
        "branch": {"id": "branch-1", "name": "Centro"},
        "branches": [
            {"id": "branch-1", "name": "Centro"},
            {"id": "branch-2", "name": "Norte"},
        ],
        "needs_branch_selection": True,
    }
    assert "Authorization" not in payload
    assert "X-Downstream-Authorization" not in payload


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

    assert payload["ok"] is False
    assert payload["status"] == "timeout"
    assert payload["found"] is False
    assert payload["error_code"] == "timeout"
    assert payload["message"] == "Contact context request timed out."


@pytest.mark.asyncio
async def test_contact_context_null_contact_marks_contact_unfound(monkeypatch):
    async def fake_post(self, url, json=None, headers=None):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "status": "ok",
                "contact": None,
                "summary": "Sin contacto",
            },
        )

    monkeypatch.setattr(
        contact_context_module,
        "get_settings",
        lambda: Settings(CONTACT_CONTEXT_WEBHOOK_URL="https://n8n.example/webhook"),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await contact_context(phone="+34999999999")

    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["found"] is False
    assert payload["contact"] == {"found": False}


@pytest.mark.asyncio
async def test_crm_contact_submit_without_webhook_returns_not_configured(monkeypatch):
    monkeypatch.setattr(
        crm_contact_submit_module,
        "get_settings",
        lambda: Settings(CRM_CONTACT_SUBMIT_WEBHOOK_URL=""),
    )

    payload = await crm_contact_submit(contact={"phone": "+34123456789"})

    assert payload["ok"] is False
    assert payload["submitted"] is False
    assert payload["status"] == "not_configured"
    assert payload["message"] == "CRM contact submit webhook is not configured."
    assert payload["crm_result"] is None


@pytest.mark.asyncio
async def test_crm_contact_submit_without_phone_or_email_returns_validation_error(monkeypatch):
    monkeypatch.setattr(
        crm_contact_submit_module,
        "get_settings",
        lambda: Settings(CRM_CONTACT_SUBMIT_WEBHOOK_URL="https://n8n.example/webhook"),
    )

    payload = await crm_contact_submit(
        contact={"name": "Cliente Demo"},
        source="whatsapp",
    )

    assert payload["ok"] is False
    assert payload["submitted"] is False
    assert payload["status"] == "validation_error"
    assert payload["crm_result"] is None


@pytest.mark.asyncio
async def test_crm_contact_submit_posts_expected_payload_and_returns_crm_result(monkeypatch):
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
                "submitted": True,
                "status": "customer_updated",
                "message": "CRM contact context submitted.",
                "crm_result": {
                    "ok": True,
                    "status": "customer_updated",
                    "decision": "customer_updated",
                    "contactType": "customer",
                    "contactId": "crm-contact-1",
                    "activityCreated": True,
                    "summaryStored": True,
                    "warnings": [],
                },
            },
        )

    monkeypatch.setattr(
        crm_contact_submit_module,
        "get_settings",
        lambda: Settings(
            CRM_CONTACT_SUBMIT_WEBHOOK_URL="https://n8n.example/webhook",
            CRM_CONTACT_SUBMIT_WEBHOOK_TOKEN="crm-secret-token",
            CRM_CONTACT_SUBMIT_TIMEOUT_SECONDS=11,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await crm_contact_submit(
        contact={
            "name": "Luis Lopez",
            "phone": " +34617214814 ",
            "email": "null",
            "whatsapp_name": " Luis ",
        },
        source="whatsapp",
        channel="whatsapp",
        external_conversation_id=" whatsapp:+34617214814 ",
        entry_point_ref=" wa-mary-main ",
        qualification={
            "is_qualified": True,
            "service_interest": " Depilación láser axilas ",
            "need": " Quiere información y disponibilidad ",
            "urgency": " medium ",
            "preferred_date": None,
            "preferred_time": " afternoon ",
        },
        conversation={
            "summary": " El contacto preguntó por depilación láser de axilas y disponibilidad por la tarde. ",
            "last_message": " ¿Tenéis hueco por la tarde? ",
            "intent": " booking_interest ",
            "needs_human": False,
            "finished": False,
        },
        actions={
            "booking_requested": True,
            "handoff_requested": False,
            "waitlist_requested": False,
        },
        metadata={
            "origin": "sales_agent",
            "sa_conversation_id": " 019... ",
            "service_slug": " laser-axilas ",
            "service_integration_key": None,
            "product_id": None,
            "utm_source": None,
            "utm_medium": None,
            "utm_campaign": None,
            "utm_content": None,
            "utm_term": None,
        },
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["url"] == "https://n8n.example/webhook"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer crm-secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert captured["json"] == {
        "event": "sales_agent.crm_contact_submit",
        "tool": "crm_contact_submit",
        "source": "mcp-gateway",
        "channel": "whatsapp",
        "contact": {
            "name": "Luis Lopez",
            "phone": "+34617214814",
            "email": None,
            "whatsapp_name": "Luis",
        },
        "crm_payload": {
            "source": "whatsapp",
            "channel": "whatsapp",
            "externalConversationId": "whatsapp:+34617214814",
            "entryPointRef": "wa-mary-main",
            "contact": {
                "name": "Luis Lopez",
                "phone": "+34617214814",
                "email": None,
                "whatsappName": "Luis",
            },
            "qualification": {
                "isQualified": True,
                "serviceInterest": "Depilación láser axilas",
                "need": "Quiere información y disponibilidad",
                "urgency": "medium",
                "preferredDate": None,
                "preferredTime": "afternoon",
            },
            "conversation": {
                "summary": "El contacto preguntó por depilación láser de axilas y disponibilidad por la tarde.",
                "lastMessage": "¿Tenéis hueco por la tarde?",
                "intent": "booking_interest",
                "needsHuman": False,
                "finished": False,
            },
            "actions": {
                "bookingRequested": True,
                "handoffRequested": False,
                "waitlistRequested": False,
            },
            "metadata": {
                "origin": "sales_agent",
                "saConversationId": "019...",
                "serviceSlug": "laser-axilas",
                "serviceIntegrationKey": None,
                "productId": None,
                "utmSource": None,
                "utmMedium": None,
                "utmCampaign": None,
                "utmContent": None,
                "utmTerm": None,
            },
        },
    }
    assert payload["ok"] is True
    assert payload["submitted"] is True
    assert payload["status"] == "accepted"
    assert payload["message"] == "CRM contact context submitted."
    assert payload["crm_result"]["decision"] == "customer_updated"
    assert payload["crm_result"]["contactType"] == "customer"
    assert payload["crm_result"]["contactId"] == "crm-contact-1"
    assert "TEST_DOWNSTREAM_TOKEN_123456" not in str(captured["json"])
    assert "crm-secret-token" not in str(payload)


@pytest.mark.asyncio
async def test_crm_contact_submit_logs_safe_metadata(monkeypatch, caplog):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "submitted": True,
                "status": "accepted",
                "message": "CRM contact context submitted.",
                "crm_result": {"ok": True, "status": "accepted", "warnings": []},
            },
        )

    monkeypatch.setattr(
        crm_contact_submit_module,
        "get_settings",
        lambda: Settings(
            CRM_CONTACT_SUBMIT_WEBHOOK_URL="https://n8n.example/webhook",
            CRM_CONTACT_SUBMIT_WEBHOOK_TOKEN="crm-secret-token",
            CRM_CONTACT_SUBMIT_TIMEOUT_SECONDS=11,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    with caplog.at_level("INFO"):
        payload = await crm_contact_submit(
            contact={"phone": "+34123456789"},
            source="whatsapp",
            ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
        )

    log_text = "\n".join(record.message for record in caplog.records)
    assert "service_auth_source=crm_contact_submit_webhook_token" in log_text
    assert "downstream_authorization_present=True" in log_text
    assert "TEST_DOWNSTREAM_TOKEN_123456" not in log_text
    assert "crm-secret-token" not in log_text
    assert payload["status"] == "accepted"
    assert captured["headers"]["Authorization"] == "Bearer crm-secret-token"


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

    payload = await appointment_availability(date_from="2026-05-11", date_to="2026-05-15", timezone="Atlantic/Canary")

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
async def test_handoff_request_without_webhook_returns_not_configured(monkeypatch):
    called = False

    async def fake_post(self, url, json=None, headers=None):
        nonlocal called
        called = True
        raise AssertionError("upstream call should not happen when webhook is missing")

    monkeypatch.setattr(
        handoff_request_module,
        "get_settings",
        lambda: Settings(HANDOFF_REQUEST_WEBHOOK_URL=""),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await handoff_request(tenant_id="tenant-1")

    assert payload["ok"] is False
    assert payload["handoff_requested"] is False
    assert payload["status"] == "not_configured"
    assert called is False


@pytest.mark.asyncio
async def test_handoff_request_posts_expected_payload_without_exposing_secrets(monkeypatch):
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
                "handoff_requested": True,
                "status": "requested",
                "message": "Handoff request queued.",
            },
        )

    monkeypatch.setattr(
        handoff_request_module,
        "get_settings",
        lambda: Settings(
            HANDOFF_REQUEST_WEBHOOK_URL="https://n8n.example/webhook",
            HANDOFF_REQUEST_WEBHOOK_TOKEN="handoff-secret-token",
            HANDOFF_REQUEST_TIMEOUT_SECONDS=9,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await handoff_request(
        tenant_id=" tenant-1 ",
        contact={
            "phone": " +34999999999 ",
            "email": "null",
            "name": " Cliente Demo ",
            "external_id": " ext-1 ",
        },
        conversation={
            "id": " conv-1 ",
            "external_id": " ext-conv-1 ",
            "channel": " whatsapp ",
            "status": " pending_human ",
            "summary": " Resumen corto ",
            "last_messages": [f"mensaje {index}" for index in range(10)],
        },
        reason="frustration",
        priority="high",
        message="Necesito que lo revise una persona.",
        metadata={
            "source": "sales-agent",
            "nested": {"visible": "yes"},
        },
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["url"] == "https://n8n.example/webhook"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer handoff-secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert captured["json"] == {
        "event": "sales_agent.handoff_requested",
        "tenant_id": "tenant-1",
        "contact": {
            "phone": "+34999999999",
            "email": None,
            "name": "Cliente Demo",
            "external_id": "ext-1",
        },
        "conversation": {
            "id": "conv-1",
            "external_conversation_id": "ext-conv-1",
            "channel": "whatsapp",
            "status": "pending_human",
            "summary": "Resumen corto",
            "last_messages": [
                "mensaje 2",
                "mensaje 3",
                "mensaje 4",
                "mensaje 5",
                "mensaje 6",
                "mensaje 7",
                "mensaje 8",
                "mensaje 9",
            ],
        },
        "reason": "frustration",
        "priority": "high",
        "message": "Necesito que lo revise una persona.",
        "metadata": {
            "source": "mcp-gateway",
            "tool": "handoff_request",
            "nested": {"visible": "yes"},
        },
    }
    assert payload["ok"] is True
    assert payload["handoff_requested"] is True
    assert payload["status"] == "accepted"
    assert payload["message"] == "Handoff request queued."
    assert payload["external_reference"] is None
    assert "Bearer TEST_DOWNSTREAM_TOKEN_123456" not in str(captured["json"])


@pytest.mark.asyncio
async def test_handoff_request_falls_back_to_generic_n8n_token(monkeypatch):
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
                "handoff_requested": True,
                "status": "accepted",
                "message": "Handoff registrado.",
            },
        )

    monkeypatch.setattr(
        handoff_request_module,
        "get_settings",
        lambda: Settings(
            HANDOFF_REQUEST_WEBHOOK_URL="https://n8n.example/webhook",
            HANDOFF_REQUEST_WEBHOOK_TOKEN="",
            N8N_WEBHOOK_BEARER_TOKEN="n8n-secret-token",
            HANDOFF_REQUEST_TIMEOUT_SECONDS=9,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await handoff_request(
        tenant_id="tenant-1",
        reason="needs_human",
        ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
    )

    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer n8n-secret-token",
        "X-Downstream-Authorization": "Bearer TEST_DOWNSTREAM_TOKEN_123456",
    }
    assert payload["ok"] is True
    assert payload["handoff_requested"] is True
    assert payload["status"] == "accepted"
    assert "n8n-secret-token" not in str(payload)
    assert "TEST_DOWNSTREAM_TOKEN_123456" not in str(payload)


@pytest.mark.asyncio
async def test_handoff_request_logs_safe_metadata(monkeypatch, caplog):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "handoff_requested": True,
                "status": "accepted",
                "message": "Handoff registrado.",
            },
        )

    monkeypatch.setattr(
        handoff_request_module,
        "get_settings",
        lambda: Settings(
            HANDOFF_REQUEST_WEBHOOK_URL="https://n8n.example/webhook",
            HANDOFF_REQUEST_WEBHOOK_TOKEN="handoff-secret-token",
            HANDOFF_REQUEST_TIMEOUT_SECONDS=9,
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    with caplog.at_level("INFO"):
        payload = await handoff_request(
            tenant_id="tenant-1",
            reason="needs_human",
            ctx=make_context("Bearer TEST_DOWNSTREAM_TOKEN_123456"),
        )

    log_text = "\n".join(record.message for record in caplog.records)
    assert "service_auth_source=handoff_request_webhook_token" in log_text
    assert "downstream_authorization_present=True" in log_text
    assert "TEST_DOWNSTREAM_TOKEN_123456" not in log_text
    assert "handoff-secret-token" not in log_text
    assert payload["status"] == "accepted"
    assert captured["headers"]["Authorization"] == "Bearer handoff-secret-token"


@pytest.mark.asyncio
async def test_handoff_request_reports_upstream_unauthorized(monkeypatch):
    request = httpx.Request("POST", "https://n8n.example/webhook")

    async def fake_post(self, url, json=None, headers=None):
        response = httpx.Response(401, request=request, json={"detail": "unauthorized"})
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr(
        handoff_request_module,
        "get_settings",
        lambda: Settings(
            HANDOFF_REQUEST_WEBHOOK_URL="https://n8n.example/webhook",
            HANDOFF_REQUEST_WEBHOOK_TOKEN="handoff-secret-token",
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await handoff_request(tenant_id="tenant-1", reason="needs_human")

    assert payload["ok"] is False
    assert payload["handoff_requested"] is False
    assert payload["status"] == "upstream_error"
    assert "unauthorized" not in payload["message"].lower()


@pytest.mark.asyncio
async def test_handoff_request_without_any_token_returns_not_configured_and_does_not_call_upstream(monkeypatch):
    called = False

    async def fake_post(self, url, json=None, headers=None):
        nonlocal called
        called = True
        raise AssertionError("upstream call should not happen without n8n auth token")

    monkeypatch.setattr(
        handoff_request_module,
        "get_settings",
        lambda: Settings(
            HANDOFF_REQUEST_WEBHOOK_URL="https://n8n.example/webhook",
            HANDOFF_REQUEST_WEBHOOK_TOKEN="",
            N8N_WEBHOOK_BEARER_TOKEN="",
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await handoff_request(tenant_id="tenant-1", reason="needs_human")

    assert payload["ok"] is False
    assert payload["handoff_requested"] is False
    assert payload["status"] == "not_configured"
    assert called is False
    assert "token" not in payload["message"].lower()
    assert "Bearer" not in str(payload)


@pytest.mark.asyncio
async def test_handoff_request_rejects_missing_reason(monkeypatch):
    monkeypatch.setattr(
        handoff_request_module,
        "get_settings",
        lambda: Settings(HANDOFF_REQUEST_WEBHOOK_URL="https://n8n.example/webhook"),
    )

    payload = await handoff_request(tenant_id="tenant-1", reason=" ")

    assert payload["ok"] is False
    assert payload["handoff_requested"] is False
    assert payload["status"] == "validation_error"


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
        "Authorization": "Bearer secret-token",
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
async def test_services_search_propagates_request_id_from_context(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "found": False,
                "count": 0,
                "items": [],
                "categories": [],
                "message": "No services found",
                "raw_summary": {},
            },
        )

    monkeypatch.setattr(
        services_search_module,
        "get_settings",
        lambda: Settings(
            SERVICES_SEARCH_WEBHOOK_URL="https://n8n.example/webhook",
            N8N_WEBHOOK_BEARER_TOKEN="secret-token",
        ),
    )
    monkeypatch.setattr(appointment_common_module.httpx.AsyncClient, "post", fake_post)

    payload = await services_search(query="whatsapp", ctx=make_context(request_id="req-123"))

    assert captured["headers"]["X-Request-Id"] == "req-123"
    assert payload["ok"] is True
    assert payload["found"] is False


def test_services_search_mcp_call_logs_request_id_and_posts_once(monkeypatch, caplog):
    captured = {"calls": 0}

    async def fake_post(self, url, json=None, headers=None):
        captured["calls"] += 1
        captured["headers"] = headers
        captured["json"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "ok": True,
                "found": False,
                "count": 0,
                "items": [],
                "categories": [],
                "message": "No services found",
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

    settings = Settings(MCP_ALLOWED_HOSTS="localhost,127.0.0.1,*.trycloudflare.com")
    app = create_app(settings)

    with caplog.at_level("INFO"):
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

            call_response = client.post(
                "/mcp",
                headers=MCP_HEADERS,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "services_search", "arguments": {"query": "whatsapp"}},
                },
                follow_redirects=False,
            )
            assert call_response.status_code == 200
            call_payload = decode_sse_json(call_response)
            assert call_payload["result"]["content"][0]["text"]

    assert captured["calls"] == 1
    request_id = captured["headers"]["X-Request-Id"]
    assert isinstance(request_id, str) and request_id
    assert captured["json"]["tool"] == "services_search"

    log_text = "\n".join(record.message for record in caplog.records)
    assert f"mcp_request request_id={request_id}" in log_text
    assert f"services_search request_id={request_id}" in log_text
    assert f"n8n_webhook request_id={request_id}" in log_text


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
