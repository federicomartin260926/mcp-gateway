from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "mcp-gateway"
    service_version: str = Field(default="0.1.0", alias="SERVICE_VERSION")
    app_env: str = Field(default="dev", alias="APP_ENV")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8010, alias="PORT")
    log_level: str = Field(default="info", alias="LOG_LEVEL")
    mcp_auth_token: str = Field(default="", alias="MCP_AUTH_TOKEN")
    mcp_allowed_hosts: str = Field(default="", alias="MCP_ALLOWED_HOSTS")
    contact_context_webhook_url: str = Field(default="", alias="CONTACT_CONTEXT_WEBHOOK_URL")
    n8n_webhook_bearer_token: str = Field(default="", alias="N8N_WEBHOOK_BEARER_TOKEN")
    contact_context_timeout_seconds: float = Field(default=5, alias="CONTACT_CONTEXT_TIMEOUT_SECONDS")
    appointment_availability_webhook_url: str = Field(default="", alias="APPOINTMENT_AVAILABILITY_WEBHOOK_URL")
    appointment_availability_timeout_seconds: float = Field(default=8, alias="APPOINTMENT_AVAILABILITY_TIMEOUT_SECONDS")
    appointment_events_webhook_url: str = Field(default="", alias="APPOINTMENT_EVENTS_WEBHOOK_URL")
    appointment_events_timeout_seconds: float = Field(default=8, alias="APPOINTMENT_EVENTS_TIMEOUT_SECONDS")
    services_search_webhook_url: str = Field(default="", alias="SERVICES_SEARCH_WEBHOOK_URL")
    services_search_timeout_seconds: float = Field(default=8, alias="SERVICES_SEARCH_TIMEOUT_SECONDS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
