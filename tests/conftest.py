from collections.abc import Mapping
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class StubTrustedSource:
    claims: Mapping[str, object]

    def load_context(self) -> Mapping[str, object]:
        return self.claims


@pytest.fixture
def valid_claims() -> dict[str, object]:
    return {
        "request_id": "req_01JABC",
        "customer_environment_id": "cust_env_a",
        "user_id": "9842",
        "employee_id": "3e2f8df0-7ae1-4eed-a1e8-c177b6c23f21",
        "roles": ["manager", "employee"],
        "legal_entity_ids": ["entity-b", "entity-a"],
        "enabled_modules": ["leave", "hr_core"],
        "locale": "ar-eg",
        "purpose": "employee_self_service",
    }
