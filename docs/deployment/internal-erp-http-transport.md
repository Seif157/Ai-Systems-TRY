# Deploying the internal ERP HTTP transport

Construct the FastAPI application only through `create_internal_http_app`. Supply the exact host
allowlist, HTTPS policy, bounded limits, production authenticator, request-ID factory, trusted
application, mandatory application audit sink, and lifecycle owner explicitly. There is no global
application, no production no-op, no environment reader, and no Uvicorn launcher in this step.

Expose `/v1/chat` only from the trusted ERP backend network path. Swagger, ReDoc, OpenAPI, CORS,
sessions, trailing-slash redirects, WebSockets, SSE, compression handling, and background tasks are
disabled or absent. `/health/live` performs no external I/O; `/health/ready` reports only lifecycle
readiness and discloses no dependency details.

Chat execution is unavailable until the injected lifecycle has completed startup. An unready chat
attempt receives a generic audited `503` without invoking authentication or the trusted
application. Readiness is cleared before lifecycle shutdown begins. Lifecycle ownership includes
any cleanup needed after partial startup; the transport does not invent or run dependency-specific
cleanup.

If TLS terminates at a proxy, that proxy and the ASGI server must be configured as one reviewed
deployment boundary. The application deliberately does not trust `Forwarded`,
`X-Forwarded-For`, or `X-Forwarded-Proto` for authentication or identity. Reverse-proxy header
sanitization, mTLS, connection/time limits, request rate limits, secret management, and network
policy remain deployment responsibilities and do not replace the ERP assertion.

A real ERP authenticator/resolver remains future integration work. It must bind the opaque
assertion to issuer, audience, time, replay policy, exact method/route, and canonical body digest.
Production startup must compose approved ERP/model/storage dependencies separately; the current
free OpenRouter model remains synthetic-test-only and is never constructed by this transport.
