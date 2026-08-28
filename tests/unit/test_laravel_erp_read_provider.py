from __future__ import annotations

import asyncio
import functools
import json
import ssl
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from erp_ai.capabilities.hr_core import GetMyEmployeeProfileHandler
from erp_ai.capabilities.hr_core.models import GetMyEmployeeProfileInput
from erp_ai.capabilities.leave import (
    GetMyLeaveBalancesHandler,
    GetMyLeaveRequestHandler,
    ListMyLeaveRequestsHandler,
)
from erp_ai.capabilities.leave.models import (
    GetMyLeaveBalancesInput,
    GetMyLeaveRequestInput,
    ListMyLeaveRequestsInput,
)
from erp_ai.context import TrustedRequestContext
from erp_ai.infrastructure.laravel_erp import (
    LARAVEL_ERP_READ_CONTRACT_BYTES,
    LARAVEL_ERP_READ_CONTRACT_DIGEST,
    LaravelContractMetadata,
    LaravelErpReadClient,
    LaravelErpReadConfig,
    LaravelErpReadProviderBundle,
    LaravelErpReadUnavailable,
    LaravelHrCoreReadProvider,
    LaravelLeaveReadProvider,
    LaravelProviderLifecycle,
)
from erp_ai.infrastructure.laravel_erp.client import (
    _same_json_type_and_value,
    _strict_json,
)
from erp_ai.infrastructure.laravel_erp.config import validate_laravel_ssl_context
from erp_ai.infrastructure.laravel_erp.contracts import (
    BALANCES_PATH,
    CONTRACT_PATH,
    PROFILE_PATH,
    REQUEST_DETAIL_PATH,
    REQUESTS_PATH,
)
from erp_ai.infrastructure.laravel_erp.models import (
    BalancesResponse,
    LaravelBinding,
    ProfileRequest,
    ProfileResponse,
    RequestDetailResponse,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
REQUEST_ID = UUID("10000000-0000-4000-8000-000000000001")
EMPLOYEE_ID = "20000000-0000-4000-8000-000000000001"
LEGAL_ID = "30000000-0000-4000-8000-000000000001"
LEAVE_ID = "40000000-0000-4000-8000-000000000001"


def run_async(function: Any) -> Any:
    @functools.wraps(function)
    def wrapper(*args: object, **kwargs: object) -> object:
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def config(**updates: object) -> LaravelErpReadConfig:
    values: dict[str, object] = {
        "origin": "https://erp.internal.example",
        "connect_timeout_seconds": 1.0,
        "read_timeout_seconds": 2.0,
        "write_timeout_seconds": 1.0,
        "pool_timeout_seconds": 1.0,
        "maximum_connections": 2,
        "maximum_keepalive_connections": 1,
        "maximum_request_bytes": 8192,
        "maximum_response_bytes": 32768,
    }
    values.update(updates)
    return LaravelErpReadConfig.model_validate(values, strict=True)


def tls() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def trusted(customer: str = "customer_a") -> TrustedRequestContext:
    return TrustedRequestContext(
        context_version=1,
        request_id=str(REQUEST_ID),
        customer_environment_id=customer,
        user_id="user_1",
        employee_id=EMPLOYEE_ID,
        roles=("employee",),
        permission_codes=("hr.profile.read_self", "leave.balance.read_self"),
        legal_entity_ids=(LEGAL_ID,),
        enabled_modules=("hr_core", "leave"),
        locale="en",
        timezone="Africa/Cairo",
        purpose="employee_self_service",
        issued_at=NOW,
        authorization_snapshot_id="snapshot_1",
    )


def metadata() -> dict[str, object]:
    return {
        "service_identity": "laravel_erp_read_api",
        "contract_version": "1.0.0",
        "contract_digest": LARAVEL_ERP_READ_CONTRACT_DIGEST,
        "read_only": True,
    }


def profile() -> dict[str, object]:
    return {
        "employee_id": EMPLOYEE_ID,
        "legal_entity_id": LEGAL_ID,
        "employee_number": "E-1",
        "display_name": "Synthetic Employee",
        "work_email": "synthetic@example.invalid",
        "job_title": None,
        "department_name": None,
        "branch_name": None,
        "legal_entity_name": None,
        "employment_status": "active",
        "hire_date": "2025-01-01",
        "manager_display_name": None,
        "freshness_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def balance() -> dict[str, object]:
    return {
        "employee_id": EMPLOYEE_ID,
        "legal_entity_id": LEGAL_ID,
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
        "calculated_at": NOW.isoformat().replace("+00:00", "Z"),
        "source_watermark": "synthetic",
        "calculation_version": "1.0.0",
    }


def summary() -> dict[str, object]:
    return {
        "request_id": LEAVE_ID,
        "employee_id": EMPLOYEE_ID,
        "legal_entity_id": LEGAL_ID,
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
        "submitted_at": NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": None,
        "working_days_calculation_version": "1.0.0",
    }


def streamed(status: int, raw: bytes, headers: Any = None) -> httpx.Response:
    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(raw))


def response_for(request: httpx.Request) -> httpx.Response:
    headers = {"Content-Type": "application/json", "Content-Encoding": "identity"}
    if request.url.path == CONTRACT_PATH:
        value: object = metadata()
    else:
        body = json.loads(request.content)
        binding = {
            key: value
            for key, value in body.items()
            if key not in {"page_size", "cursor", "leave_request_id"}
        }
        if request.url.path == PROFILE_PATH:
            value = {**binding, "outcome": "found", "profile": profile()}
        elif request.url.path == BALANCES_PATH:
            value = {**binding, "outcome": "found", "balances": [balance()]}
        elif request.url.path == REQUESTS_PATH:
            value = {
                **binding,
                "outcome": "found",
                "requests": {"items": [summary()], "next_cursor": "opaque"},
            }
        elif request.url.path == REQUEST_DETAIL_PATH:
            detail = {
                **summary(),
                "customer_environment_id": binding["customer_environment_id"],
                "status_history": [],
            }
            value = {**binding, "outcome": "found", "leave_request": detail}
        else:
            return streamed(404, b"{}", headers)
    return streamed(200, json.dumps(value, separators=(",", ":")).encode(), headers)


async def opened(handler: Any = response_for, **updates: object) -> LaravelErpReadClient:
    client = LaravelErpReadClient(
        config(**updates), tls(), test_transport=httpx.MockTransport(handler)
    )
    await client.open()
    return client


def test_contract_golden_bytes_and_metadata_are_frozen() -> None:
    assert LARAVEL_ERP_READ_CONTRACT_BYTES.startswith(b'{"domain"')
    assert LARAVEL_ERP_READ_CONTRACT_BYTES.endswith(b'"read_only":true}')
    import hashlib

    assert (
        hashlib.sha256(
            b"erp-ai:laravel-erp-read-contract:v1\x00" + LARAVEL_ERP_READ_CONTRACT_BYTES
        ).hexdigest()
        == LARAVEL_ERP_READ_CONTRACT_DIGEST
    )
    assert LaravelContractMetadata.model_validate(metadata(), strict=True).read_only is True
    for key, value in (("read_only", 1), ("contract_version", "2.0.0"), ("extra", True)):
        invalid = metadata()
        invalid[key] = value
        with pytest.raises(ValidationError):
            LaravelContractMetadata.model_validate(invalid, strict=True)
    wrong = metadata()
    wrong["contract_digest"] = "0" * 64
    with pytest.raises(ValidationError):
        LaravelContractMetadata.model_validate(wrong, strict=True)


@pytest.mark.parametrize(
    "origin",
    [
        "http://erp.example",
        "https://u:p@erp.example",
        "https://erp.example/base",
        "https://erp.example?q=1",
        "https://erp.example/#x",
        "https://ERP.example",
        "https://[::1]",
        "https://erp.example:bad",
    ],
)
def test_config_rejects_ambiguous_origins_without_exposing_input(origin: str) -> None:
    with pytest.raises(ValidationError) as caught:
        config(origin=origin)
    assert origin not in str(caught.value)


def test_config_is_strict_frozen_repr_safe_and_defensively_copied() -> None:
    value = config()
    assert "erp.internal" not in repr(value)
    with pytest.raises(ValidationError):
        config(maximum_connections="2")
    with pytest.raises(ValidationError):
        config(maximum_connections=1, maximum_keepalive_connections=2)
    with pytest.raises(ValidationError):
        config(unknown=True)
    with pytest.raises(ValidationError):
        config(expected_contract_digest="0" * 64)
    with pytest.raises(ValidationError):
        value.maximum_connections = 3  # type: ignore[misc]
    client = LaravelErpReadClient(value, tls(), test_transport=httpx.MockTransport(response_for))
    object.__setattr__(value, "maximum_connections", 31)
    assert client.config.maximum_connections == 2
    assert "erp.internal" not in repr(client)


def test_ssl_policy_fails_closed() -> None:
    context = tls()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError):
        validate_laravel_ssl_context(context)
    with pytest.raises(TypeError):
        validate_laravel_ssl_context(object())
    context = tls()
    with pytest.warns(DeprecationWarning):
        context.minimum_version = ssl.TLSVersion.TLSv1
    with pytest.raises(ValueError):
        validate_laravel_ssl_context(context)


