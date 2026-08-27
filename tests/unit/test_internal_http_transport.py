import asyncio
from copy import deepcopy
from typing import Any

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.exceptions import HTTPException

from erp_ai.api import PublicChatRequest
from erp_ai.application import ApplicationAuditEvent, TrustedRequestReference
from erp_ai.orchestration import AgentErrorCode, PublicChatFailure, PublicChatSuccess
from erp_ai.transport.http import (
    IngressAuthenticationDenied,
    IngressAuthenticationUnavailable,
    InternalHttpTransportConfig,
    TrustedIngressAuthenticationRequest,
    canonical_public_chat_bytes,
    canonical_public_chat_digest,
    create_internal_http_app,
)
from erp_ai.transport.http.parsing import (
    StrictRequestError,
    _canonical_public_chat_bytes,
    parse_public_chat_request,
)

REQUEST_ID = "123e4567-e89b-42d3-a456-426614174000"


class Ids:
    def __init__(self, value: object | None = None) -> None:
        self.value = value
        self.calls = 0

    def create(self) -> str:
        self.calls += 1
        if self.value is not None:
            return self.value  # type: ignore[return-value]
        if self.calls == 1:
            return REQUEST_ID
        return f"123e4567-e89b-42d3-a456-{426_614_174_000 + self.calls - 1:012d}"


class Authenticator:
    def __init__(self, outcome: object = None) -> None:
        self.outcome = outcome
        self.calls: list[TrustedIngressAuthenticationRequest] = []

    async def authenticate(
        self, request: TrustedIngressAuthenticationRequest
    ) -> TrustedRequestReference:
        self.calls.append(request)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if self.outcome is not None:
            return self.outcome  # type: ignore[return-value]
        return TrustedRequestReference(
            request_id=request.request_id, resolver_handle="opaque_handle"
        )


class Application:
    def __init__(self, result: object = None) -> None:
        self.result = result or PublicChatSuccess(
            answer="Synthetic answer", response_language="en", citations=()
        )
        self.calls: list[tuple[PublicChatRequest, TrustedRequestReference]] = []

    async def execute(self, request: PublicChatRequest, reference: TrustedRequestReference) -> Any:
        self.calls.append((request, reference))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class Audit:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.events: list[ApplicationAuditEvent] = []

    async def record(self, event: ApplicationAuditEvent) -> None:
        self.events.append(event)
        if self.failure:
            raise self.failure


class Lifecycle:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.started = 0
        self.stopped = 0

    async def startup(self) -> None:
        self.started += 1
        if self.failure:
            raise self.failure

    async def shutdown(self) -> None:
        self.stopped += 1


def config(**changes: object) -> InternalHttpTransportConfig:
    values: dict[str, object] = {"allowed_hosts": ("erp.internal",)}
    values.update(changes)
    return InternalHttpTransportConfig(**values)


def build(
    *,
    auth: Authenticator | None = None,
    application: Application | None = None,
    audit: Audit | None = None,
    ids: Ids | None = None,
    lifecycle: Lifecycle | None = None,
    transport_config: InternalHttpTransportConfig | None = None,
):  # type: ignore[no-untyped-def]
    auth = auth or Authenticator()
    application = application or Application()
    audit = audit or Audit()
    ids = ids or Ids()
    lifecycle = lifecycle or Lifecycle()
    app = create_internal_http_app(
        config=transport_config or config(),
        authenticator=auth,
        request_id_factory=ids,
        application=application,
        application_audit_sink=audit,
        lifecycle=lifecycle,
    )
    return app, auth, application, audit, ids, lifecycle


def request(client: TestClient, **changes: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "method": "POST",
        "url": "https://erp.internal/v1/chat",
        "headers": {"Authorization": "Bearer synthetic_assertion"},
        "json": {"message": "Hello", "stream": False},
    }
    values.update(changes)
    return client.request(**values)


def test_configuration_is_strict_frozen_copied_and_redacted() -> None:
    hosts = ["ERP.INTERNAL"]
    value = config(allowed_hosts=hosts)
    hosts.append("other.internal")
    assert value.allowed_hosts == ("erp.internal",)
    assert "erp.internal" not in repr(value)
    with pytest.raises(ValidationError):
        value.maximum_body_bytes = 3  # type: ignore[misc]
    invalid = (
        {"allowed_hosts": ()},
        {"allowed_hosts": ("*",)},
        {"allowed_hosts": ("a", "A")},
        {"allowed_hosts": ("https://a",)},
        {"allowed_hosts": ("a/path",)},
        {"allowed_hosts": ("a",), "maximum_body_bytes": True},
        {"allowed_hosts": ("a",), "maximum_body_bytes": 0},
        {"allowed_hosts": ("a",), "maximum_authorization_bytes": 20_000},
        {"allowed_hosts": ("a",), "require_https": 1},
        {"allowed_hosts": ("a",), "unknown": True},
        {"allowed_hosts": ("user@host",)},
        {"allowed_hosts": ("host:",)},
        {"allowed_hosts": ("host:0",)},
        {"allowed_hosts": ("host:65536",)},
        {"allowed_hosts": ("a..b",)},
        {"allowed_hosts": (" host",)},
        {"allowed_hosts": (1,)},
    )
    for item in invalid:
        with pytest.raises(ValidationError):
            InternalHttpTransportConfig(**item)


