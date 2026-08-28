"""One-attempt bounded mTLS client for the frozen Laravel ERP read API."""

import asyncio
import json
import ssl
from contextlib import suppress
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, ValidationError

from .config import LaravelErpReadConfig, validate_laravel_ssl_context
from .contracts import (
    CONTRACT_PATH,
    LARAVEL_ERP_READ_CONTRACT_DIGEST,
    LARAVEL_ERP_READ_CONTRACT_VERSION,
    LARAVEL_ERP_READ_SERVICE_IDENTITY,
    POST_PATHS,
    LaravelContractMetadata,
)
from .errors import LaravelErpReadUnavailable
from .models import (
    BalancesRequest,
    LaravelBinding,
    ProfileRequest,
    RequestDetailRequest,
    RequestListRequest,
)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _invalid_number(_: str) -> object:
    raise ValueError("invalid JSON number")


def _strict_json(raw: bytes) -> object:
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_pairs,
        parse_constant=_invalid_number,
    )


def _same_json_type_and_value(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _same_json_type_and_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_json_type_and_value(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


@dataclass(slots=True, init=False)
class LaravelErpReadClient:
    """Shared lifecycle client; construction is side-effect free."""

    config: LaravelErpReadConfig = field(repr=False)
    _ssl_context: ssl.SSLContext | None = field(repr=False)
    _transport: httpx.AsyncBaseTransport | None = field(repr=False)
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _state: str = field(default="created", repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __init__(
        self,
        config: LaravelErpReadConfig,
        ssl_context: ssl.SSLContext,
        *,
        test_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        validated = LaravelErpReadConfig.model_validate(
            config.model_dump(mode="python"), strict=True
        )
        validate_laravel_ssl_context(ssl_context)
        object.__setattr__(self, "config", validated)
        object.__setattr__(self, "_ssl_context", ssl_context)
        object.__setattr__(self, "_transport", test_transport)
        object.__setattr__(self, "_client", None)
        object.__setattr__(self, "_state", "created")
        object.__setattr__(self, "_lifecycle_lock", asyncio.Lock())

    @property
    def state(self) -> str:
        return self._state

    async def open(self) -> None:
        async with self._lifecycle_lock:
            if self._state == "ready" and self._client is not None:
                return
            if self._state != "created" or self._client is not None:
                raise LaravelErpReadUnavailable
            self._state = "starting"
            try:
                context = self._ssl_context
                validate_laravel_ssl_context(context)
                assert context is not None
                timeout = httpx.Timeout(
                    connect=self.config.connect_timeout_seconds,
                    read=self.config.read_timeout_seconds,
                    write=self.config.write_timeout_seconds,
                    pool=self.config.pool_timeout_seconds,
                )
                client = httpx.AsyncClient(
                    base_url=self.config.origin.get_secret_value(),
                    verify=context,
                    transport=self._transport,
                    timeout=timeout,
                    limits=httpx.Limits(
                        max_connections=self.config.maximum_connections,
                        max_keepalive_connections=self.config.maximum_keepalive_connections,
                    ),
                    follow_redirects=False,
                    trust_env=False,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                        "X-ERP-AI-Service": LARAVEL_ERP_READ_SERVICE_IDENTITY,
                        "X-ERP-AI-Contract-Version": LARAVEL_ERP_READ_CONTRACT_VERSION,
                        "X-ERP-AI-Contract-Digest": LARAVEL_ERP_READ_CONTRACT_DIGEST,
                    },
                )
                self._client = client
                await self._verify_contract(client)
                self._state = "ready"
            except asyncio.CancelledError:
                await self._rollback_open()
                raise
            except Exception:
                await self._rollback_open()
                raise LaravelErpReadUnavailable from None

    async def _rollback_open(self) -> None:
        client, self._client = self._client, None
        self._state = "failed"
        if client is not None:
            with suppress(Exception):
                await client.aclose()

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if self._state == "closed":
                return
            client, self._client = self._client, None
            self._state = "stopping"
        try:
            if client is not None:
                await client.aclose()
        finally:
            self._state = "closed"

    async def _verify_contract(self, client: httpx.AsyncClient) -> None:
        value = await self._send(client, "GET", CONTRACT_PATH, None)
        try:
            metadata = LaravelContractMetadata.model_validate(value, strict=True)
            if (
                metadata.service_identity
                != self.config.expected_service_identity.get_secret_value()
                or metadata.contract_version
                != self.config.expected_contract_version.get_secret_value()
                or metadata.contract_digest
                != self.config.expected_contract_digest.get_secret_value()
            ):
                raise LaravelErpReadUnavailable  # pragma: no cover - validated config is identical
        except ValidationError:
            raise LaravelErpReadUnavailable from None

    async def post_model(
        self,
        path: str,
        request: BaseModel,
        response_model: type[BaseModel],
    ) -> BaseModel:
        client = self._client
        if self._state != "ready" or client is None or path not in POST_PATHS:
            raise LaravelErpReadUnavailable
        if not isinstance(
            request, (ProfileRequest, BalancesRequest, RequestListRequest, RequestDetailRequest)
        ):
            raise LaravelErpReadUnavailable
        try:
            source_payload = _project_request(request)
            request = type(request).model_validate_json(request.model_dump_json(), strict=False)
            payload = _project_request(request)
            if not _same_json_type_and_value(source_payload, payload):  # pragma: no cover
                raise LaravelErpReadUnavailable  # pragma: no cover
        except LaravelErpReadUnavailable:  # pragma: no cover - defensive normalization mismatch
            raise
        except Exception:
            raise LaravelErpReadUnavailable from None
        value = await self._send(client, "POST", path, payload)
        try:
            canonical = json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )
            result = response_model.model_validate_json(canonical, strict=False)
            normalized = result.model_dump(mode="json", exclude_none=False)
            if not _same_json_type_and_value(value, normalized):
                raise LaravelErpReadUnavailable
            return result
        except ValidationError:
            raise LaravelErpReadUnavailable from None

    async def _send(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        payload: dict[str, object] | None,
    ) -> object:
        try:
            body = None
            headers: dict[str, str] = {}
            if payload is not None:
                body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                if len(body) > self.config.maximum_request_bytes:
                    raise LaravelErpReadUnavailable
                headers["Content-Type"] = "application/json"
            request = client.build_request(method, path, content=body, headers=headers)
            expected = httpx.URL(self.config.origin.get_secret_value())
            if (
                request.url.scheme != expected.scheme
                or request.url.host != expected.host
                or request.url.port != expected.port
                or request.url.raw_path != path.encode("ascii")
                or request.url.query
            ):
                raise LaravelErpReadUnavailable
            response = await client.send(request, stream=True)
            try:
                if response.status_code != 200 or response.is_redirect:
                    raise LaravelErpReadUnavailable
                content_types = response.headers.get_list("content-type")
                lengths = response.headers.get_list("content-length")
                if len(content_types) != 1 or len(lengths) > 1:
                    raise LaravelErpReadUnavailable
                if "transfer-encoding" in response.headers and lengths:
                    raise LaravelErpReadUnavailable
                if "set-cookie" in response.headers:
                    raise LaravelErpReadUnavailable
                if response.headers.get("content-encoding") not in (None, "identity"):
                    raise LaravelErpReadUnavailable
                if content_types[0].split(";", 1)[0].strip().lower() != "application/json":
                    raise LaravelErpReadUnavailable
                if lengths and (
                    not lengths[0].isdigit() or int(lengths[0]) > self.config.maximum_response_bytes
                ):
                    raise LaravelErpReadUnavailable
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_raw():
                    size += len(chunk)
                    if size > self.config.maximum_response_bytes:
                        raise LaravelErpReadUnavailable
                    chunks.append(chunk)
                raw = b"".join(chunks)
                if lengths and len(raw) != int(lengths[0]):
                    raise LaravelErpReadUnavailable
                return _strict_json(raw)
            finally:
                client.cookies.clear()
                await response.aclose()
        except asyncio.CancelledError:
            raise
        except LaravelErpReadUnavailable:
            raise
        except Exception:
            raise LaravelErpReadUnavailable from None


def _binding_projection(request: LaravelBinding) -> dict[str, object]:
    values: dict[str, object] = {
        "contract_version": request.contract_version,
        "correlation_request_id": str(request.correlation_request_id),
        "customer_environment_id": request.customer_environment_id,
        "user_id": request.user_id,
        "employee_id": request.employee_id,
        "authorization_snapshot_id": request.authorization_snapshot_id,
        "purpose": request.purpose,
        "legal_entity_ids": list(request.legal_entity_ids),
        "tool_name": request.tool_name,
        "tool_version": request.tool_version,
    }
    return values


def _project_request(request: LaravelBinding) -> dict[str, object]:
    result = _binding_projection(request)
    if isinstance(request, (ProfileRequest, BalancesRequest)):
        return result
    if isinstance(request, RequestListRequest):
        result["page_size"] = request.page_size
        result["cursor"] = request.cursor
        return result
    if isinstance(request, RequestDetailRequest):
        result["leave_request_id"] = str(request.leave_request_id)
        return result
    raise LaravelErpReadUnavailable  # pragma: no cover - closed request union
