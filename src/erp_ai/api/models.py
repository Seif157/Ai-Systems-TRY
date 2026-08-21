"""Models accepted from untrusted public API clients."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]


class ChatRequest(BaseModel):
    """A public chat request containing no trusted identity or entitlement fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    message: Message
    stream: bool = Field(default=False)