def test_strict_parser_and_canonical_digest_golden_contract() -> None:
    omitted = parse_public_chat_request(b'{ "message":"Hello" }')
    first = parse_public_chat_request(b'{ "stream":false, "message":"Hello" }')
    second = parse_public_chat_request(b'{"message":"Hello","stream":false}')
    assert canonical_public_chat_bytes(omitted) == canonical_public_chat_bytes(first)
    assert canonical_public_chat_digest(first) == canonical_public_chat_digest(second)
    assert canonical_public_chat_bytes(first) == (
        b'{"domain":"erp-ai:internal-http-chat:v1","contract_version":1,'
        b'"method":"POST","route_path":"/v1/chat","request":{"message":"Hello",'
        b'"stream":false,"preferred_response_language":null}}'
    )
    assert canonical_public_chat_digest(first) == (
        "3846b4757bc23ccb9ada1fe4a75dc0954bec09c357e0dbb7feb5b4c57b111e58"
    )
    arabic = parse_public_chat_request('{"message":"مرحبا"}'.encode())
    assert "مرحبا".encode() in canonical_public_chat_bytes(arabic)
    assert canonical_public_chat_digest(arabic) != canonical_public_chat_digest(first)
    changed = first.model_copy(update={"message": "Changed"})
    assert canonical_public_chat_digest(changed) != canonical_public_chat_digest(first)
    language = first.model_copy(update={"preferred_response_language": "ar"})
    assert canonical_public_chat_digest(language) != canonical_public_chat_digest(first)
    composed = parse_public_chat_request('{"message":"é"}'.encode())
    decomposed = parse_public_chat_request('{"message":"é"}'.encode())
    assert canonical_public_chat_bytes(composed) != canonical_public_chat_bytes(decomposed)
    base = canonical_public_chat_bytes(first)
    assert (
        _canonical_public_chat_bytes(
            first,
            domain="different-domain",
            contract_version=1,
            method="POST",
            raw_route=b"/v1/chat",
        )
        != base
    )
    assert (
        _canonical_public_chat_bytes(
            first,
            domain="erp-ai:internal-http-chat:v1",
            contract_version=1,
            method="PUT",
            raw_route=b"/v1/chat",
        )
        != base
    )
    assert (
        _canonical_public_chat_bytes(
            first,
            domain="erp-ai:internal-http-chat:v1",
            contract_version=1,
            method="POST",
            raw_route=b"/v1/other",
        )
        != base
    )
    with pytest.raises(StrictRequestError):
        _canonical_public_chat_bytes(
            first,
            domain="erp-ai:internal-http-chat:v1",
            contract_version=1,
            method="POST",
            raw_route=b"/v1/\xff",
        )


@pytest.mark.parametrize(
    "body",
    (
        b"",
        b"\xef\xbb\xbf{}",
        b"\xff",
        b'{"message":"a","message":"b"}',
        b'{"message":NaN}',
        b'{"message":Infinity}',
        b'{"message":-Infinity}',
        b"null",
        b"[]",
        b'"scalar"',
        b'{"message":"a"} trailing',
        b'{"message":1}',
        b'{"message":true}',
        b'{"message":null}',
        b'{"message":[]}',
        b'{"message":"a","unknown":true}',
    ),
)
def test_strict_parser_rejects_invalid_inputs(body: bytes) -> None:
    with pytest.raises(StrictRequestError):
        parse_public_chat_request(body)


def test_authentication_model_is_frozen_strict_and_repr_safe() -> None:
    marker = "assertion_sensitive_marker"
    value = TrustedIngressAuthenticationRequest(
        request_id=REQUEST_ID,
        method="POST",
        route_path="/v1/chat",
        body_digest_sha256="a" * 64,
        bearer_assertion=marker,
    )
    assert marker not in repr(value)
    assert isinstance(value.bearer_assertion, SecretStr)
    with pytest.raises(ValidationError) as caught:
        TrustedIngressAuthenticationRequest.model_validate(
            {**value.model_dump(), "body_digest_sha256": marker}, strict=True
        )
    assert marker not in str(caught.value)
    with pytest.raises(ValidationError):
        value.method = "GET"  # type: ignore[misc]


def test_success_lifecycle_headers_and_exact_public_schema() -> None:
    app, auth, application, audit, ids, lifecycle = build()
    with TestClient(app) as client:
        assert client.get("https://erp.internal/health/live").status_code == 204
        assert client.get("https://erp.internal/health/ready").status_code == 204
        response = request(client)
    assert response.status_code == 200
    assert response.json() == {
        "answer": "Synthetic answer",
        "response_language": "en",
        "citations": [],
    }
    assert response.headers["x-request-id"] == REQUEST_ID
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert len(auth.calls) == len(application.calls) == 1
    assert audit.events == []
    assert ids.calls == 1
    assert lifecycle.started == lifecycle.stopped == 1
    assert auth.calls[0].body_digest_sha256 == canonical_public_chat_digest(application.calls[0][0])


def test_route_surface_is_exact_and_framework_features_are_absent() -> None:
    app, *_ = build()
    surface = {
        (route.path, frozenset(route.methods or ()))
        for route in app.routes
        if hasattr(route, "methods")
    }
    assert surface == {
        ("/v1/chat", frozenset({"POST"})),
        ("/health/live", frozenset({"GET"})),
        ("/health/ready", frozenset({"GET"})),
    }
    assert app.docs_url is app.redoc_url is app.openapi_url is None
    assert app.router.redirect_slashes is False
    assert app.user_middleware == []


def test_successful_dependency_order_is_request_id_digest_authentication_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import erp_ai.transport.http.app as app_module

    trace: list[str] = []

    class TraceIds(Ids):
        def create(self) -> str:
            trace.append("request_id")
            return super().create()

    class TraceAuthenticator(Authenticator):
        async def authenticate(
            self, request: TrustedIngressAuthenticationRequest
        ) -> TrustedRequestReference:
            trace.append("authenticate")
            return await super().authenticate(request)

    class TraceApplication(Application):
        async def execute(
            self, request: PublicChatRequest, reference: TrustedRequestReference
        ) -> Any:
            trace.append("application")
            return await super().execute(request, reference)

    original_digest = app_module.canonical_public_chat_digest

    def traced_digest(value: PublicChatRequest) -> str:
        trace.append("digest")
        return original_digest(value)

    monkeypatch.setattr(app_module, "canonical_public_chat_digest", traced_digest)
    app, *_ = build(auth=TraceAuthenticator(), application=TraceApplication(), ids=TraceIds())
    with TestClient(app) as client:
        response = request(client)
    assert response.status_code == 200
    assert trace == ["request_id", "digest", "authenticate", "application"]


