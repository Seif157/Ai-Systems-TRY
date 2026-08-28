from __future__ import annotations

import asyncio
import json
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from erp_ai.context import TrustedRequestContext
from erp_ai.infrastructure.laravel_erp import (
    LARAVEL_ERP_READ_CONTRACT_DIGEST,
    LaravelErpReadClient,
    LaravelErpReadConfig,
    LaravelErpReadUnavailable,
    LaravelHrCoreReadProvider,
    LaravelLeaveReadProvider,
)
from erp_ai.infrastructure.laravel_erp.contracts import (
    BALANCES_PATH,
    CONTRACT_PATH,
    PROFILE_PATH,
    REQUEST_DETAIL_PATH,
    REQUESTS_PATH,
)


def _certificate(
    *,
    subject: str,
    key: rsa.RSAPrivateKey,
    issuer: x509.Name,
    issuer_key: rsa.RSAPrivateKey,
    ca: bool = False,
    server: bool = False,
) -> x509.Certificate:
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if server:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        ).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    elif not ca:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        )
    return builder.sign(issuer_key, hashes.SHA256())


def _write(path: Path, value: bytes) -> None:
    path.write_bytes(value)


def _pem_certificate(value: x509.Certificate) -> bytes:
    return value.public_bytes(serialization.Encoding.PEM)


def _pem_key(value: rsa.RSAPrivateKey) -> bytes:
    return value.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _contexts(
    root: Path,
) -> tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, ssl.SSLContext]:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-test-ca")])
    ca = _certificate(
        subject="synthetic-test-ca", key=ca_key, issuer=ca_name, issuer_key=ca_key, ca=True
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = _certificate(
        subject="localhost", key=server_key, issuer=ca.subject, issuer_key=ca_key, server=True
    )
    client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = _certificate(
        subject="synthetic-ai-client", key=client_key, issuer=ca.subject, issuer_key=ca_key
    )
    paths = {
        name: root / name
        for name in ("ca.pem", "server.pem", "server.key", "client.pem", "client.key")
    }
    _write(paths["ca.pem"], _pem_certificate(ca))
    _write(paths["server.pem"], _pem_certificate(server))
    _write(paths["server.key"], _pem_key(server_key))
    _write(paths["client.pem"], _pem_certificate(client))
    _write(paths["client.key"], _pem_key(client_key))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(paths["server.pem"], paths["server.key"])
    server_context.load_verify_locations(paths["ca.pem"])
    server_context.verify_mode = ssl.CERT_REQUIRED
    client_context = ssl.create_default_context(cafile=paths["ca.pem"])
    client_context.minimum_version = ssl.TLSVersion.TLSv1_2
    client_context.load_cert_chain(paths["client.pem"], paths["client.key"])
    no_client_context = ssl.create_default_context(cafile=paths["ca.pem"])
    no_client_context.minimum_version = ssl.TLSVersion.TLSv1_2
    untrusted_context = ssl.create_default_context()
    untrusted_context.minimum_version = ssl.TLSVersion.TLSv1_2
    untrusted_context.load_cert_chain(paths["client.pem"], paths["client.key"])
    return server_context, client_context, no_client_context, untrusted_context


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, bytes]:
    header = await reader.readuntil(b"\r\n\r\n")
    lines = header.decode("ascii").split("\r\n")
    path = lines[0].split(" ")[1]
    length = 0
    for line in lines[1:]:
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1])
    return path, await reader.readexactly(length)


def _profile(binding: dict[str, object]) -> dict[str, object]:
    return {
        **binding,
        "outcome": "found",
        "profile": {
            "employee_id": binding["employee_id"],
            "legal_entity_id": binding["legal_entity_ids"][0],
            "employee_number": "SYN-1",
            "display_name": "Synthetic Person",
            "work_email": "synthetic@example.invalid",
            "job_title": None,
            "department_name": None,
            "branch_name": None,
            "legal_entity_name": None,
            "employment_status": "active",
            "hire_date": "2025-01-01",
            "manager_display_name": None,
            "freshness_at": "2026-01-01T00:00:00Z",
        },
    }


def _balance(binding: dict[str, object]) -> dict[str, object]:
    return {
        **binding,
        "outcome": "found",
        "balances": [
            {
                "employee_id": binding["employee_id"],
                "legal_entity_id": binding["legal_entity_ids"][0],
                "leave_type_id": "annual",
                "leave_type_code": "annual",
                "leave_type_name": "Annual",
                "leave_type_name_local": "Annual",
                "fiscal_year": 2026,
                "opening_days": "10.00",
                "accrued_days": "1.00",
                "used_days": "2.00",
                "pending_days": "0.00",
                "available_days": "9.00",
                "calculated_at": "2026-01-01T00:00:00Z",
                "source_watermark": "synthetic",
                "calculation_version": "1.0.0",
            }
        ],
    }


