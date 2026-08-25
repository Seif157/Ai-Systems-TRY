"""Opaque, signed, authorization-bound leave-request cursor."""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from erp_ai.capabilities.leave.models import LeaveRequestStatus
from erp_ai.infrastructure.postgres_erp.config import ErpCursorKeyring
from erp_ai.infrastructure.postgres_erp.errors import InvalidErpCursor

_MAX_CURSOR_SIZE = 512


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _digest(value: str) -> str:
    return _b64(hashlib.sha256(value.encode()).digest()[:16])


def _binding(key: bytes, value: str) -> str:
    return _b64(hmac.digest(key, value.encode(), "sha256")[:16])


def filter_digest(
    statuses: tuple[LeaveRequestStatus, ...], start_from: object, start_to: object
) -> str:
    payload = json.dumps(
        [tuple(status.value for status in statuses), str(start_from or ""), str(start_to or "")],
        separators=(",", ":"),
    )
    return _digest(payload)


@dataclass(frozen=True, slots=True)
class CursorPosition:
    snapshot_ceiling: datetime
    submitted_at: datetime
    request_id: UUID


class SignedLeaveRequestCursor:
    __slots__ = ("_clock", "_keyring")

    def __init__(
        self, keyring: ErpCursorKeyring, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._keyring = keyring
        self._clock = clock

    def encode(
        self,
        *,
        customer_environment_id: str,
        employee_id: str,
        legal_entity_ids: tuple[str, ...],
        authorization_snapshot_id: str,
        filters_digest: str,
        limit: int,
        position: CursorPosition,
    ) -> str:
        now = int(self._clock())
        key = self._keyring.active
        raw_key = key.decoded()
        payload = {
            "v": 1,
            "k": key.key_id,
            "i": now,
            "e": now + self._keyring.ttl_seconds,
            "s": position.snapshot_ceiling.isoformat(),
            "t": position.submitted_at.isoformat(),
            "r": position.request_id.hex,
            "f": filters_digest,
            "c": _binding(raw_key, customer_environment_id),
            "u": _binding(raw_key, employee_id),
            "l": _digest("\0".join(sorted(legal_entity_ids))),
            "a": _binding(raw_key, authorization_snapshot_id),
            "n": limit,
        }
        body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        signature = _b64(hmac.digest(raw_key, body.encode(), "sha256"))
        cursor = f"{body}.{signature}"
        if len(cursor) > _MAX_CURSOR_SIZE:
            raise InvalidErpCursor("invalid leave request cursor")
        return cursor

    def decode(
        self,
        cursor: str,
        *,
        customer_environment_id: str,
        employee_id: str,
        legal_entity_ids: tuple[str, ...],
        authorization_snapshot_id: str,
        filters_digest: str,
        limit: int,
    ) -> CursorPosition:
        try:
            if len(cursor) > _MAX_CURSOR_SIZE or cursor.count(".") != 1:
                raise ValueError
            body, encoded_signature = cursor.split(".")
            payload: dict[str, Any] = json.loads(_unb64(body))
            key_id = payload["k"]
            keys = (self._keyring.active, *self._keyring.previous)
            key = next(item for item in keys if item.key_id == key_id)
            raw_key = key.decoded()
            expected = hmac.digest(raw_key, body.encode(), "sha256")
            if not hmac.compare_digest(expected, _unb64(encoded_signature)):
                raise ValueError
            now = int(self._clock())
            expected_keys = {"v", "k", "i", "e", "s", "t", "r", "f", "c", "u", "l", "a", "n"}
            if set(payload) != expected_keys or payload["v"] != 1:
                raise ValueError
            if not payload["i"] <= now <= payload["e"]:
                raise ValueError
            checks = (
                payload["f"] == filters_digest,
                payload["c"] == _binding(raw_key, customer_environment_id),
                payload["u"] == _binding(raw_key, employee_id),
                payload["l"] == _digest("\0".join(sorted(legal_entity_ids))),
                payload["a"] == _binding(raw_key, authorization_snapshot_id),
                payload["n"] == limit,
            )
            if not all(checks):
                raise ValueError
            return CursorPosition(
                snapshot_ceiling=datetime.fromisoformat(payload["s"]),
                submitted_at=datetime.fromisoformat(payload["t"]),
                request_id=UUID(hex=payload["r"]),
            )
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError):
            raise InvalidErpCursor("invalid leave request cursor") from None