@pytest.mark.parametrize(
    ("headers", "status"),
    (
        ({}, 401),
        ({"Authorization": "Basic abc"}, 401),
        ({"Authorization": "Bearer"}, 401),
        ({"Authorization": "Bearer "}, 401),
        ({"Authorization": "Bearer a,b"}, 401),
        ({"Authorization": "Bearer a b"}, 401),
        ({"Authorization": "Bearer " + "a" * 5000}, 401),
        ({"X-API-Key": "not_authentication"}, 401),
        ({"Cookie": "authorization=Bearer%20not_authentication"}, 401),
    ),
)
def test_bearer_rejections_are_generic_and_audited(headers: dict[str, str], status: int) -> None:
    app, auth, application, audit, _, _ = build()
    with TestClient(app) as client:
        response = request(client, headers=headers)
    assert response.status_code == status
    assert response.headers["www-authenticate"] == "Bearer"
    assert len(audit.events) == 1
    assert auth.calls == application.calls == []
    assert "synthetic_assertion" not in response.text


def test_duplicate_authorization_is_rejected() -> None:
    app, auth, application, audit, _, _ = build()
    with TestClient(app) as client:
        response = client.post(
            "https://erp.internal/v1/chat",
            headers=[("Authorization", "Bearer one"), ("Authorization", "Bearer two")],
            json={"message": "Hello"},
        )
    assert response.status_code == 401
    assert len(audit.events) == 1
    assert auth.calls == application.calls == []


def test_streaming_request_is_rejected_before_authentication() -> None:
    from erp_ai.transport.http.app import _in_flight_request_id_count

    app, auth, application, audit, _, _ = build()
    with TestClient(app) as client:
        response = request(client, json={"message": "Hello", "stream": True})
    assert response.status_code == 400
    assert response.json()["safe_error_code"] == "INVALID_REQUEST"
    assert len(audit.events) == 1
    assert auth.calls == application.calls == []
    assert _in_flight_request_id_count(app.state._erp_ai_transport_state) == 0


@pytest.mark.parametrize(
    ("changes", "status"),
    (
        ({"url": "http://erp.internal/v1/chat"}, 400),
        ({"url": "https://wrong.internal/v1/chat"}, 400),
        ({"url": "https://erp.internal/v1/chat?token=x"}, 400),
        ({"headers": {"Authorization": "Bearer a", "X-Request-ID": "client"}}, 400),
        ({"headers": {"Authorization": "Bearer a", "Content-Type": "text/plain"}}, 415),
        (
            {
                "headers": {
                    "Authorization": "Bearer a",
                    "Content-Type": "application/json",
                    "Content-Encoding": "gzip",
                },
                "content": b"{}",
                "json": None,
            },
            415,
        ),
        (
            {
                "headers": {
                    "Authorization": "Bearer a",
                    "Content-Type": "application/json",
                },
                "content": b"",
                "json": None,
            },
            400,
        ),
        (
            {
                "headers": {
                    "Authorization": "Bearer a",
                    "Content-Type": "application/json",
                },
                "content": b"\xff",
                "json": None,
            },
            400,
        ),
    ),
)
def test_envelope_and_media_rejections_precede_authentication(
    changes: dict[str, object], status: int
) -> None:
    app, auth, application, audit, _, _ = build()
    with TestClient(app) as client:
        response = request(client, **changes)
    assert response.status_code == status
    assert len(audit.events) == 1
    assert auth.calls == application.calls == []


@pytest.mark.parametrize(
    "field",
    (
        "request_id",
        "resolver_handle",
        "customer_environment_id",
        "user_id",
        "roles",
        "permission_codes",
        "enabled_modules",
        "legal_entity_ids",
        "purpose",
        "authorization_snapshot_id",
        "trusted_context",
        "route_intent",
        "tool_name",
        "tool_version",
        "tool_selection",
        "arguments",
        "audit",
        "model",
        "provider",
    ),
)
def test_public_authority_spoofing_fields_fail_before_authentication(field: str) -> None:
    app, auth, application, audit, _, _ = build()
    with TestClient(app) as client:
        response = request(client, json={"message": "Hello", field: "spoofed"})
    assert response.status_code == 400
    assert len(audit.events) == 1
    assert auth.calls == application.calls == []


@pytest.mark.parametrize(
    "header",
    (
        "X-Customer-ID",
        "X-User-ID",
        "X-Roles",
        "X-Permissions",
        "X-Modules",
        "X-Legal-Entities",
        "X-Purpose",
        "X-Route-Intent",
        "X-Tool-Name",
        "X-Tool-Version",
        "X-Authorization-Snapshot-ID",
        "X-Resolver-Handle",
        "X-Request-ID",
    ),
)
def test_authority_headers_are_rejected(header: str) -> None:
    app, auth, application, audit, _, _ = build()
    with TestClient(app) as client:
        response = request(
            client, headers={"Authorization": "Bearer synthetic_assertion", header: "spoofed"}
        )
    assert response.status_code == 400
    assert len(audit.events) == 1
    assert auth.calls == application.calls == []


def test_forwarded_headers_are_not_identity_and_do_not_change_binding() -> None:
    app, auth, application, _, _, _ = build()
    with TestClient(app) as client:
        response = request(
            client,
            headers={
                "Authorization": "Bearer synthetic_assertion",
                "Forwarded": "for=customer_marker;proto=http",
                "X-Forwarded-For": "user_marker",
                "X-Forwarded-Proto": "http",
            },
        )
    assert response.status_code == 200
    assert len(auth.calls) == len(application.calls) == 1


