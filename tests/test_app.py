from __future__ import annotations

import json
import importlib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.tools.contact_context import contact_context
from app.tools.contact_context_mock import contact_context_mock
from app.tools.echo import echo

contact_context_module = importlib.import_module("app.tools.contact_context")

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
    monkeypatch.setattr(contact_context_module.httpx.AsyncClient, "post", fake_post)

    payload = await contact_context(
        phone=" +34999999999 ",
        email="null",
        name="  Cliente Demo  ",
        tenant_id=" tenant-1 ",
        channel=" whatsapp ",
    )

    assert captured["url"] == "https://n8n.example/webhook"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret-token",
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
