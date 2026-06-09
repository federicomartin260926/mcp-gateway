from __future__ import annotations

import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route

from app.settings import Settings, get_settings
from app.tools import (
    appointment_booking_invitation,
    appointment_cancel,
    appointment_availability,
    appointment_events,
    appointment_confirm,
    appointment_reschedule,
    build_available_tools,
    debug_auth_context,
    contact_context,
    contact_context_mock,
    echo,
    services_search,
    handoff_request,
    crm_contact_submit,
)

logger = logging.getLogger(__name__)


def parse_allowed_hosts(raw_value: str) -> list[str]:
    return [host.strip().lower() for host in raw_value.split(",") if host.strip()]


def normalize_host(host: str | None) -> str:
    if not host:
        return ""

    host = host.strip().lower()
    if host.startswith("[") and "]" in host:
        return host

    if host.count(":") == 1:
        return host.split(":", 1)[0]

    return host


def _authorization_summary(authorization: str | None) -> tuple[bool, str | None]:
    if authorization is None:
        return False, None

    normalized = authorization.strip()
    if normalized == "":
        return False, None

    parts = normalized.split(None, 1)
    if len(parts) >= 2 and parts[0].lower() in {"bearer", "basic", "digest"}:
        return True, parts[0].capitalize()

    return True, None


def host_is_allowed(host: str | None, allowed_hosts: list[str]) -> bool:
    if not allowed_hosts:
        return True

    normalized_host = normalize_host(host)
    if not normalized_host:
        return False

    for allowed in allowed_hosts:
        if allowed == normalized_host:
            return True

        if allowed.startswith("*."):
            suffix = allowed[1:]
            if normalized_host.endswith(suffix) and normalized_host != suffix[1:]:
                return True

    return False


def build_mcp_server(enable_debug_tools: bool = False) -> FastMCP:
    mcp = FastMCP(
        "mcp-gateway",
        stateless_http=True,
        json_response=True,
        # Host validation is enforced in FastAPI middleware so it can be controlled by env.
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    mcp.tool()(echo)
    mcp.tool()(contact_context_mock)
    mcp.tool()(contact_context)
    mcp.tool()(appointment_availability)
    mcp.tool()(appointment_events)
    mcp.tool()(appointment_confirm)
    mcp.tool()(appointment_reschedule)
    mcp.tool()(appointment_cancel)
    mcp.tool()(appointment_booking_invitation)
    mcp.tool()(services_search)
    mcp.tool()(handoff_request)
    mcp.tool()(crm_contact_submit)
    if enable_debug_tools:
        mcp.tool()(debug_auth_context)
    return mcp


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    allowed_hosts = parse_allowed_hosts(app_settings.mcp_allowed_hosts)
    auth_token = app_settings.mcp_auth_token.strip()
    mcp_server = build_mcp_server(app_settings.enable_debug_tools)
    available_tools = build_available_tools(app_settings.enable_debug_tools)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_server.session_manager.run())
            yield

    app = FastAPI(
        title=app_settings.service_name,
        version=app_settings.service_version,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def mcp_request_middleware(request: Request, call_next):
        mcp_path = request.url.path.startswith("/mcp")
        response = None

        if mcp_path:
            if not host_is_allowed(request.headers.get("host"), allowed_hosts):
                response = JSONResponse({"detail": "Invalid Host header"}, status_code=421)

            elif auth_token != "":
                authorization = request.headers.get("Authorization", "")
                expected = f"Bearer {auth_token}"
                if authorization != expected:
                    response = JSONResponse({"detail": "Unauthorized"}, status_code=401)

        if response is None:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("Unhandled error while processing request %s %s", request.method, request.url.path)
                raise

        try:
            return response
        finally:
            if mcp_path:
                authorization = request.headers.get("Authorization", "")
                has_authorization, authorization_scheme = _authorization_summary(authorization)
                logger.info(
                    "mcp_request method=%s path=%s status_code=%s user_agent=%s has_authorization=%s authorization_scheme=%s",
                    request.method,
                    request.url.path,
                    response.status_code if response is not None else 500,
                    request.headers.get("user-agent") or "-",
                    has_authorization,
                    authorization_scheme or "-",
                )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": app_settings.service_name}

    @app.get("/info")
    async def info() -> dict[str, object]:
        return {
            "service": app_settings.service_name,
            "version": app_settings.service_version,
            "environment": app_settings.app_env,
            "available_tools": available_tools,
            "mcp_endpoint": "/mcp",
            "auth_required": app_settings.mcp_auth_token.strip() != "",
        }

    # Register /mcp as an exact ASGI route to avoid Starlette mount redirects.
    app.router.routes.append(Route("/mcp", mcp_server.streamable_http_app()))

    return app


app = create_app()