@pytest.mark.parametrize(
    ("outcome", "status"),
    (
        (IngressAuthenticationDenied(), 401),
        (IngressAuthenticationUnavailable(), 503),
        (RuntimeError("private_provider_marker"), 503),
    ),
)
def test_authenticator_failures_are_contained_and_audited(
    outcome: BaseException, status: int
) -> None:
    auth = Authenticator(outcome)
    app, _, application, audit, _, _ = build(auth=auth)
    with TestClient(app) as client:
        response = request(client)
    assert response.status_code == status
    assert len(auth.calls) == len(audit.events) == 1
    assert application.calls == []
    assert "private_provider_marker" not in response.text


def test_sensitive_ingress_values_never_cross_public_or_audit_boundaries(caplog: Any) -> None:
    bearer = "bearer_assertion_distinctive_marker"
    resolver = "resolver_handle_distinctive_marker"
    message = "user_message_distinctive_marker"
    auth = Authenticator(TrustedRequestReference(request_id=REQUEST_ID, resolver_handle=resolver))
    app, _, application, audit, _, _ = build(auth=auth)
    with TestClient(app) as client:
        response = request(
            client,
            headers={"Authorization": f"Bearer {bearer}"},
            json={"message": message},
        )
    assert response.status_code == 200
    assert len(auth.calls) == len(application.calls) == 1
    authentication_request = auth.calls[0]
    reference = application.calls[0][1]
    public_material = repr(
        (
            response.text,
            dict(response.headers),
            audit.events,
            caplog.text,
            authentication_request,
            authentication_request.model_dump(mode="json"),
            reference,
            reference.model_dump(mode="json"),
        )
    )
    for marker in (bearer, resolver, message):
        assert marker not in public_material

    rejected, _, _, rejected_audit, _, _ = build()
    with TestClient(rejected) as client:
        failure = request(client, headers={}, json={"message": message})
    serialized = rejected_audit.events[0].model_dump(mode="json")
    assert set(serialized) == {"request_id", "stage", "outcome", "internal_reason"}
    assert message not in repr((failure.text, dict(failure.headers), serialized, caplog.text))


def test_reference_is_revalidated_and_bound_to_server_request_id() -> None:
    outcomes = (
        TrustedRequestReference(
            request_id="223e4567-e89b-42d3-a456-426614174000", resolver_handle="x"
        ),
        TrustedRequestReference.model_construct(request_id=REQUEST_ID, resolver_handle=""),
        {"request_id": REQUEST_ID, "resolver_handle": "opaque"},
    )
    for outcome in outcomes:
        auth = Authenticator(outcome)
        app, _, application, audit, _, _ = build(auth=auth)
        with TestClient(app) as client:
            response = request(client)
        assert response.status_code in (401, 503)
        assert application.calls == []
        assert len(audit.events) == 1


def test_audit_failure_withholds_rejection_and_cancellation_propagates() -> None:
    from erp_ai.transport.http.app import _in_flight_request_id_count

    app, _, _, audit, _, _ = build(audit=Audit(RuntimeError("audit_private")))
    with TestClient(app) as client:
        response = request(client, headers={})
    assert response.status_code == 503
    assert response.json()["safe_error_code"] == "AUDIT_UNAVAILABLE"
    assert len(audit.events) == 1
    assert _in_flight_request_id_count(app.state._erp_ai_transport_state) == 0

    async def exercise_cancel() -> None:
        from erp_ai.transport.http.app import _audit_rejection

        with pytest.raises(asyncio.CancelledError):
            await _audit_rejection(Audit(asyncio.CancelledError()), REQUEST_ID, "cancelled")

    asyncio.run(exercise_cancel())


def test_application_failures_map_exhaustively_without_transport_audit() -> None:
    cases = (
        (AgentErrorCode.AGENT_UNAVAILABLE, 503),
        (AgentErrorCode.AUDIT_UNAVAILABLE, 503),
        (AgentErrorCode.AGENT_LIMIT_REACHED, 503),
        (AgentErrorCode.AGENT_CATALOG_LIMIT, 503),
        (AgentErrorCode.INVALID_MODEL_RESPONSE, 500),
    )
    for code, status in cases:
        application = Application(PublicChatFailure(safe_error_code=code, safe_message="Safe"))
        app, _, _, audit, _, _ = build(application=application)
        with TestClient(app) as client:
            response = request(client)
        assert response.status_code == status
        assert response.json() == {"safe_error_code": code.value, "safe_message": "Safe"}
        assert audit.events == []


def test_invalid_application_result_and_exception_fail_generically_without_second_audit() -> None:
    for result in (object(), RuntimeError("application_private_marker")):
        application = Application(result)
        app, _, _, audit, _, _ = build(application=application)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = request(client)
        assert response.status_code == 500
        assert "application_private_marker" not in response.text
        assert audit.events == []


def test_size_limits_apply_to_content_length_and_streamed_body() -> None:
    app, auth, application, audit, _, _ = build(transport_config=config(maximum_body_bytes=256))
    with TestClient(app) as client:
        early = request(
            client,
            headers={
                "Authorization": "Bearer synthetic_assertion",
                "Content-Type": "application/json",
                "Content-Length": "257",
            },
            content=b"{}",
            json=None,
        )
        streamed = request(
            client,
            headers={
                "Authorization": "Bearer synthetic_assertion",
                "Content-Type": "application/json",
            },
            content=(part for part in (b'{"message":"', b"x" * 300, b'"}')),
            json=None,
        )
    assert early.status_code == streamed.status_code == 413
    assert len(audit.events) == 2
    assert auth.calls == application.calls == []


