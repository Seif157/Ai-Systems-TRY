"""Immutable deterministic mapping from trusted intents to Step 21 routes."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict

from erp_ai.capabilities.models import Code
from erp_ai.capabilities.registry import CapabilityRegistry
from erp_ai.orchestration import AgentRouteMode, AgentRoutingPolicy
from erp_ai.tools import ReadToolGateway


class TrustedRouteEntry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    intent_code: Code
    route: AgentRoutingPolicy


@dataclass(frozen=True, slots=True, init=False)
class TrustedRouteCatalog:
    entries: tuple[TrustedRouteEntry, ...]
    _by_intent: Mapping[str, AgentRoutingPolicy] = field(repr=False)

    def __init__(self, entries: Iterable[TrustedRouteEntry]) -> None:
        validated = tuple(TrustedRouteEntry.model_validate(item, strict=True) for item in entries)
        codes = tuple(item.intent_code for item in validated)
        if len(set(codes)) != len(codes):
            raise ValueError("duplicate trusted intent code")
        ordered = tuple(sorted(validated, key=lambda item: item.intent_code))
        object.__setattr__(self, "entries", ordered)
        object.__setattr__(
            self, "_by_intent", MappingProxyType({item.intent_code: item.route for item in ordered})
        )

    def validate_startup(self, registry: CapabilityRegistry, gateway: ReadToolGateway) -> None:
        descriptors = {
            tool.tool_name: tool for manifest in registry.manifests for tool in manifest.tools
        }
        installed = {handler.tool_name: handler.version for handler in gateway.handlers}
        for entry in self.entries:
            route = entry.route
            if route.mode is AgentRouteMode.GENERAL_ONLY:
                continue
            descriptor = descriptors.get(route.tool_name or "")
            if (
                descriptor is None
                or descriptor.operation != "read"
                or descriptor.version != route.version
                or installed.get(route.tool_name or "") != route.version
            ):
                raise ValueError("trusted route references an unavailable read tool")

    def resolve(self, intent_code: str) -> AgentRoutingPolicy:
        route = self._by_intent.get(intent_code)
        if route is None:
            raise KeyError("trusted intent has no configured route")
        return route
