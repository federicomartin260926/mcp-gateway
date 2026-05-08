from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1)


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str
    echoed: bool = True


def echo(message: str) -> dict[str, Any]:
    """Return the input message unchanged."""
    payload = EchoInput(message=message)
    return EchoOutput(message=payload.message, echoed=True).model_dump()