def test_generic_routes_docs_redirects_and_lifecycle_surface() -> None:
    app, _, _, audit, _, lifecycle = build()
    with TestClient(app) as client:
        assert client.get("https://erp.internal/openapi.json").status_code == 404
        assert client.get("https://erp.internal/docs").status_code == 404
        assert client.get("https://erp.internal/v1/chat").status_code == 405
        trailing = client.post("https://erp.internal/v1/chat/", follow_redirects=False)
        assert trailing.status_code == 404
        assert "access-control-allow-origin" not in trailing.headers
    assert len(audit.events) == 2
    assert {event.internal_reason for event in audit.events} == {
        "request_method_not_allowed",
        "request_route_not_found",
    }
    assert lifecycle.started == lifecycle.stopped == 1


def test_route_rejection_fails_closed_when_audit_is_unavailable() -> None:
    app, _, _, audit, _, _ = build(audit=Audit(RuntimeError("private_audit")))
    with TestClient(app) as client:
        response = client.get("https://erp.internal/v1/chat")
    assert response.status_code == 503
    assert response.json()["safe_error_code"] == "AUDIT_UNAVAILABLE"
    assert "private_audit" not in response.text
    assert len(audit.events) == 1


def test_every_failure_status_uses_contained_json_and_security_headers() -> None:
    default, *_ = build()
    invalid_application, *_ = build(application=Application(object()))
    unavailable_auth, *_ = build(auth=Authenticator(IngressAuthenticationUnavailable()))
    with (
        TestClient(default, raise_server_exceptions=False) as client,
        TestClient(invalid_application, raise_server_exceptions=False) as invalid_client,
        TestClient(unavailable_auth) as unavailable_client,
    ):
        responses = (
            request(client, url="https://erp.internal/v1/chat?x=1"),
            request(client, headers={}),
            request(
                client,
                headers={
                    "Authorization": "Bearer synthetic",
                    "Content-Type": "application/json",
                    "Content-Length": "2000000",
                },
                content=b"{}",
                json=None,
            ),
            request(
                client,
                headers={"Authorization": "Bearer synthetic", "Content-Type": "text/plain"},
                content=b"{}",
                json=None,
            ),
            client.post("https://erp.internal/v1/chat/", follow_redirects=False),
            client.get("https://erp.internal/v1/chat"),
            request(invalid_client),
            request(unavailable_client),
        )
    assert {response.status_code for response in responses} == {
        400,
        401,
        404,
        405,
        413,
        415,
        500,
        503,
    }
    for response in responses:
        assert response.headers["content-type"] == "application/json"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert set(response.json()) == {"safe_error_code", "safe_message"}
        assert "detail" not in response.text
        assert response.headers["x-request-id"] not in {"", "unavailable"}
        if response.status_code == 401:
            assert response.headers["www-authenticate"] == "Bearer"
        else:
            assert "www-authenticate" not in response.headers
        if response.status_code == 405 and "allow" in response.headers:
            assert response.headers["allow"] == "POST"


def test_factory_requires_every_dependency_and_valid_generated_uuid() -> None:
    app, auth, application, audit, ids, lifecycle = build()
    del app
    values = {
        "config": config(),
        "authenticator": auth,
        "request_id_factory": ids,
        "application": application,
        "application_audit_sink": audit,
        "lifecycle": lifecycle,
    }
    for key in tuple(values)[1:]:
        changed = deepcopy(values)
        changed[key] = object()
        with pytest.raises(TypeError):
            create_internal_http_app(**changed)  # type: ignore[arg-type]
    for invalid_id in ("not-a-uuid", "123e4567-e89b-12d3-a456-426614174000", 3):
        built, *_ = build(ids=Ids(invalid_id))
        with TestClient(built) as client:
            response = request(client)
        assert response.status_code == 500
        assert response.headers["x-request-id"] == "unavailable"


def test_request_id_state_returns_to_zero_after_many_sequential_requests() -> None:
    from erp_ai.transport.http.app import _in_flight_request_id_count

    app, auth, application, audit, ids, _ = build()
    with TestClient(app) as client:
        for _ in range(512):
            assert request(client).status_code == 200
            assert _in_flight_request_id_count(app.state._erp_ai_transport_state) == 0
    assert len(auth.calls) == len(application.calls) == ids.calls == 512
    assert audit.events == []


def test_concurrent_duplicate_request_id_fails_before_authentication() -> None:
    from erp_ai.transport.http.app import _in_flight_request_id_count

    class BlockingAuthenticator(Authenticator):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def authenticate(
            self, request: TrustedIngressAuthenticationRequest
        ) -> TrustedRequestReference:
            self.calls.append(request)
            self.entered.set()
            await self.release.wait()
            return TrustedRequestReference(
                request_id=request.request_id, resolver_handle="opaque_handle"
            )

    auth = BlockingAuthenticator()
    app, _, application, audit, ids, _ = build(auth=auth, ids=Ids(REQUEST_ID))
    route = next(route for route in app.routes if getattr(route, "path", None) == "/v1/chat")

    def raw() -> Request:
        sent = False

        async def receive() -> dict[str, object]:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {
                "type": "http.request",
                "body": b'{"message":"Hello"}',
                "more_body": False,
            }

        return _raw_request(
            [
                (b"host", b"erp.internal"),
                (b"authorization", b"Bearer synthetic"),
                (b"content-type", b"application/json"),
            ],
            receive=receive,
        )

    async def exercise() -> tuple[Response, Response]:
        async with app.router.lifespan_context(app):
            first_task = asyncio.create_task(route.endpoint(raw()))
            await auth.entered.wait()
            assert _in_flight_request_id_count(app.state._erp_ai_transport_state) == 1
            duplicate = await route.endpoint(raw())
            auth.release.set()
            first = await first_task
            return first, duplicate

    first, duplicate = asyncio.run(exercise())
    assert first.status_code == 200
    assert duplicate.status_code == 500
    assert duplicate.headers["x-request-id"] == "unavailable"
    assert len(auth.calls) == len(application.calls) == 1
    assert audit.events == []
    assert ids.calls == 2
    assert _in_flight_request_id_count(app.state._erp_ai_transport_state) == 0


