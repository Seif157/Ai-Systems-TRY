"""Entitlement and authorization filtering for registered capabilities."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from erp_ai.capabilities.models import ToolDescriptor
from erp_ai.capabilities.registry import CapabilityRegistry
from erp_ai.context import TrustedRequestContext

type DenialReason = Literal[
    "required_module_disabled",
    "required_permission_missing",
    "required_role_missing",
    "purpose_not_allowed",
    "employee_context_required",
    "command_disabled_read_only",
]


class ModelToolDescriptor(BaseModel):
    """Authorized tool metadata safe to place in model-facing configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tool_name: str
    version: str
    operation: Literal["read", "command"]


class ModelCapability(BaseModel):
    """Authorized capability and its filtered model-facing tools."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    capability_code: str
    version: str
    tools: tuple[ModelToolDescriptor, ...]


class AccessDenial(BaseModel):
    """Internal server-side explanation that must never be sent to the model."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    capability_code: str
    tool_name: str | None
    reason: DenialReason


class CapabilityAccessDecision(BaseModel):
    """Immutable result separating model-facing output from internal denials."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_capabilities: tuple[ModelCapability, ...]
    denials: tuple[AccessDenial, ...]


def _model_tool(tool: ToolDescriptor) -> ModelToolDescriptor:
    return ModelToolDescriptor(
        tool_name=tool.tool_name,
        version=tool.version,
        operation=tool.operation,
    )


def evaluate_capability_access(
    registry: CapabilityRegistry,
    context: TrustedRequestContext,
    *,
    read_only_mode: bool = True,
) -> CapabilityAccessDecision:
    """Filter a registry using only trusted context authorization collections."""

    enabled_modules = frozenset(context.enabled_modules)
    permissions = frozenset(context.permission_codes)
    roles = frozenset(context.roles)
    available: list[ModelCapability] = []
    denials: list[AccessDenial] = []

    for manifest in registry.manifests:
        if not set(manifest.required_modules).issubset(enabled_modules):
            denials.append(
                AccessDenial(
                    capability_code=manifest.capability_code,
                    tool_name=None,
                    reason="required_module_disabled",
                )
            )
            continue

        tools: list[ModelToolDescriptor] = []
        for tool in manifest.tools:
            reason: DenialReason
            if read_only_mode and tool.operation == "command":
                reason = "command_disabled_read_only"
            elif tool.requires_employee_context and context.employee_id is None:
                reason = "employee_context_required"
            elif not set(tool.required_permissions_all).issubset(permissions):
                reason = "required_permission_missing"
            elif tool.required_roles_any and roles.isdisjoint(tool.required_roles_any):
                reason = "required_role_missing"
            elif context.purpose not in tool.allowed_purposes:
                reason = "purpose_not_allowed"
            else:
                tools.append(_model_tool(tool))
                continue

            denials.append(
                AccessDenial(
                    capability_code=manifest.capability_code,
                    tool_name=tool.tool_name,
                    reason=reason,
                )
            )

        available.append(
            ModelCapability(
                capability_code=manifest.capability_code,
                version=manifest.version,
                tools=tuple(tools),
            )
        )

    return CapabilityAccessDecision(
        model_capabilities=tuple(available),
        denials=tuple(denials),
    )
