"""Private immutable ingress authentication models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from erp_ai.context.models import Identifier


class TrustedIngressAuthenticationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    request_id: Identifier = Field(repr=False)
    method: Literal["POST"]
    route_path: Literal["/v1/chat"]
    body_digest_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$", repr=False
    )
    bearer_assertion: SecretStr = Field(min_length=1, repr=False)