def test_lifecycle_startup_failure_prevents_serving() -> None:
    app, *_, lifecycle = build(lifecycle=Lifecycle(RuntimeError("startup_private")))
    with pytest.raises(RuntimeError, match="startup_private"), TestClient(app):
        pass
    assert lifecycle.started == 1
    assert lifecycle.stopped == 0


def test_unready_chat_fails_before_authentication_and_is_audited() -> None:
    app, auth, application, audit, _, lifecycle = build()
    route = next(route for route in app.routes if getattr(route, "path", None) == "/v1/chat")
    raw = _raw_request([(b"host", b"erp.internal")])
    response = asyncio.run(route.endpoint(raw))
    assert response.status_code == 503
    assert response.body == (
        b'{"safe_error_code":"SERVICE_UNAVAILABLE",'
        b'"safe_message":"The service is temporarily unavailable."}'
    )
    assert len(audit.events) == 1
    assert audit.events[0].internal_reason == "transport_not_ready"
    assert auth.calls == application.calls == []
    assert lifecycle.started == lifecycle.stopped == 0


def test_readiness_is_instance_local_and_false_before_startup_and_shutdown() -> None:
    class ObservingLifecycle(Lifecycle):
        readiness_endpoint: Any = None
        shutdown_readiness: int | None = None

        async def shutdown(self) -> None:
            assert self.readiness_endpoint is not None
            self.shutdown_readiness = (await self.readiness_endpoint()).status_code
            await super().shutdown()

    first_lifecycle = ObservingLifecycle()
    first, _, _, first_audit, _, _ = build(lifecycle=first_lifecycle)
    second, _, _, second_audit, _, _ = build()
    first_ready = next(
        route for route in first.routes if getattr(route, "path", None) == "/health/ready"
    )
    second_ready = next(
        route for route in second.routes if getattr(route, "path", None) == "/health/ready"
    )
    first_lifecycle.readiness_endpoint = first_ready.endpoint
    assert asyncio.run(first_ready.endpoint()).status_code == 503
    assert asyncio.run(second_ready.endpoint()).status_code == 503
    with TestClient(first) as client:
        assert client.get("https://erp.internal/health/ready").status_code == 204
        assert asyncio.run(second_ready.endpoint()).status_code == 503
    assert first_lifecycle.shutdown_readiness == 503
    assert first_lifecycle.started == first_lifecycle.stopped == 1
    assert first_audit.events == second_audit.events == []


def test_lifecycle_shutdown_failure_and_cancellation_do_not_become_http_details() -> None:
    class ShutdownFailure(Lifecycle):
        async def shutdown(self) -> None:
            self.stopped += 1
            raise RuntimeError("private_shutdown_marker")

    failing, *_ = build(lifecycle=ShutdownFailure())
    with (
        pytest.raises(RuntimeError, match="private_shutdown_marker"),
        TestClient(failing) as client,
    ):
        response = client.get("https://erp.internal/health/ready")
        assert response.status_code == 204
        assert "private_shutdown_marker" not in response.text

    cancelled, *_ = build(lifecycle=Lifecycle(asyncio.CancelledError()))

    async def cancelled_startup() -> None:
        async with cancelled.router.lifespan_context(cancelled):
            raise AssertionError("cancelled startup unexpectedly completed")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancelled_startup())


def _raw_request(
    headers: list[tuple[bytes, bytes]],
    *,
    scope_changes: dict[str, object] | None = None,
    receive: Any = None,
) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/v1/chat",
        "raw_path": b"/v1/chat",
        "query_string": b"",
        "headers": headers,
        "server": ("erp.internal", 443),
        "client": ("127.0.0.1", 1),
    }
    scope.update(scope_changes or {})
    return Request(scope, receive=receive)


async def _raw_asgi_exchange(
    app: Any,
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    scope_changes: dict[str, object] | None = None,
    messages: list[dict[str, object]] | None = None,
) -> tuple[int, dict[bytes, bytes], bytes]:
    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/v1/chat",
        "raw_path": b"/v1/chat",
        "query_string": b"",
        "headers": headers
        or [
            (b"host", b"erp.internal"),
            (b"authorization", b"Bearer synthetic"),
            (b"content-type", b"application/json"),
        ],
        "server": ("erp.internal", 443),
        "client": ("127.0.0.1", 1),
        "root_path": "",
    }
    scope.update(scope_changes or {})
    pending = list(
        messages
        or [
            {
                "type": "http.request",
                "body": b'{"message":"Hello"}',
                "more_body": False,
            }
        ]
    )
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    async with app.router.lifespan_context(app):
        await app(scope, receive, send)
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")  # type: ignore[arg-type]
        for message in sent
        if message["type"] == "http.response.body"
    )
    return (
        start["status"],  # type: ignore[return-value]
        dict(start["headers"]),  # type: ignore[arg-type]
        body,
    )


def test_raw_asgi_ambiguities_reject_before_authentication() -> None:
    base = [
        (b"host", b"erp.internal"),
        (b"authorization", b"Bearer synthetic"),
        (b"content-type", b"application/json"),
    ]
    cases = (
        ([*base, (b"host", b"erp.internal")], {}, 400),
        ([*base, (b"content-type", b"application/json")], {}, 415),
        ([*base, (b"content-length", b"19"), (b"content-length", b"19")], {}, 400),
        ([*base, (b"content-length", b"19"), (b"transfer-encoding", b"chunked")], {}, 400),
        (base, {"raw_path": b"/v1%2Fchat"}, 400),
        (base, {"query_string": b"="}, 400),
        (base, {"method": "PATCH"}, 405),
    )
    for headers, scope_changes, expected in cases:
        app, auth, application, audit, ids, _ = build()
        status, response_headers, body = asyncio.run(
            _raw_asgi_exchange(app, headers=headers, scope_changes=scope_changes)
        )
        assert status == expected
        assert response_headers[b"cache-control"] == b"no-store"
        assert b"detail" not in body
        assert auth.calls == application.calls == []
        assert len(audit.events) == 1
        assert ids.calls == 1


