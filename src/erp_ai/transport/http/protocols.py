"""Mandatory provider-neutral HTTP transport dependencies."""

from typing import Protocol, runtime_checkable

from erp_ai.api import PublicChatRequest
from erp_ai.application import ApplicationAuditSink, TrustedRequestReference
from erp_ai.orchestration.models import PublicChatResult

from .models import TrustedIngressAuthenticationRequest


@runtime_checkable
class TrustedIngressAuthenticator(Protocol):
    async def authenticate(
        self, request: TrustedIngressAuthenticationRequest
    ) -> TrustedRequestReference: ...


@runtime_checkable
class RequestIdFactory(Protocol):
    def create(self) -> str: ...


@runtime_checkable
class TrustedApplicationExecutor(Protocol):
    async def execute(
        self, request: PublicChatRequest, reference: TrustedRequestReference
    ) -> PublicChatResult: ...


@runtime_checkable
class TransportLifecycle(Protocol):
    async def startup(self) -> None: ...

    async def shutdown(self) -> None: ...


class TransportDependencies(Protocol):
    authenticator: TrustedIngressAuthenticator
    request_id_factory: RequestIdFactory
    application: TrustedApplicationExecutor
    application_audit_sink: ApplicationAuditSink
    lifecycle: TransportLifecycle