def _summary(binding: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "40000000-0000-4000-8000-000000000001",
        "employee_id": binding["employee_id"],
        "legal_entity_id": binding["legal_entity_ids"][0],
        "leave_type_id": "50000000-0000-4000-8000-000000000001",
        "leave_type_code": "annual",
        "leave_type_name": "Annual",
        "leave_type_name_local": "Annual",
        "start_date": "2026-02-01",
        "end_date": "2026-02-01",
        "working_days": "1.00",
        "is_half_day": False,
        "half_day_period": None,
        "status": "pending",
        "submitted_at": "2026-01-01T00:00:00Z",
        "updated_at": None,
        "working_days_calculation_version": "1.0.0",
    }


async def _exercise() -> None:
    with TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        server_context, client_context, no_client_context, untrusted_context = _contexts(
            temporary_path
        )
        requests: list[str] = []

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                path, raw = await _read_request(reader)
                requests.append(path)
                if path == CONTRACT_PATH:
                    value: object = {
                        "service_identity": "laravel_erp_read_api",
                        "contract_version": "1.0.0",
                        "contract_digest": LARAVEL_ERP_READ_CONTRACT_DIGEST,
                        "read_only": True,
                    }
                else:
                    request = json.loads(raw)
                    binding = {
                        key: value
                        for key, value in request.items()
                        if key not in {"page_size", "cursor", "leave_request_id"}
                    }
                    if path == PROFILE_PATH:
                        value = _profile(binding)
                    elif path == BALANCES_PATH:
                        value = _balance(binding)
                    elif path == REQUESTS_PATH:
                        value = {
                            **binding,
                            "outcome": "found",
                            "requests": {"items": [_summary(binding)], "next_cursor": None},
                        }
                    elif path == REQUEST_DETAIL_PATH:
                        value = {
                            **binding,
                            "outcome": "found",
                            "leave_request": {
                                **_summary(binding),
                                "customer_environment_id": binding["customer_environment_id"],
                                "status_history": [],
                            },
                        }
                    else:
                        raise AssertionError("unexpected path")
                body = json.dumps(value, separators=(",", ":")).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
        port = server.sockets[0].getsockname()[1]
        config = LaravelErpReadConfig(
            origin=f"https://localhost:{port}",
            connect_timeout_seconds=2.0,
            read_timeout_seconds=2.0,
            write_timeout_seconds=2.0,
            pool_timeout_seconds=2.0,
            maximum_connections=1,
            maximum_keepalive_connections=0,
            maximum_request_bytes=8192,
            maximum_response_bytes=32768,
        )
        client = LaravelErpReadClient(config, client_context)
        try:
            await client.open()
            context = TrustedRequestContext(
                context_version=1,
                request_id=str(UUID("10000000-0000-4000-8000-000000000001")),
                customer_environment_id="synthetic_customer",
                user_id="synthetic_user",
                employee_id="20000000-0000-4000-8000-000000000001",
                roles=("employee",),
                permission_codes=("hr.profile.read_self",),
                legal_entity_ids=("30000000-0000-4000-8000-000000000001",),
                enabled_modules=("hr_core",),
                locale="en",
                timezone="UTC",
                purpose="employee_self_service",
                issued_at=datetime(2026, 1, 1, tzinfo=UTC),
                authorization_snapshot_id="synthetic_snapshot",
            )
            record = await LaravelHrCoreReadProvider(client).get_my_employee_profile(
                context=context
            )
            assert record is not None and record.employee_number == "SYN-1"
            leave = LaravelLeaveReadProvider(client)
            assert len(await leave.get_my_leave_balances(context=context)) == 1
            assert (
                len(
                    (
                        await leave.list_my_leave_requests(
                            context=context,
                            statuses=(),
                            start_from=None,
                            start_to=None,
                            limit=20,
                            cursor=None,
                        )
                    ).items
                )
                == 1
            )
            assert (
                await leave.get_my_leave_request(
                    context=context, request_id=UUID("40000000-0000-4000-8000-000000000001")
                )
                is not None
            )
        finally:
            await client.close()

        async def rejected(context: ssl.SSLContext, host: str = "localhost") -> None:
            invalid = LaravelErpReadClient(
                config.model_copy(update={"origin": f"https://{host}:{port}"}), context
            )
            with pytest.raises(LaravelErpReadUnavailable):
                await invalid.open()
            await invalid.close()

        await rejected(no_client_context)
        await rejected(untrusted_context)
        await rejected(client_context, "127.0.0.1")
        assert all(path.parent == temporary_path for path in temporary_path.iterdir())
        assert requests == [
            CONTRACT_PATH,
            PROFILE_PATH,
            BALANCES_PATH,
            REQUESTS_PATH,
            REQUEST_DETAIL_PATH,
        ]
        assert all(path.suffix in {".pem", ".key"} for path in temporary_path.iterdir())
        server.close()
        await server.wait_closed()
    assert not temporary_path.exists()


def test_synthetic_mutual_tls_contract_and_profile_round_trip() -> None:
    asyncio.run(_exercise())
