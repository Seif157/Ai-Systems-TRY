"""Minimal audit contract for the outer application boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type ApplicationStage = Literal[
    "validation", "resolution", "authorization", "routing", "orchestration"
]


class ApplicationAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: str
    stage: ApplicationStage
    outcome: Literal["success", "failure"]
    internal_reason: str = Field(repr=False)