@run_async
async def test_all_four_providers_share_one_client_and_preserve_bindings() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response_for(request)

    client = await opened(handler)
    hr = LaravelHrCoreReadProvider(client)
    leave = LaravelLeaveReadProvider(client)
    context = trusted()
    assert (await hr.get_my_employee_profile(context=context)).employee_number == "E-1"  # type: ignore[union-attr]
    assert len(await leave.get_my_leave_balances(context=context)) == 1
    page = await leave.list_my_leave_requests(
        context=context,
        statuses=(),
        start_from=None,
        start_to=None,
        limit=20,
        cursor="opaque.in",
    )
    assert page.next_cursor == "opaque"
    detail = await leave.get_my_leave_request(context=context, request_id=UUID(LEAVE_ID))
    assert detail is not None and detail.customer_environment_id == "customer_a"
    assert [call.url.path for call in calls] == [
        CONTRACT_PATH,
        PROFILE_PATH,
        BALANCES_PATH,
        REQUESTS_PATH,
        REQUEST_DETAIL_PATH,
    ]
    assert calls[0].method == "GET"
    assert all(call.url.query == b"" for call in calls)
    assert b"roles" not in b"".join(call.content for call in calls)
    assert b"permission_codes" not in b"".join(call.content for call in calls)
    assert b"enabled_modules" not in b"".join(call.content for call in calls)

    assert await GetMyEmployeeProfileHandler(hr).execute(context, GetMyEmployeeProfileInput())
    assert await GetMyLeaveBalancesHandler(leave).execute(context, GetMyLeaveBalancesInput())
    assert await ListMyLeaveRequestsHandler(leave).execute(context, ListMyLeaveRequestsInput())
    assert await GetMyLeaveRequestHandler(leave).execute(
        context, GetMyLeaveRequestInput(request_id=UUID(LEAVE_ID))
    )
    await client.close()
    assert client.state == "closed"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("correlation_request_id", "90000000-0000-4000-8000-000000000001"),
        ("customer_environment_id", "customer_b"),
        ("user_id", "user_2"),
        ("employee_id", "employee_2"),
        ("authorization_snapshot_id", "snapshot_2"),
        ("purpose", "manager_review"),
        ("legal_entity_ids", ["legal_2"]),
        ("tool_name", "get_my_leave_balances"),
        ("tool_version", "2.0.0"),
    ],
)
@run_async
async def test_detail_not_found_and_binding_substitution_fail_closed(
    field: str, replacement: object
) -> None:
    def not_found(request: httpx.Request) -> httpx.Response:
        if request.url.path == CONTRACT_PATH:
            return response_for(request)
        body = json.loads(request.content)
        binding = {key: value for key, value in body.items() if key != "leave_request_id"}
        raw = json.dumps(
            {**binding, "outcome": "not_found", "leave_request": None},
            separators=(",", ":"),
        ).encode()
        return streamed(200, raw, {"Content-Type": "application/json"})

    client = await opened(not_found)
    provider = LaravelLeaveReadProvider(client)
    assert await provider.get_my_leave_request(context=trusted(), request_id=UUID(LEAVE_ID)) is None
    await client.close()

    def substituted(request: httpx.Request) -> httpx.Response:
        if request.url.path != CONTRACT_PATH:
            body = json.loads(request.content)
            value: dict[str, object] = {**body, "outcome": "found", "profile": profile()}
            value[field] = replacement
            return streamed(
                200,
                json.dumps(value, separators=(",", ":")).encode(),
                {"Content-Type": "application/json"},
            )
        return response_for(request)

    client = await opened(substituted)
    with pytest.raises(LaravelErpReadUnavailable):
        await LaravelHrCoreReadProvider(client).get_my_employee_profile(context=trusted())
    await client.close()


