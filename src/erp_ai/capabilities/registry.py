"""Immutable in-memory capability registry."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from erp_ai.capabilities.models import CapabilityManifest, ToolDescriptor


@dataclass(frozen=True, slots=True, init=False)
class CapabilityRegistry:
    """Deterministic validated snapshot with no loading or external access behavior."""

    manifests: tuple[CapabilityManifest, ...]
    _by_code: Mapping[str, CapabilityManifest] = field(repr=False)
    _tools_by_name: Mapping[str, ToolDescriptor] = field(repr=False)

    def __init__(self, manifests: Iterable[CapabilityManifest]) -> None:
        entries = tuple(manifests)
        if not all(isinstance(manifest, CapabilityManifest) for manifest in entries):
            raise TypeError("registry entries must be validated CapabilityManifest instances")
        ordered = tuple(sorted(entries, key=lambda manifest: manifest.capability_code))

        by_code: dict[str, CapabilityManifest] = {}
        tools_by_name: dict[str, ToolDescriptor] = {}
        for manifest in ordered:
            if manifest.capability_code in by_code:
                raise ValueError(f"duplicate capability code: {manifest.capability_code}")
            by_code[manifest.capability_code] = manifest

            for tool in manifest.tools:
                if tool.tool_name in tools_by_name:
                    raise ValueError(f"duplicate tool name: {tool.tool_name}")
                tools_by_name[tool.tool_name] = tool

        object.__setattr__(self, "manifests", ordered)
        object.__setattr__(self, "_by_code", MappingProxyType(by_code))
        object.__setattr__(self, "_tools_by_name", MappingProxyType(tools_by_name))

    def get(self, capability_code: str) -> CapabilityManifest | None:
        """Return a registered manifest by its already-normalized code."""

        return self._by_code.get(capability_code)
