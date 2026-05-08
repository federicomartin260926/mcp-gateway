from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContactContextMockInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    email: str | None = None


class ContactContextMockOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    found: bool = True
    contact: dict[str, Any] = Field(default_factory=dict)


def contact_context_mock(phone: str | None = None, email: str | None = None) -> dict[str, Any]:
    """Return a mock contact context payload."""
    ContactContextMockInput(phone=phone, email=email)
    return ContactContextMockOutput(
        found=True,
        contact={
            "name": "Cliente Demo",
            "status": "lead",
            "stage": "new",
            "last_interaction": "mock",
        },
    ).model_dump()
