"""Strict compact-JWS parsing for the single approved ERP assertion profile."""

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any

_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
HEADER_FIELDS = frozenset(("alg", "kid", "typ"))
PAYLOAD_FIELDS = frozenset(
    ("v", "iss", "aud", "jti", "iat", "exp", "method", "path", "body_sha256", "resolver_ref")
)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise ValueError("invalid JSON number")


def decode_segment(value: str, maximum_bytes: int) -> bytes:
    if not value or len(value) > maximum_bytes or "=" in value or not _B64URL.fullmatch(value):
        raise ValueError("invalid compact JWS segment")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise ValueError("non-canonical compact JWS segment")
    return decoded


def strict_object(value: bytes, fields: frozenset[str]) -> dict[str, object]:
    if value.startswith(b"\xef\xbb\xbf"):
        raise ValueError("JSON BOM is forbidden")
    text = value.decode("utf-8", errors="strict")
    root = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(root, dict) or set(root) != fields:
        raise ValueError("invalid JSON object contract")
    return root


@dataclass(frozen=True, slots=True)
class ParsedAssertion:
    header: dict[str, object] = field(repr=False)
    payload: dict[str, object] = field(repr=False)
    signing_input: bytes = field(repr=False)
    signature: bytes = field(repr=False)


def parse_compact_jws(
    token: str, maximum_token_bytes: int, maximum_segment_bytes: int
) -> ParsedAssertion:
    raw = token.encode("ascii", errors="strict")
    if len(raw) > maximum_token_bytes:
        raise ValueError("compact JWS is too large")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("compact JWS must have three segments")
    header_bytes, payload_bytes, signature = (
        decode_segment(part, maximum_segment_bytes) for part in parts
    )
    if len(signature) != 64:
        raise ValueError("invalid Ed25519 signature length")
    header = strict_object(header_bytes, HEADER_FIELDS)
    payload = strict_object(payload_bytes, PAYLOAD_FIELDS)
    return ParsedAssertion(header, payload, f"{parts[0]}.{parts[1]}".encode("ascii"), signature)


def valid_body_digest(value: Any) -> bool:
    return isinstance(value, str) and _HEX.fullmatch(value) is not None