@pytest.mark.parametrize(
    "mode",
    ["status", "media", "cookie", "encoding", "duplicate", "nan", "oversize", "length_conflict"],
)
@run_async
async def test_invalid_responses_are_contained(mode: str) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if request.url.path == CONTRACT_PATH:
            return response_for(request)
        if mode == "status":
            return streamed(403, b'{"private":"hidden"}', {"Content-Type": "application/json"})
        if mode == "media":
            return streamed(200, b"{}", {"Content-Type": "text/plain"})
        if mode == "cookie":
            return streamed(
                200, b"{}", {"Content-Type": "application/json", "Set-Cookie": "secret=x"}
            )
        if mode == "encoding":
            return streamed(
                200, b"{}", {"Content-Type": "application/json", "Content-Encoding": "gzip"}
            )
        if mode == "duplicate":
            return streamed(
                200, b'{"binding":{},"binding":{}}', {"Content-Type": "application/json"}
            )
        if mode == "nan":
            return streamed(200, b'{"x":NaN}', {"Content-Type": "application/json"})
        if mode == "length_conflict":
            return streamed(
                200,
                b"{}",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", "2"),
                    ("Transfer-Encoding", "chunked"),
                ],
            )
        return streamed(200, b"x" * 600, {"Content-Type": "application/json"})

    client = await opened(handler, maximum_response_bytes=512)
    with pytest.raises(LaravelErpReadUnavailable) as caught:
        await LaravelHrCoreReadProvider(client).get_my_employee_profile(context=trusted())
    assert "private" not in str(caught.value)
    assert attempts == 2
    await client.close()


