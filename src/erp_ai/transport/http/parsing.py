"""Bounded strict parsing and canonical request authentication binding."""

import hashlib
import json
from typing import Any, Final

from pydantic import ValidationError

from erp_ai.api import PublicChatRequest

INGRESS_DIGEST_DOMAIN: Final = "erp-ai:internal-http-chat:v1"
INGRESS_DIGEST_CONTRACT_VERSION: Final = 1


class StrictRequestError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictRequestError("invalid JSON object")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise StrictRequestError("invalid JSON number")


def parse_public_chat_request(body: bytes) -> PublicChatRequest:
    if not body:
        raise StrictRequestError("empty request body")
    if body.startswith(b"\xef\xbb\xbf"):
        raise StrictRequestError("UTF-8 BOM is forbidden")
    try:
        text = body.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, StrictRequestError):
        raise StrictRequestError("invalid JSON request") from None
    if type(value) is not dict:
        raise StrictRequestError("JSON root must be an object")
    try:
        return PublicChatRequest.model_validate(value, strict=True)
    except ValidationError:
        raise StrictRequestError("invalid public chat request") from None


def canonical_public_chat_bytes(request: PublicChatRequest) -> bytes:
    return _canonical_public_chat_bytes(
        request,
        domain=INGRESS_DIGEST_DOMAIN,
        contract_version=INGRESS_DIGEST_CONTRACT_VERSION,
        method="POST",
        raw_route=b"/v1/chat",
    )


def _canonical_public_chat_bytes(
    request: PublicChatRequest,
    *,
    domain: str,
    contract_version: int,
    method: str,
    raw_route: bytes,
) -> bytes:
    validated = PublicChatRequest.model_validate(request.model_dump(mode="python"), strict=True)
    try:
        route_path = raw_route.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        raise StrictRequestError("invalid canonical route") from None
    payload = {
        "domain": domain,
        "contract_version": contract_version,
        "method": method,
        "route_path": route_path,
        "request": {
            "message": validated.message,
            "stream": validated.stream,
            "preferred_response_language": validated.preferred_response_language,
        },
    }
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False, allow_nan=False
    ).encode("utf-8")


def canonical_public_chat_digest(request: PublicChatRequest) -> str:
    return hashlib.sha256(canonical_public_chat_bytes(request)).hexdigest()
