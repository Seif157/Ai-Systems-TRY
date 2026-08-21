"""Boundary for context supplied by authenticated, trusted server services."""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from erp_ai.context.models import TrustedRequestContext


@runtime_checkable
class TrustedContextSource(Protocol):
    """Adapter implemented by a trusted authentication/context integration."""

    def load_context(self) -> Mapping[str, object]: ...


def resolve_trusted_context(source: TrustedContextSource) -> TrustedRequestContext:
    """Validate and freeze claims loaded from a trusted server-side adapter."""

    return TrustedRequestContext.model_validate(dict(source.load_context()), strict=True)
