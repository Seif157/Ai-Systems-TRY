from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


@dataclass(frozen=True)
class FakeTrustedContextProvider:
    claims: Mapping[str, object]

    def load_context(self) -> Mapping[str, object]:
        return self.claims


@pytest.fixture
def valid_claims() -> dict[str, object]:
    return {
        "context_version": 1,
        "request_id": "req_01JABC",
        "customer_environment_id": "cust_env_a",
        "user_id": "9842",
        "employee_id": "3e2f8df0-7ae1-4eed-a1e8-c177b6c23f21",
        "roles": ["manager", "employee"],
        "permission_codes": ["leave_read", "profile_read"],
        "legal_entity_ids": ["entity-b", "entity-a"],
        "enabled_modules": ["leave", "hr_core"],
        "locale": "ar-eg",
        "timezone": "Africa/Cairo",
        "purpose": "employee_self_service",
        "issued_at": datetime(2026, 8, 21, 12, 0, tzinfo=ZoneInfo("Africa/Cairo")),
        "authorization_snapshot_id": "authz_snap_01JABC",
    }
