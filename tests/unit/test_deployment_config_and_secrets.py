import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from erp_ai.deployment.config import (
    DEPLOYMENT_CONFIG_CONTRACT_DIGEST,
    DEPLOYMENT_CONFIG_CONTRACT_VERSION,
    MAXIMUM_CONFIG_BYTES,
    ProductionDeploymentConfig,
    canonical_deployment_config_contract_bytes,
    load_production_config,
)
from erp_ai.deployment.secrets import FileSecretProvider


def payload() -> dict[str, object]:
    return {
        "contract_version": "1.0.0",
        "deployment_version": "synthetic-v1",
        "server": {
            "bind_address": "0.0.0.0",
            "port": 8080,
            "workers": 1,
            "concurrency_limit": 32,
            "backlog": 64,
            "keep_alive_seconds": 5,
            "startup_timeout_seconds": 60,
            "graceful_shutdown_seconds": 30,
        },
        "runtime_catalog_reference": "config/catalog.json",
        "erp_trust_config_reference": "config/trust.json",
        "laravel_config_reference": "config/laravel.json",
        "audit_control_dsn_reference": "postgres/control.dsn",
        "customer_routes": [
            {
                "customer_environment_id": "synthetic-customer",
                "audit_runtime_dsn_reference": "postgres/audit.dsn",
                "knowledge_runtime_dsn_reference": "postgres/knowledge.dsn",
                "openai_credential_reference": "openai/key",
                "openai_project_route_id": "synthetic-project-route",
            }
        ],
    }


def test_config_contract_digest_and_strict_immutable_parse(tmp_path: Path) -> None:
    raw = canonical_deployment_config_contract_bytes()
    assert DEPLOYMENT_CONFIG_CONTRACT_VERSION == "1.0.0"
    assert hashlib.sha256(raw).hexdigest() == DEPLOYMENT_CONFIG_CONTRACT_DIGEST
    assert not raw.endswith(b"\n")
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(payload(), separators=(",", ":")), encoding="utf-8")
    config = load_production_config(path)
    assert config.server.port == 8080 and config.server.workers == 1
    assert "synthetic-customer" not in repr(config)
    with pytest.raises(ValidationError):
        config.server.port = 9000  # type: ignore[misc]


@pytest.mark.parametrize(
    "raw",
    (
        b'{"contract_version":"1.0.0","contract_version":"1.0.0"}',
        b"\xff",
        b'{"contract_version":NaN}',
        b"[]",
        b"",
    ),
)
def test_invalid_config_is_generic(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "runtime.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="invalid deployment configuration") as error:
        load_production_config(path)
    marker = raw.decode(errors="ignore")
    if marker:
        assert marker not in repr(error.value)


def test_config_size_depth_unknown_coercion_and_duplicates_fail(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_bytes(b"x" * (MAXIMUM_CONFIG_BYTES + 1))
    with pytest.raises(ValueError):
        load_production_config(path)
    deep: object = "x"
    for _ in range(14):
        deep = [deep]
    path.write_text(json.dumps(deep), encoding="utf-8")
    with pytest.raises(ValueError):
        load_production_config(path)
    for changed in (
        {**payload(), "unknown": True},
        {**payload(), "server": {**payload()["server"], "port": "8080"}},  # type: ignore[dict-item]
        {**payload(), "customer_routes": payload()["customer_routes"] * 2},  # type: ignore[operator]
    ):
        with pytest.raises(ValidationError):
            ProductionDeploymentConfig.model_validate(changed, strict=True)


def test_secret_boundary_text_binary_and_path_rules(tmp_path: Path) -> None:
    root = tmp_path / "secrets"
    root.mkdir()
    (root / "token").write_bytes(b"synthetic-secret\r\n")
    provider = FileSecretProvider(root)
    secret = provider.read_text("token")
    assert secret.get_secret_value() == "synthetic-secret"
    assert "synthetic-secret" not in repr(secret) and str(root) not in repr(provider)
    assert provider.read_bytes("token") == b"synthetic-secret\r\n"
    for reference in ("../token", "/absolute", "missing"):
        with pytest.raises(ValueError, match="secret is unavailable") as error:
            provider.read_text(reference)  # type: ignore[arg-type]
        assert str(root) not in str(error.value)


@pytest.mark.parametrize("raw", (b"", b"nul\x00", b"internal\nnewline", b"\xff"))
def test_secret_invalid_values_are_contained(tmp_path: Path, raw: bytes) -> None:
    root = tmp_path / "secrets"
    root.mkdir()
    (root / "bad").write_bytes(raw)
    with pytest.raises(ValueError, match="secret is unavailable"):
        FileSecretProvider(root).read_text("bad")


def test_projected_volume_symlink_stays_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "secrets"
    data = root / "..data-version"
    root.mkdir()
    data.mkdir()
    (data / "token").write_text("safe", encoding="utf-8")
    try:
        (root / "..data").symlink_to(data, target_is_directory=True)
        (root / "token").symlink_to(root / "..data" / "token")
    except OSError:
        pytest.skip("symlink creation is unavailable")
    assert FileSecretProvider(root).read_text("token").get_secret_value() == "safe"


def test_secret_file_type_and_bounded_read_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "secrets"
    root.mkdir()
    directory = root / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="secret is unavailable"):
        FileSecretProvider(root).read_bytes("directory")

    token = root / "token"
    token.write_bytes(b"safe")
    checks = iter((True, False))
    monkeypatch.setattr("erp_ai.deployment.secrets.stat.S_ISREG", lambda mode: next(checks))
    with pytest.raises(ValueError, match="secret is unavailable"):
        FileSecretProvider(root).read_bytes("token")


def test_secret_lf_termination_and_binary_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "secrets"
    root.mkdir()
    token = root / "token"
    token.write_bytes(b"safe\n")
    provider = FileSecretProvider(root)
    assert provider.read_text("token").get_secret_value() == "safe"
    monkeypatch.setattr("erp_ai.deployment.secrets.MAXIMUM_BINARY_SECRET_BYTES", 2)
    with pytest.raises(ValueError, match="secret is unavailable"):
        provider.read_bytes("token")
