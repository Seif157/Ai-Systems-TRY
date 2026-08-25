import base64

import pytest
from pydantic import SecretStr, ValidationError

from erp_ai.infrastructure.postgres_erp import (
    ErpCursorKey,
    ErpCursorKeyring,
    ErpDatabaseRouteConfig,
    StaticErpDatabaseConfig,
)


def key(key_id: str = "active", byte: bytes = b"a") -> ErpCursorKey:
    return ErpCursorKey(
        key_id=key_id,
        key_base64=SecretStr(base64.b64encode(byte * 32).decode()),
    )


def route(customer: str = "customer_a", database: str = "erp_a") -> ErpDatabaseRouteConfig:
    return ErpDatabaseRouteConfig(
        customer_environment_id=customer,
        reader_dsn=SecretStr("postgresql://placeholder"),
        expected_database_name=database,
    )


def test_cursor_keys_are_secret_immutable_and_validated() -> None:
    item = key()
    assert item.decoded() == b"a" * 32
    assert "postgresql" not in repr(route())
    assert "YWFh" not in repr(item)
    with pytest.raises(ValidationError, match="valid base64"):
        ErpCursorKey(key_id="bad", key_base64=SecretStr("***"))
    with pytest.raises(ValidationError, match="at least 32"):
        ErpCursorKey(key_id="short", key_base64=SecretStr(base64.b64encode(b"short").decode()))


def test_keyring_and_routes_are_normalized_and_unique() -> None:
    ring = ErpCursorKeyring(active=key(), previous=[key("old", b"b")])
    config = StaticErpDatabaseConfig(routes=[route()], cursor_keyring=ring)
    assert isinstance(ring.previous, tuple) and isinstance(config.routes, tuple)
    with pytest.raises(ValidationError, match="key IDs"):
        ErpCursorKeyring(active=key(), previous=(key(),))
    with pytest.raises(ValidationError, match="duplicate ERP customer"):
        StaticErpDatabaseConfig(routes=(route(), route(database="erp_b")), cursor_keyring=ring)
    with pytest.raises(ValidationError, match="separate databases"):
        StaticErpDatabaseConfig(routes=(route(), route("customer_b", "erp_a")), cursor_keyring=ring)
    with pytest.raises(ValidationError, match="minimum pool"):
        StaticErpDatabaseConfig(
            routes=(route(),), cursor_keyring=ring, minimum_pool_size=2, maximum_pool_size=1
        )
