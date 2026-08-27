# ERP-signed request assertion

The ERP alone signs compact JWS assertions. Production AI code contains verification only and
receives static Ed25519 public keys; ERP private keys must never enter this repository or the AI
deployment. The protected header is exactly `alg`, `kid`, `typ`, with `EdDSA`, a configured
canonical key ID, and `erp-ai-request+jws`. No other algorithm, header, JWKS lookup, or discovery
mechanism is accepted.

The payload is exactly `v`, `iss`, `aud`, `jti`, `iat`, `exp`, `method`, `path`, `body_sha256`, and
`resolver_ref`. Version is integer `1`; audience is one string; JTI is lowercase UUIDv4; NumericDate
values are integer UTC seconds; method/path are `POST` and `/v1/chat`; the digest is 64 lowercase
hexadecimal characters; and the unpadded canonical base64url reference is 43 characters encoding
32 bytes. This proves structural 256-bit capacity only; the ERP issuer remains responsible for
cryptographically secure random generation. It contains no identity, authorization, context,
route, intent, tool, message, or response data.

Parsing is a strict three-segment ASCII profile with bounded canonical base64url, strict UTF-8 JSON,
duplicate/unknown-field rejection, and a 64-byte Ed25519 signature over the original encoded header
and payload. Verification captures an injected aware clock exactly once. It requires `exp > iat`,
`exp - iat <= maximum_lifetime`, `iat <= now + maximum_clock_skew`, and
`exp > now - maximum_clock_skew`; equality at the expiry boundary is expired. Key validity requires
`activation <= iat`, `iat < retirement`, and `exp <= retirement`. Exact maximum-lifetime,
future-skew, activation, and retirement boundaries are accepted. Overlapping key windows enable
rotation; strictly validated `kid` selects one startup-parsed configured key. There is no default,
first-key fallback, filesystem/environment key loading, refresh task, or remote key.

The authenticator returns only the AI-generated request ID and opaque resolver reference. Assertion,
signature, JTI, key ID, claims, and digest are discarded. ERP owns atomic one-time consumption; AI
keeps no replay cache. Assertion rejection is generic and produces one transport-owned application
audit, with no downstream application, agent, or tool audit.
