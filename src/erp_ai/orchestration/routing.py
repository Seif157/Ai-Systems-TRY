"""Trusted server-owned routing decisions for bounded agent execution."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from erp_ai.capabilities.models import Code, Version


class AgentRouteMode(str, Enum):
    GENERAL_ONLY = "general_only"
    EXACT_READ_THEN_FINAL = "exact_read_then_final"


class AgentRoutingPolicy(BaseModel):
    """Explicit route selected outside public and model-controlled data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    mode: AgentRouteMode
    tool_name: Code | None = Field(default=None, repr=False)
    version: Version | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_route(self) -> "AgentRoutingPolicy":
        exact = self.mode is AgentRouteMode.EXACT_READ_THEN_FINAL
        has_both = self.tool_name is not None and self.version is not None
        has_either = self.tool_name is not None or self.version is not None
        if (exact and not has_both) or (not exact and has_either):
            raise ValueError("route selection is inconsistent")
        return self
