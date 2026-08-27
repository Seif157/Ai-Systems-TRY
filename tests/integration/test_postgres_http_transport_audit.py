import httpx
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from erp_ai.api import PublicChatRequest
from erp_ai.application import TrustedRequestReference
from erp_ai.infrastructure.postgres_audit import (
    PostgresApplicationAuditSink,
    StaticAuditDatabaseRouter,
)
from erp_ai.orchestration import PublicChatSuccess
from erp_ai.transport.http import InternalHttpTransportConfig, create_internal_http_app
from erp_ai.transport.http.models import TrustedIngressAuthenticationRequest
from tests.integration.test_postgres_audit_storage import _prepare, _required, _run

pytestmark = pytest.mark.postgres


class SyntheticAuthenticator:
    async def authenticate(
        self, request: TrustedIngressAuthenticationRequest
    ) -> TrustedRequestReference:
        return TrustedRequestReference(
            request_id=request.request_id,
            resolver_reference="cnJycnJycnJycnJycnJycnJycnJycnJycnJycnJycnI",
        )


class SyntheticApplication:
    async def execute(
        self, request: PublicChatRequest, reference: TrustedRequestReference
    ) -> PublicChatSuccess:
        return PublicChatSuccess(answer="Synthetic", response_language="en", citations=())


class SyntheticIds:
    def create(self) -> str:
        return "123e4567-e89b-42d3-a456-426614174000"


class RouterLifecycle:
    def __init__(self, router: StaticAuditDatabaseRouter) -> None:
        self.router = router

    async def startup(self) -> None:
        await self.router.open()

    async def shutdown(self) -> None:
        await self.router.close()


class ClosedRouterLifecycle:
    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


async def _exercise_transport_audit() -> None:
    admin_dsn = _required()
    config, databases = await _prepare(admin_dsn)
    router = StaticAuditDatabaseRouter(config)
    app = create_internal_http_app(
        config=InternalHttpTransportConfig(allowed_hosts=("erp.internal",)),
        authenticator=SyntheticAuthenticator(),
        request_id_factory=SyntheticIds(),
        application=SyntheticApplication(),
        application_audit_sink=PostgresApplicationAuditSink(router, config),
        lifecycle=RouterLifecycle(router),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://erp.internal"
        ) as client,
    ):
        response = await client.post(
            "/v1/chat",
            headers={"Content-Type": "application/json"},
            content=b'{"message":"synthetic"}',
        )
    assert response.status_code == 401
    assert set(response.json()) == {"safe_error_code", "safe_message"}

    counts: list[tuple[int, bool]] = []
    for index, database in enumerate(databases):
        values = conninfo_to_dict(admin_dsn)
        values["dbname"] = database
        async with await psycopg.AsyncConnection.connect(make_conninfo(**values)) as connection:
            table = await (
                await connection.execute("SELECT to_regclass('erp_ai_audit.application_events')")
            ).fetchone()
            count = 0
            if table and table[0] is not None:
                rows = await (
                    await connection.execute(
                        "SELECT request_id,stage,outcome,internal_reason "
                        "FROM erp_ai_audit.application_events"
                    )
                ).fetchall()
                assert rows == [
                    (
                        "123e4567-e89b-42d3-a456-426614174000",
                        "validation",
                        "failure",
                        "ingress_authentication_rejected",
                    )
                ]
                count = len(rows)
            if index > 0:
                agent_count = await (
                    await connection.execute("SELECT count(*) FROM erp_ai_audit.agent_events")
                ).fetchone()
                tool_count = await (
                    await connection.execute("SELECT count(*) FROM erp_ai_audit.tool_events")
                ).fetchone()
                assert agent_count == tool_count == (0,)
            counts.append((count, index == 0))
    assert counts == [(1, True), (0, False), (0, False)]

    unavailable_router = StaticAuditDatabaseRouter(config)
    unavailable = create_internal_http_app(
        config=InternalHttpTransportConfig(allowed_hosts=("erp.internal",)),
        authenticator=SyntheticAuthenticator(),
        request_id_factory=SyntheticIds(),
        application=SyntheticApplication(),
        application_audit_sink=PostgresApplicationAuditSink(unavailable_router, config),
        lifecycle=ClosedRouterLifecycle(),
    )
    async with (
        unavailable.router.lifespan_context(unavailable),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=unavailable), base_url="https://erp.internal"
        ) as client,
    ):
        failed = await client.post(
            "/v1/chat",
            headers={"Content-Type": "application/json"},
            content=b'{"message":"withheld_marker"}',
        )
    assert failed.status_code == 503
    assert failed.json()["safe_error_code"] == "AUDIT_UNAVAILABLE"
    assert "withheld_marker" not in failed.text


def test_postgres_pre_application_audit_is_control_only() -> None:
    _run(_exercise_transport_audit())
