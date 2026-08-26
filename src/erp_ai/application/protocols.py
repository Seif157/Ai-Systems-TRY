"""Mandatory provider-neutral application dependencies."""

from datetime import datetime
from typing import Protocol, runtime_checkable

from erp_ai.application.audit import ApplicationAuditEvent
from erp_ai.application.models import (
    AuthorizationSnapshotDecision,
    TrustedRequestReference,
    TrustedResolution,
)
from erp_ai.context import TrustedRequestContext


@runtime_checkable
class TrustedRequestResolver(Protocol):
    async def resolve(self, reference: TrustedRequestReference) -> TrustedResolution: ...


@runtime_checkable
class AuthorizationSnapshotVerifier(Protocol):
    async def verify(self, context: TrustedRequestContext) -> AuthorizationSnapshotDecision: ...


@runtime_checkable
class ApplicationAuditSink(Protocol):
    async def record(self, event: ApplicationAuditEvent) -> None: ...


@runtime_checkable
class TrustedClock(Protocol):
    def now(self) -> datetime: ...
