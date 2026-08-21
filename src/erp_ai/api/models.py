"""Models accepted from untrusted public API clients."""

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class PublicChatRequest(BaseModel):
    """A public chat request containing no trusted identity or entitlement fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    message: Message
    stream: bool = Field(default=False)
    preferred_response_language: str | None = None

    @field_validator("preferred_response_language", mode="before")
    @classmethod
    def normalize_preferred_response_language(cls, value: object) -> object:
        """Normalize a response preference without treating it as authoritative context."""

        if value is None or not isinstance(value, str):
            return value
        parts = value.strip().split("-")
        normalized = "-".join([parts[0].lower(), *(part.upper() for part in parts[1:])])
        if not _LANGUAGE_PATTERN.fullmatch(normalized):
            raise ValueError("preferred response language must be a valid language tag")
        return normalized