def test_raw_asgi_body_boundaries_and_disconnect() -> None:
    exact = b'{"message":"x"}' + b" " * (256 - len(b'{"message":"x"}'))
    scenarios = (
        ([{"type": "http.request", "body": exact, "more_body": False}], None, 200),
        (
            [
                {"type": "http.request", "body": b"a", "more_body": index < 256}
                for index in range(257)
            ],
            None,
            413,
        ),
        (
            [{"type": "http.request", "body": b"x" * 257, "more_body": False}],
            [(b"content-length", b"1")],
            413,
        ),
        ([{"type": "http.disconnect"}], None, 400),
        ([{"type": "lifespan.startup"}], None, 400),
    )
    for messages, added_headers, expected in scenarios:
        app, auth, application, audit, _, _ = build(transport_config=config(maximum_body_bytes=256))
        headers = [
            (b"host", b"erp.internal"),
            (b"authorization", b"Bearer synthetic"),
            (b"content-type", b"application/json"),
            *(added_headers or []),
        ]
        status, _, _ = asyncio.run(_raw_asgi_exchange(app, headers=headers, messages=messages))
        assert status == expected
        if expected == 200:
            assert len(auth.calls) == len(application.calls) == 1
            assert audit.events == []
        else:
            assert auth.calls == application.calls == []
            assert len(audit.events) == 1


def test_raw_header_and_content_length_ambiguities_fail_closed() -> None:
    from erp_ai.transport.http.app import (
        _bearer_assertion,
        _validate_envelope,
        _validate_media,
    )

    for headers in (
        [],
        [(b"host", b"erp.internal"), (b"host", b"erp.internal")],
        [(b"host", b"\xff")],
        [(b"host", b"")],
        [(b"host", b"user@erp.internal")],
        [(b"host", b"erp.internal:")],
    ):
        with pytest.raises(StrictRequestError):
            _validate_envelope(_raw_request(headers), config())
    with pytest.raises(IngressAuthenticationDenied):
        _bearer_assertion(
            _raw_request([(b"host", b"erp.internal"), (b"authorization", b"Bearer \xff")]),
            4096,
        )
    media_prefix = [
        (b"host", b"erp.internal"),
        (b"authorization", b"Bearer a"),
    ]
    cases = (
        (media_prefix, LookupError),
        ([*media_prefix, (b"content-type", b"\xff")], LookupError),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b"1"),
                (b"content-length", b"1"),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b"1,1"),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b"+1"),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b" 1"),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b"9" * 10_000),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b"1"),
                (b"transfer-encoding", b"chunked"),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-type", b"application/json"),
            ],
            LookupError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-encoding", b"identity"),
                (b"content-encoding", b"identity"),
            ],
            LookupError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"transfer-encoding", b"compress"),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json;charset=utf-8;charset=utf-8"),
            ],
            LookupError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b"bad"),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b"\xff"),
            ],
            StrictRequestError,
        ),
        (
            [
                *media_prefix,
                (b"content-type", b"application/json"),
                (b"content-length", b"-1"),
            ],
            StrictRequestError,
        ),
    )
    for headers, exception in cases:
        with pytest.raises(exception):
            _validate_media(_raw_request(headers), 256)


@pytest.mark.parametrize(
    "scope_changes",
    (
        {"method": "PUT"},
        {"query_string": b"="},
        {"query_string": b"%00="},
        {"path": "/v1/chat/", "raw_path": b"/v1/chat/"},
        {"path": "/v1/chat", "raw_path": b"/v1%2Fchat"},
        {"path": "/v1/chat", "raw_path": b"//v1/chat"},
        {"path": "/v1/chat", "raw_path": b"/v1/./chat"},
        {"path": "/v1/chat", "raw_path": b"/v1/chat;parameter"},
        {"path": "/v1/chat", "raw_path": b"/v1/chat/.."},
        {"path": "/v1/chat", "raw_path": b"/different"},
    ),
)
def test_raw_route_and_query_variants_fail_exact_envelope(scope_changes: dict[str, object]) -> None:
    from erp_ai.transport.http.app import _validate_envelope

    raw = _raw_request([(b"host", b"erp.internal")], scope_changes=scope_changes)
    with pytest.raises(StrictRequestError):
        _validate_envelope(raw, config())


def test_raw_authorization_ambiguities_fail_closed() -> None:
    from erp_ai.transport.http.app import _bearer_assertion

    invalid_values = (
        b"Bearer one,two",
        b"Bearer one\ttwo",
        b"Bearer one\r\ntwo",
        b"Bearer \x01",
        b"Bearer \xff",
    )
    for value in invalid_values:
        with pytest.raises(IngressAuthenticationDenied):
            _bearer_assertion(
                _raw_request([(b"host", b"erp.internal"), (b"AuThOrIzAtIoN", value)]),
                4096,
            )
    with pytest.raises(IngressAuthenticationDenied):
        _bearer_assertion(
            _raw_request(
                [
                    (b"host", b"erp.internal"),
                    (b"Authorization", b"Bearer one"),
                    (b"authorization", b"Bearer two"),
                ]
            ),
            4096,
        )


