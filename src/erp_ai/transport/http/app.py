"""Explicit internal ERP-to-AI FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import Response
from pydantic import SecretStr
from starlette.exceptions import HTTPException

from erp_ai.application import ApplicationAuditEvent, ApplicationAuditSink, TrustedRequestReference

from .config import InternalHttpTransportConfig
from .errors import IngressAuthenticationDenied, IngressAuthenticationUnavailable
from .models import TrustedIngressAuthenticationRequest
from .parsing import StrictRequestError, canonical_public_chat_digest, parse_public_chat_request
from .protocols import (
    RequestIdFactory,
    TransportLifecycle,
    TrustedApplicationExecutor,
    TrustedIngressAuthenticator,
)
from .responses import (
    TransportErrorCode,
    application_response,
    empty_response,
    failure_response,
)

_AUTHORITY_HEADERS = frozenset(
    {
        b"x-customer-id",
        b"x-user-id",
        b"x-roles",
        b"x-permissions",
        b"x-modules",
        b"x-legal-entities",
        b"x-purpose",
        b"x-route-intent",
        b"x-tool-name",
        b"x-tool-version",
        b"x-authorization-snapshot-id",
        b"x-resolver-handle",
        b"x-request-id",
    }
)


@dataclass(slots=True)
class _LifecycleState:
    ready: bool = False
    in_flight_request_ids: set[str] = field(default_factory=set)
    request_id_lock: Any = field(default_factory=Lock, repr=False)


def _request_id(factory: RequestIdFactory, state: _LifecycleState) -> str:
    value = factory.create()
    if type(value) is not str:
        raise ValueError("request ID factory returned invalid data")
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ValueError("request ID factory returned invalid data")
    normalized = str(parsed)
    with state.request_id_lock:
        if normalized in state.in_flight_request_ids:
            raise ValueError("request ID factory returned invalid data")
        state.in_flight_request_ids.add(normalized)
    return normalized


def _release_request_id(request_id: str, state: _LifecycleState) -> None:
    with state.request_id_lock:
        state.in_flight_request_ids.discard(request_id)


def _in_flight_request_id_count(state: _LifecycleState) -> int:
    with state.request_id_lock:
        return len(state.in_flight_request_ids)


def _header_values(request: Request, name: bytes) -> tuple[bytes, ...]:
    return tuple(value for key, value in request.scope.get("headers", ()) if key.lower() == name)


def _validate_envelope(request: Request, config: InternalHttpTransportConfig) -> None:
    if config.require_https and request.scope.get("scheme") != "https":
        raise StrictRequestError("invalid transport scheme")
    if (
        request.scope.get("method") != "POST"
        or request.scope.get("path") != "/v1/chat"
        or request.scope.get("raw_path") != b"/v1/chat"
        or request.scope.get("query_string") != b""
    ):
        raise StrictRequestError("invalid request target")
    hosts = _header_values(request, b"host")
    if len(hosts) != 1:
        raise StrictRequestError("invalid host")
    try:
        host = hosts[0].decode("ascii", errors="strict").lower()
    except UnicodeDecodeError:
        raise StrictRequestError("invalid host") from None
    if host not in config.allowed_hosts:
        raise StrictRequestError("invalid host")
    if any(key.lower() in _AUTHORITY_HEADERS for key, _ in request.scope.get("headers", ())):
        raise StrictRequestError("authority headers are forbidden")


def _bearer_assertion(request: Request, limit: int) -> SecretStr:
    values = _header_values(request, b"authorization")
    if len(values) != 1 or len(values[0]) > limit:
        raise IngressAuthenticationDenied()
    try:
        raw = values[0].decode("ascii", errors="strict")
    except UnicodeDecodeError:
        raise IngressAuthenticationDenied() from None
    if not raw.startswith("Bearer ") or raw.count(" ") != 1:
        raise IngressAuthenticationDenied()
    assertion = raw[7:]
    if (
        not assertion
        or "," in assertion
        or any(char.isspace() or ord(char) < 33 for char in assertion)
    ):
        raise IngressAuthenticationDenied()
    return SecretStr(assertion)


def _validate_media(request: Request, maximum_body_bytes: int) -> None:
    encodings = _header_values(request, b"content-encoding")
    if len(encodings) > 1 or (encodings and encodings[0].lower() != b"identity"):
        raise LookupError("unsupported content encoding")
    types = _header_values(request, b"content-type")
    if len(types) != 1:
        raise LookupError("unsupported content type")
    try:
        parts = [part.strip().lower() for part in types[0].decode("ascii").split(";")]
    except UnicodeDecodeError:
        raise LookupError("unsupported content type") from None
    if parts not in (["application/json"], ["application/json", "charset=utf-8"]):
        raise LookupError("unsupported content type")
    lengths = _header_values(request, b"content-length")
    if len(lengths) > 1:
        raise StrictRequestError("invalid content length")
    transfers = _header_values(request, b"transfer-encoding")
    if len(transfers) > 1 or (lengths and transfers):
        raise StrictRequestError("ambiguous body framing")
    if transfers and transfers[0].lower() != b"chunked":
        raise StrictRequestError("invalid transfer encoding")
    if lengths:
        try:
            encoded_length = lengths[0].decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise StrictRequestError("invalid content length") from None
        if not encoded_length or not encoded_length.isascii() or not encoded_length.isdecimal():
            raise StrictRequestError("invalid content length")
        try:
            length = int(encoded_length, 10)
        except ValueError:
            raise StrictRequestError("invalid content length") from None
        if length > maximum_body_bytes:
            raise OverflowError("request body too large")


async def _read_body(request: Request, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    more_body = True
    while more_body:
        message = await request.receive()
        if message.get("type") != "http.request":
            raise StrictRequestError("request body unavailable")
        chunk = message.get("body", b"")
        if type(chunk) is not bytes:
            raise StrictRequestError("request body unavailable")
        raw_more_body = message.get("more_body", False)
        if type(raw_more_body) is not bool:
            raise StrictRequestError("request body unavailable")
        more_body = raw_more_body
        total += len(chunk)
        if total > limit:
            raise OverflowError("request body too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _audit_rejection(audit_sink: ApplicationAuditSink, request_id: str, reason: str) -> bool:
    try:
        await audit_sink.record(
            ApplicationAuditEvent(
                request_id=request_id,
                stage="validation",
                outcome="failure",
                internal_reason=reason,
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return False
    return True


def create_internal_http_app(
    *,
    config: InternalHttpTransportConfig,
    authenticator: TrustedIngressAuthenticator,
    request_id_factory: RequestIdFactory,
    application: TrustedApplicationExecutor,
    application_audit_sink: ApplicationAuditSink,
    lifecycle: TransportLifecycle,
) -> FastAPI:
    config = InternalHttpTransportConfig.model_validate(
        config.model_dump(mode="python"), strict=True
    )
    for dependency, protocol, label in (
        (authenticator, TrustedIngressAuthenticator, "authenticator"),
        (request_id_factory, RequestIdFactory, "request ID factory"),
        (application, TrustedApplicationExecutor, "application"),
        (application_audit_sink, ApplicationAuditSink, "application audit sink"),
        (lifecycle, TransportLifecycle, "lifecycle"),
    ):
        if not isinstance(dependency, protocol):
            raise TypeError(f"{label} dependency is required")
    state = _LifecycleState()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await lifecycle.startup()
        state.ready = True
        try:
            yield
        finally:
            state.ready = False
            await lifecycle.shutdown()

    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        debug=False,
        lifespan=lifespan,
    )
    app.state._erp_ai_transport_state = state

    @app.get("/health/live", include_in_schema=False)
    async def liveness() -> Response:
        return empty_response(204)

    @app.get("/health/ready", include_in_schema=False)
    async def readiness() -> Response:
        return empty_response(204 if state.ready else 503)

    async def execute_chat(request: Request, request_id: str) -> Response:
        async def reject(code: TransportErrorCode, status: int, reason: str) -> Response:
            if not await _audit_rejection(application_audit_sink, request_id, reason):
                return failure_response(TransportErrorCode.AUDIT_UNAVAILABLE, 503, request_id)
            return failure_response(code, status, request_id)

        if not state.ready:
            return await reject(TransportErrorCode.SERVICE_UNAVAILABLE, 503, "transport_not_ready")

        try:
            _validate_envelope(request, config)
        except StrictRequestError:
            return await reject(TransportErrorCode.INVALID_REQUEST, 400, "invalid_http_envelope")
        try:
            assertion = _bearer_assertion(request, config.maximum_authorization_bytes)
        except IngressAuthenticationDenied:
            return await reject(
                TransportErrorCode.AUTHENTICATION_REQUIRED, 401, "ingress_authentication_rejected"
            )
        try:
            _validate_media(request, config.maximum_body_bytes)
        except LookupError:
            return await reject(
                TransportErrorCode.UNSUPPORTED_MEDIA_TYPE, 415, "unsupported_request_media"
            )
        except OverflowError:
            return await reject(TransportErrorCode.REQUEST_TOO_LARGE, 413, "request_body_too_large")
        except StrictRequestError:
            return await reject(TransportErrorCode.INVALID_REQUEST, 400, "invalid_http_envelope")
        try:
            body = await _read_body(request, config.maximum_body_bytes)
        except asyncio.CancelledError:
            raise
        except OverflowError:
            return await reject(TransportErrorCode.REQUEST_TOO_LARGE, 413, "request_body_too_large")
        except Exception:
            return await reject(TransportErrorCode.INVALID_REQUEST, 400, "request_body_unavailable")
        try:
            public_request = parse_public_chat_request(body)
            if public_request.stream:
                raise StrictRequestError("streaming responses are unavailable")
            digest = canonical_public_chat_digest(public_request)
        except StrictRequestError:
            return await reject(TransportErrorCode.INVALID_REQUEST, 400, "invalid_public_request")
        try:
            authentication_request = TrustedIngressAuthenticationRequest(
                request_id=request_id,
                method="POST",
                route_path="/v1/chat",
                body_digest_sha256=digest,
                bearer_assertion=assertion,
            )
            reference = await authenticator.authenticate(authentication_request)
            if type(reference) is not TrustedRequestReference:
                raise IngressAuthenticationDenied()
            reference = TrustedRequestReference.model_validate(
                reference.model_dump(mode="python"), strict=True
            )
            if reference.request_id != request_id:
                raise IngressAuthenticationDenied()
        except asyncio.CancelledError:
            raise
        except IngressAuthenticationDenied:
            return await reject(
                TransportErrorCode.AUTHENTICATION_REQUIRED, 401, "ingress_authentication_rejected"
            )
        except IngressAuthenticationUnavailable:
            return await reject(
                TransportErrorCode.SERVICE_UNAVAILABLE, 503, "ingress_authentication_unavailable"
            )
        except Exception:
            return await reject(
                TransportErrorCode.SERVICE_UNAVAILABLE, 503, "ingress_authentication_unavailable"
            )
        try:
            result = await application.execute(public_request, reference)
            return application_response(result, request_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            return failure_response(TransportErrorCode.INTERNAL_ERROR, 500, request_id)

    @app.post("/v1/chat", include_in_schema=False)
    async def chat(request: Request) -> Response:
        try:
            request_id = _request_id(request_id_factory, state)
        except Exception:
            return failure_response(TransportErrorCode.INTERNAL_ERROR, 500, "unavailable")
        try:
            return await execute_chat(request, request_id)
        finally:
            _release_request_id(request_id, state)

    @app.exception_handler(HTTPException)
    async def http_exception(request: Request, error: HTTPException) -> Response:
        raw_path = request.scope.get("raw_path", b"")
        is_chat_attempt = (
            request.scope.get("path") == "/v1/chat"
            or (type(raw_path) is bytes and raw_path.lower().startswith(b"/v1%2fchat"))
            or (type(raw_path) is bytes and raw_path.startswith(b"/v1/chat"))
        )
        request_id = "unavailable"
        if is_chat_attempt:
            with suppress(Exception):
                request_id = _request_id(request_id_factory, state)
        try:
            if is_chat_attempt and request_id != "unavailable":
                reason = (
                    "request_method_not_allowed"
                    if error.status_code == 405
                    else "request_route_not_found"
                )
                if not await _audit_rejection(application_audit_sink, request_id, reason):
                    return failure_response(TransportErrorCode.AUDIT_UNAVAILABLE, 503, request_id)
            if error.status_code == 405:
                return failure_response(TransportErrorCode.METHOD_NOT_ALLOWED, 405, request_id)
            return failure_response(TransportErrorCode.NOT_FOUND, 404, request_id)
        finally:
            if request_id != "unavailable":
                _release_request_id(request_id, state)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, __: Exception) -> Response:
        request_id = "unavailable"
        if request.scope.get("path") == "/v1/chat":
            with suppress(Exception):
                request_id = _request_id(request_id_factory, state)
        try:
            if request_id != "unavailable" and not await _audit_rejection(
                application_audit_sink, request_id, "unhandled_transport_failure"
            ):
                return failure_response(TransportErrorCode.AUDIT_UNAVAILABLE, 503, request_id)
            return failure_response(TransportErrorCode.INTERNAL_ERROR, 500, request_id)
        finally:
            if request_id != "unavailable":
                _release_request_id(request_id, state)

    return app