def test_strict_json_rejects_invalid_utf8_and_duplicate_keys() -> None:
    with pytest.raises(UnicodeDecodeError):
        _strict_json(b"\xff")
    with pytest.raises(ValueError):
        _strict_json(b'{"a":1,"a":2}')
    with pytest.raises(ValueError):
        _strict_json(b'{"a":Infinity}')
    assert not _same_json_type_and_value(True, 1)
    assert not _same_json_type_and_value({"a": [1]}, {"a": [1.0]})
    assert not _same_json_type_and_value([1], [1, 2])
    assert _same_json_type_and_value({"a": [1]}, {"a": [1]})


@run_async
async def test_startup_drift_rolls_back_once_and_calls_require_readiness() -> None:
    calls = 0

    def drift(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        value = metadata()
        value["contract_version"] = "9.0.0"
        return streamed(
            200,
            json.dumps(value, separators=(",", ":")).encode(),
            {"Content-Type": "application/json"},
        )

    client = LaravelErpReadClient(config(), tls(), test_transport=httpx.MockTransport(drift))
    with pytest.raises(LaravelErpReadUnavailable):
        await client.open()
    assert client.state == "failed" and calls == 1
    with pytest.raises(LaravelErpReadUnavailable):
        await client.open()
    with pytest.raises(LaravelErpReadUnavailable):
        await client.post_model(
            PROFILE_PATH, LaravelContractMetadata.model_construct(), LaravelContractMetadata
        )
    await client.close()


@run_async
async def test_cancellation_propagates_without_retry() -> None:
    calls = 0

    async def cancel(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    client = LaravelErpReadClient(config(), tls(), test_transport=httpx.MockTransport(cancel))
    with pytest.raises(asyncio.CancelledError):
        await client.open()
    assert calls == 1 and client.state == "failed"


def test_detail_outcome_consistency_and_error_redaction() -> None:
    with pytest.raises(ValidationError) as caught:
        RequestDetailResponse.model_validate(
            {"secret": "selector", "outcome": "not_found", "leave_request": profile()},
            strict=True,
        )
    assert "selector" not in str(caught.value)
    valid_binding = {
        "contract_version": "1.0.0",
        "correlation_request_id": str(REQUEST_ID),
        "customer_environment_id": "customer_a",
        "user_id": "user_1",
        "employee_id": EMPLOYEE_ID,
        "authorization_snapshot_id": "snapshot_1",
        "purpose": "employee_self_service",
        "legal_entity_ids": [LEGAL_ID],
        "tool_name": "get_my_leave_request",
        "tool_version": "1.0.0",
    }
    with pytest.raises(ValidationError):
        RequestDetailResponse.model_validate(
            {**valid_binding, "outcome": "found", "leave_request": None}
        )


@run_async
async def test_missing_employee_and_invalid_correlation_are_rejected_without_http() -> None:
    client = await opened()
    provider = LaravelHrCoreReadProvider(client)
    missing = trusted().model_copy(update={"employee_id": None})
    malformed = trusted().model_copy(update={"request_id": "not-a-uuid"})
    with pytest.raises(LaravelErpReadUnavailable):
        await provider.get_my_employee_profile(context=missing)
    with pytest.raises(LaravelErpReadUnavailable):
        await provider.get_my_employee_profile(context=malformed)
    await client.close()


@run_async
async def test_request_limit_dynamic_path_and_response_header_edges_fail_closed() -> None:
    client = await opened(maximum_request_bytes=512)
    large = trusted().model_copy(
        update={"legal_entity_ids": tuple(f"legal_entity_{index}" for index in range(40))}
    )
    with pytest.raises(LaravelErpReadUnavailable):
        await LaravelHrCoreReadProvider(client).get_my_employee_profile(context=large)
    raw_client = client._client
    assert raw_client is not None
    with pytest.raises(LaravelErpReadUnavailable):
        await client._send(raw_client, "POST", "/unapproved", {})
    await client.close()

    class WrongOrigin:
        def build_request(self, *args: object, **kwargs: object) -> httpx.Request:
            return httpx.Request("POST", "https://foreign.invalid/unapproved")

    direct = LaravelErpReadClient(config(), tls(), test_transport=httpx.MockTransport(response_for))
    with pytest.raises(LaravelErpReadUnavailable):
        await direct._send(WrongOrigin(), "POST", PROFILE_PATH, {})  # type: ignore[arg-type]

    for headers in (
        [("Content-Type", "application/json"), ("Content-Type", "application/json")],
        [("Content-Type", "application/json"), ("Content-Length", "x")],
        [("Content-Type", "application/json"), ("Content-Length", "999999")],
    ):

        def edge(request: httpx.Request, selected: Any = headers) -> httpx.Response:
            if request.url.path == CONTRACT_PATH:
                return response_for(request)
            return streamed(200, b"{}", selected)

        edge_client = await opened(edge)
        with pytest.raises(LaravelErpReadUnavailable):
            await LaravelHrCoreReadProvider(edge_client).get_my_employee_profile(context=trusted())
        await edge_client.close()

    def malformed(request: httpx.Request) -> httpx.Response:
        if request.url.path == CONTRACT_PATH:
            return response_for(request)
        return streamed(200, b"{}", {"Content-Type": "application/json"})

    malformed_client = await opened(malformed)
    with pytest.raises(LaravelErpReadUnavailable):
        await LaravelHrCoreReadProvider(malformed_client).get_my_employee_profile(context=trusted())
    await malformed_client.close()

    class CoercedResponse(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)
        value: bool

    def coerced(request: httpx.Request) -> httpx.Response:
        if request.url.path == CONTRACT_PATH:
            return response_for(request)
        return streamed(200, b'{"value":1}', {"Content-Type": "application/json"})

    coerced_client = await opened(coerced)
    with pytest.raises(LaravelErpReadUnavailable):
        await coerced_client.post_model(PROFILE_PATH, GetMyEmployeeProfileInput(), CoercedResponse)
    with pytest.raises(LaravelErpReadUnavailable):
        await coerced_client.post_model(
            PROFILE_PATH,
            ProfileRequest.model_validate(
                {
                    "contract_version": "1.0.0",
                    "correlation_request_id": REQUEST_ID,
                    "customer_environment_id": "customer_a",
                    "user_id": "user_1",
                    "employee_id": EMPLOYEE_ID,
                    "authorization_snapshot_id": "snapshot_1",
                    "purpose": "employee_self_service",
                    "legal_entity_ids": (LEGAL_ID,),
                    "tool_name": "get_my_employee_profile",
                    "tool_version": "1.0.0",
                },
                strict=True,
            ),
            CoercedResponse,
        )
    await coerced_client.close()


@run_async
async def test_lifecycle_is_idempotent_and_concurrency_safe() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return response_for(request)

    client = LaravelErpReadClient(config(), tls(), test_transport=httpx.MockTransport(handler))
    await asyncio.gather(client.open(), client.open())
    assert calls == 1 and client.state == "ready"
    await asyncio.gather(client.close(), client.close())
    assert client.state == "closed"


class _Resource:
    def __init__(
        self,
        events: list[str],
        *,
        fail_open: bool = False,
        fail_close: bool = False,
        cancel_close: bool = False,
    ) -> None:
        self.events, self.fail_open, self.fail_close, self.cancel_close = (
            events,
            fail_open,
            fail_close,
            cancel_close,
        )

    async def open(self) -> None:
        self.events.append("open")
        if self.fail_open:
            raise RuntimeError

    async def close(self) -> None:
        self.events.append("close")
        if self.cancel_close:
            raise asyncio.CancelledError
        if self.fail_close:
            raise RuntimeError


@run_async
async def test_explicit_bundle_and_combined_lifecycle() -> None:
    events: list[str] = []
    downstream = _Resource(events)
    bundle = LaravelErpReadProviderBundle(config(), tls(), downstream)
    assert [handler.tool_name for handler in bundle.handlers] == [
        "get_my_employee_profile",
        "get_my_leave_balances",
        "list_my_leave_requests",
        "get_my_leave_request",
    ]
    fake_client = _Resource(events)
    lifecycle = LaravelProviderLifecycle(fake_client, downstream)  # type: ignore[arg-type]
    await lifecycle.open()
    await lifecycle.close()
    assert events == ["open", "open", "close", "close"]
    with pytest.raises(TypeError):
        LaravelErpReadProviderBundle(config(), tls(), object())  # type: ignore[arg-type]


@run_async
async def test_combined_lifecycle_rolls_back_and_contains_shutdown_failures() -> None:
    events: list[str] = []
    lifecycle = LaravelProviderLifecycle(_Resource(events), _Resource(events, fail_open=True))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        await lifecycle.open()
    assert events == ["open", "open", "close"]
    lifecycle = LaravelProviderLifecycle(
        _Resource([], fail_close=True), _Resource([], fail_close=True)
    )  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="shutdown failed"):
        await lifecycle.close()
    lifecycle = LaravelProviderLifecycle(_Resource([]), _Resource([], cancel_close=True))  # type: ignore[arg-type]
    with pytest.raises(asyncio.CancelledError):
        await lifecycle.close()


@run_async
async def test_constructed_request_and_truncated_response_fail_closed() -> None:
    client = await opened()
    invalid = ProfileRequest.model_construct(contract_version="1.0.0")
    with pytest.raises(LaravelErpReadUnavailable):
        await client.post_model(PROFILE_PATH, invalid, ProfileResponse)
    await client.close()


def test_wire_model_consistency_and_duplicate_scope_validation() -> None:
    binding = {
        "contract_version": "1.0.0",
        "correlation_request_id": str(REQUEST_ID),
        "customer_environment_id": "customer_a",
        "user_id": "user_1",
        "employee_id": EMPLOYEE_ID,
        "authorization_snapshot_id": "snapshot_1",
        "purpose": "employee_self_service",
        "legal_entity_ids": [LEGAL_ID],
        "tool_name": "get_my_employee_profile",
        "tool_version": "1.0.0",
    }
    with pytest.raises(ValidationError):
        LaravelBinding.model_validate({**binding, "legal_entity_ids": [LEGAL_ID, LEGAL_ID]})
    with pytest.raises(ValidationError):
        ProfileResponse.model_validate_json(
            json.dumps({**binding, "outcome": "found", "profile": None}), strict=False
        )
    detail_binding = {**binding, "tool_name": "get_my_leave_request"}
    detail = {
        **summary(),
        "customer_environment_id": "customer_a",
        "status_history": [],
    }
    with pytest.raises(ValidationError):
        RequestDetailResponse.model_validate_json(
            json.dumps({**detail_binding, "outcome": "not_found", "leave_request": detail}),
            strict=False,
        )
    balances_binding = {**binding, "tool_name": "get_my_leave_balances"}
    parsed = BalancesResponse.model_validate_json(
        json.dumps({**balances_binding, "outcome": "found", "balances": [balance()]}),
        strict=False,
    )
    assert isinstance(parsed.balances, tuple)


@pytest.mark.parametrize("mode", ["profile", "balances", "list", "detail"])
@run_async
async def test_operation_record_scope_substitution_fails_closed(mode: str) -> None:
    def substituted(request: httpx.Request) -> httpx.Response:
        if request.url.path == CONTRACT_PATH:
            return response_for(request)
        body = json.loads(request.content)
        binding = {
            key: value
            for key, value in body.items()
            if key not in {"page_size", "cursor", "leave_request_id"}
        }
        if mode == "profile":
            record = profile()
            record["employee_id"] = "foreign"
            value = {**binding, "outcome": "found", "profile": record}
        elif mode == "balances":
            record = balance()
            record["legal_entity_id"] = "foreign"
            value = {**binding, "outcome": "found", "balances": [record]}
        elif mode == "list":
            record = summary()
            record["employee_id"] = "90000000-0000-4000-8000-000000000001"
            value = {
                **binding,
                "outcome": "found",
                "requests": {"items": [record], "next_cursor": None},
            }
        else:
            record = {
                **summary(),
                "request_id": "90000000-0000-4000-8000-000000000001",
                "customer_environment_id": binding["customer_environment_id"],
                "status_history": [],
            }
            value = {**binding, "outcome": "found", "leave_request": record}
        return streamed(
            200,
            json.dumps(value, separators=(",", ":")).encode(),
            {"Content-Type": "application/json"},
        )

    client = await opened(substituted)
    context = trusted()
    with pytest.raises(LaravelErpReadUnavailable):
        if mode == "profile":
            await LaravelHrCoreReadProvider(client).get_my_employee_profile(context=context)
        elif mode == "balances":
            await LaravelLeaveReadProvider(client).get_my_leave_balances(context=context)
        elif mode == "list":
            await LaravelLeaveReadProvider(client).list_my_leave_requests(
                context=context,
                statuses=(),
                start_from=None,
                start_to=None,
                limit=20,
                cursor=None,
            )
        else:
            await LaravelLeaveReadProvider(client).get_my_leave_request(
                context=context, request_id=UUID(LEAVE_ID)
            )
    await client.close()


@run_async
async def test_laravel_list_rejects_uncontracted_filters_without_http() -> None:
    client = await opened()
    with pytest.raises(LaravelErpReadUnavailable):
        await LaravelLeaveReadProvider(client).list_my_leave_requests(
            context=trusted(),
            statuses=("pending",),  # type: ignore[arg-type]
            start_from=None,
            start_to=None,
            limit=20,
            cursor=None,
        )
    await client.close()

    def truncated(request: httpx.Request) -> httpx.Response:
        if request.url.path == CONTRACT_PATH:
            return response_for(request)
        return streamed(200, b"{}", {"Content-Type": "application/json", "Content-Length": "3"})

    client = await opened(truncated)
    with pytest.raises(LaravelErpReadUnavailable):
        await LaravelHrCoreReadProvider(client).get_my_employee_profile(context=trusted())
    await client.close()
