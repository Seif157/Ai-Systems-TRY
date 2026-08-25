import base64
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr

from erp_ai.capabilities.leave.models import LeaveRequestStatus
from erp_ai.infrastructure.postgres_erp.config import ErpCursorKey, ErpCursorKeyring
from erp_ai.infrastructure.postgres_erp.cursor import (
    CursorPosition,
    SignedLeaveRequestCursor,
    filter_digest,
)
from erp_ai.infrastructure.postgres_erp.errors import InvalidErpCursor


def key(key_id: str, fill: bytes) -> ErpCursorKey:
    return ErpCursorKey(
        key_id=key_id,
        key_base64=SecretStr(base64.b64encode(fill * 32).decode()),
    )


def values() -> dict[str, object]:
    return {
        "customer_environment_id": "customer_a",
        "employee_id": "00000000-0000-4000-8000-000000000001",
        "legal_entity_ids": ("00000000-0000-4000-8000-000000000002",),
        "authorization_snapshot_id": "snapshot_a",
        "filters_digest": filter_digest((LeaveRequestStatus.PENDING,), None, None),
        "limit": 20,
    }


def test_signed_cursor_round_trip_rotation_and_opaque_payload() -> None:
    old = key("old", b"o")
    old_codec = SignedLeaveRequestCursor(ErpCursorKeyring(active=old), clock=lambda: 1000)
    position = CursorPosition(
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2025, 12, 1, tzinfo=UTC),
        UUID("00000000-0000-4000-8000-000000000003"),
    )
    token = old_codec.encode(**values(), position=position)
    rotated = SignedLeaveRequestCursor(
        ErpCursorKeyring(active=key("new", b"n"), previous=(old,)), clock=lambda: 1000
    )
    assert rotated.decode(token, **values()) == position
    assert len(token) <= 512
    assert "customer_a" not in token and "snapshot_a" not in token


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("customer_environment_id", "customer_b"),
        ("employee_id", "00000000-0000-4000-8000-000000000009"),
        ("legal_entity_ids", ("00000000-0000-4000-8000-000000000009",)),
        ("authorization_snapshot_id", "snapshot_b"),
        ("filters_digest", "f" * 43),
        ("limit", 21),
    ],
)
def test_cursor_scope_changes_fail_generically(field: str, replacement: object) -> None:
    codec = SignedLeaveRequestCursor(
        ErpCursorKeyring(active=key("active", b"a")), clock=lambda: 1000
    )
    token = codec.encode(
        **values(),
        position=CursorPosition(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
            UUID("00000000-0000-4000-8000-000000000003"),
        ),
    )
    changed = {**values(), field: replacement}
    with pytest.raises(InvalidErpCursor, match="invalid leave request cursor"):
        codec.decode(token, **changed)


def test_cursor_tampering_expiration_unknown_key_and_malformed_values_fail() -> None:
    codec = SignedLeaveRequestCursor(
        ErpCursorKeyring(active=key("active", b"a"), ttl_seconds=30), clock=lambda: 1000
    )
    token = codec.encode(
        **values(),
        position=CursorPosition(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
            UUID("00000000-0000-4000-8000-000000000003"),
        ),
    )
    for bad in ("x", "x.y.z", token[:-1] + ("A" if token[-1] != "A" else "B"), "x" * 513):
        with pytest.raises(InvalidErpCursor):
            codec.decode(bad, **values())
    expired = SignedLeaveRequestCursor(
        ErpCursorKeyring(active=key("active", b"a"), ttl_seconds=30), clock=lambda: 2000
    )
    with pytest.raises(InvalidErpCursor):
        expired.decode(token, **values())
    unknown = SignedLeaveRequestCursor(
        ErpCursorKeyring(active=key("other", b"b")), clock=lambda: 1000
    )
    with pytest.raises(InvalidErpCursor):
        unknown.decode(token, **values())


def test_cursor_rejects_resigned_unknown_or_wrong_version_payload() -> None:
    active = key("active", b"a")
    codec = SignedLeaveRequestCursor(ErpCursorKeyring(active=active), clock=lambda: 1000)
    token = codec.encode(
        **values(),
        position=CursorPosition(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, tzinfo=UTC),
            UUID("00000000-0000-4000-8000-000000000003"),
        ),
    )
    body = token.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    for mutation in (
        {**payload, "v": 2},
        {key: value for key, value in payload.items() if key != "n"},
    ):
        encoded = (
            base64.urlsafe_b64encode(
                json.dumps(mutation, sort_keys=True, separators=(",", ":")).encode()
            )
            .rstrip(b"=")
            .decode()
        )
        signature = (
            base64.urlsafe_b64encode(hmac.digest(active.decoded(), encoded.encode(), "sha256"))
            .rstrip(b"=")
            .decode()
        )
        with pytest.raises(InvalidErpCursor):
            codec.decode(f"{encoded}.{signature}", **values())


def test_cursor_fails_closed_if_validated_metadata_exceeds_envelope_budget() -> None:
    codec = SignedLeaveRequestCursor(
        ErpCursorKeyring(active=key("k" * 128, b"a")), clock=lambda: 1000
    )
    with pytest.raises(InvalidErpCursor):
        codec.encode(
            **values(),
            position=CursorPosition(
                datetime(9999, 12, 31, tzinfo=UTC),
                datetime(9999, 12, 31, tzinfo=UTC),
                UUID("00000000-0000-4000-8000-000000000003"),
            ),
        )