def test_raw_body_stream_limits_disconnect_types_and_single_consumption() -> None:
    from erp_ai.transport.http.app import _read_body

    async def read(messages: list[dict[str, object]], limit: int) -> tuple[bytes, int]:
        calls = 0

        async def receive() -> dict[str, object]:
            nonlocal calls
            message = messages[calls]
            calls += 1
            return message

        raw = _raw_request([], receive=receive)
        return await _read_body(raw, limit), calls

    exact, calls = asyncio.run(
        read(
            [
                {"type": "http.request", "body": b"a" * 128, "more_body": True},
                {"type": "http.request", "body": b"b" * 128, "more_body": False},
            ],
            256,
        )
    )
    assert len(exact) == 256 and calls == 2
    many = [
        {"type": "http.request", "body": b"a", "more_body": index < 256} for index in range(257)
    ]
    with pytest.raises(OverflowError):
        asyncio.run(read(many, 256))
    for message in (
        {"type": "http.disconnect"},
        {"type": "websocket.receive", "bytes": b"x"},
        {"type": "http.request", "body": "not-bytes", "more_body": False},
        {"type": "http.request", "body": b"x", "more_body": 1},
    ):
        with pytest.raises(StrictRequestError):
            asyncio.run(read([message], 256))


def test_read_body_propagates_cancellation_and_other_receive_failure() -> None:
    from erp_ai.transport.http.app import _read_body

    class BrokenRequest:
        def __init__(self, failure: BaseException) -> None:
            self.failure = failure

        async def receive(self):  # type: ignore[no-untyped-def]
            raise self.failure

    async def exercise() -> None:
        with pytest.raises(asyncio.CancelledError):
            await _read_body(BrokenRequest(asyncio.CancelledError()), 256)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError):
            await _read_body(BrokenRequest(RuntimeError("private")), 256)  # type: ignore[arg-type]

    asyncio.run(exercise())


def test_http_and_unhandled_exception_handlers_are_stable() -> None:
    app, _, _, audit, _, _ = build()
    http_handler = app.exception_handlers[HTTPException]
    exception_handler = app.exception_handlers[Exception]
    raw = _raw_request([(b"host", b"erp.internal")])

    async def exercise() -> None:
        method = await http_handler(raw, HTTPException(status_code=405))
        missing = await http_handler(raw, HTTPException(status_code=404))
        internal = await exception_handler(raw, RuntimeError("private"))
        assert (method.status_code, missing.status_code, internal.status_code) == (405, 404, 500)
        assert [event.internal_reason for event in audit.events] == [
            "request_method_not_allowed",
            "request_route_not_found",
            "unhandled_transport_failure",
        ]

    asyncio.run(exercise())


def test_exception_handlers_fail_closed_when_request_id_generation_fails() -> None:
    app, _, _, _, _, _ = build(ids=Ids("invalid"))
    http_handler = app.exception_handlers[HTTPException]
    exception_handler = app.exception_handlers[Exception]
    raw = _raw_request([(b"host", b"erp.internal")])

    async def exercise() -> None:
        missing = await http_handler(raw, HTTPException(status_code=404))
        internal = await exception_handler(raw, RuntimeError("private"))
        assert missing.headers["x-request-id"] == "unavailable"
        assert internal.headers["x-request-id"] == "unavailable"

    asyncio.run(exercise())


def test_unhandled_exception_audit_failure_withholds_generic_error() -> None:
    app, _, _, audit, _, _ = build(audit=Audit(RuntimeError("private")))
    exception_handler = app.exception_handlers[Exception]
    raw = _raw_request([(b"host", b"erp.internal")])

    async def exercise() -> None:
        response = await exception_handler(raw, RuntimeError("private"))
        assert response.status_code == 503
        assert b"private" not in response.body

    asyncio.run(exercise())
    assert len(audit.events) == 1


def test_chat_endpoint_handles_media_and_receive_failures_without_leakage() -> None:
    async def invoke(
        built: Any,
        *,
        extra_headers: tuple[tuple[bytes, bytes], ...] = (),
        receive_failure: BaseException | None = None,
    ) -> Response:
        route = next(route for route in built.routes if getattr(route, "path", None) == "/v1/chat")

        async def receive() -> dict[str, object]:
            if receive_failure is not None:
                raise receive_failure
            return {"type": "http.request", "body": b'{"message":"Hello"}', "more_body": False}

        raw = _raw_request(
            [
                (b"host", b"erp.internal"),
                (b"authorization", b"Bearer a"),
                (b"content-type", b"application/json"),
                *extra_headers,
            ]
        )
        raw._receive = receive
        async with built.router.lifespan_context(built):
            return await route.endpoint(raw)

    malformed_app, *_ = build()
    malformed = asyncio.run(invoke(malformed_app, extra_headers=((b"content-length", b"invalid"),)))
    assert malformed.status_code == 400

    failed_app, *_ = build()
    failed = asyncio.run(invoke(failed_app, receive_failure=RuntimeError("private_receive")))
    assert failed.status_code == 400
    assert b"private_receive" not in failed.body

    cancelled_app, *_ = build()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(invoke(cancelled_app, receive_failure=asyncio.CancelledError()))


def test_handler_cancellation_from_authenticator_and_application_propagates() -> None:
    from erp_ai.transport.http.app import _in_flight_request_id_count

    async def invoke(built: Any) -> None:
        route = next(route for route in built.routes if getattr(route, "path", None) == "/v1/chat")
        body = b'{"message":"Hello"}'
        sent = False

        async def receive() -> dict[str, object]:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        raw = _raw_request(
            [
                (b"host", b"erp.internal"),
                (b"authorization", b"Bearer a"),
                (b"content-type", b"application/json"),
            ]
        )
        raw._receive = receive
        async with built.router.lifespan_context(built):
            with pytest.raises(asyncio.CancelledError):
                await route.endpoint(raw)

    auth_app, *_ = build(auth=Authenticator(asyncio.CancelledError()))
    application_app, *_ = build(application=Application(asyncio.CancelledError()))
    asyncio.run(invoke(auth_app))
    asyncio.run(invoke(application_app))
    assert _in_flight_request_id_count(auth_app.state._erp_ai_transport_state) == 0
    assert _in_flight_request_id_count(application_app.state._erp_ai_transport_state) == 0
