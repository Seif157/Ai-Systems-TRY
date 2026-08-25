import base64

import pytest
from pydantic import SecretStr

from erp_ai.infrastructure.postgres_erp import (
    ErpCursorKey,
    ErpCursorKeyring,
    ErpDatabaseRouteConfig,
    PostgresHrCoreReadProvider,
    PostgresLeaveReadProvider,
    SignedLeaveRequestCursor,
    StaticErpDatabaseConfig,
    StaticErpDatabaseRouter,
)
from erp_ai.infrastructure.postgres_erp.errors import ErpReadUnavailable
from erp_ai.infrastructure.postgres_erp.providers import (
    _BALANCES_SQL,
    _DETAIL_SQL,
    _HISTORY_SQL,
    _LIST_SQL,
    _PROFILE_SQL,
    _ReadTransaction,
)


def config() -> StaticErpDatabaseConfig:
    key = ErpCursorKey(
        key_id="active",
        key_base64=SecretStr(base64.b64encode(b"a" * 32).decode()),
    )
    return StaticErpDatabaseConfig(
        routes=(
            ErpDatabaseRouteConfig(
                customer_environment_id="customer_a",
                reader_dsn=SecretStr("postgresql://placeholder"),
                expected_database_name="erp_a",
            ),
        ),
        cursor_keyring=ErpCursorKeyring(active=key),
    )


def test_router_is_explicit_lifecycle_static_and_has_no_fallback() -> None:
    router = StaticErpDatabaseRouter(config())
    assert router.config.routes[0].expected_database_name == "erp_a"
    with pytest.raises(ErpReadUnavailable, match="router is unavailable"):
        router.pool("customer_a")
    router._started = True
    router._pools["customer_a"] = object()  # type: ignore[assignment]
    assert router.pool("customer_a") is router._pools["customer_a"]
    with pytest.raises(ErpReadUnavailable, match="route is unavailable"):
        router.pool("unknown")


def test_providers_require_explicit_router_and_cursor_boundaries() -> None:
    router = StaticErpDatabaseRouter(config())
    cursor = SignedLeaveRequestCursor(router.config.cursor_keyring)
    assert PostgresHrCoreReadProvider(router)._router is router
    assert PostgresLeaveReadProvider(router, cursor)._cursor is cursor
    transaction = _ReadTransaction(5000, 2000, 10000)
    assert transaction.statement_timeout_ms == 5000


def test_business_sql_is_static_view_only_read_only_and_parameterized() -> None:
    statements = (_PROFILE_SQL, _BALANCES_SQL, _LIST_SQL, _DETAIL_SQL, _HISTORY_SQL)
    for statement in statements:
        normalized = " ".join(statement.lower().split())
        assert "ai_read." in normalized
        assert "select *" not in normalized
        assert "%s" in normalized
        assert not any(
            token in normalized
            for token in (
                " insert ",
                " update ",
                " delete ",
                " truncate ",
                " create ",
                " alter ",
                " drop ",
                " offset ",
            )
        )
    assert "order by submitted_at desc,request_id asc" in " ".join(_LIST_SQL.lower().split())
    assert "order by changed_at asc,history_id asc" in " ".join(_HISTORY_SQL.lower().split())
    assert "available_days" in _BALANCES_SQL and "+" not in _BALANCES_SQL
    assert "created_at" not in _LIST_SQL
    assert "legal_entity_id=any(%s::uuid[])" in "".join(_PROFILE_SQL.lower().split())
