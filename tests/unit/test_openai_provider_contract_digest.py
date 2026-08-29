import hashlib
import json
from copy import deepcopy

import pytest

from erp_ai.infrastructure.openai.contracts import (
    OPENAI_PROVIDER_CONTRACT,
    OPENAI_PROVIDER_CONTRACT_DIGEST,
    OPENAI_PROVIDER_CONTRACT_VERSION,
    canonical_openai_provider_contract_bytes,
)

EXPECTED_DIGEST = "04560be15e5927e68a35fad77fd8b25c9598bde693971944bac4562a4a0fa51d"


def _mutated(path: tuple[object, ...], value: object) -> dict[str, object]:
    descriptor = deepcopy(OPENAI_PROVIDER_CONTRACT)
    target: object = descriptor
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    return descriptor


def test_canonical_contract_golden_bytes_and_digest() -> None:
    raw = canonical_openai_provider_contract_bytes()
    assert OPENAI_PROVIDER_CONTRACT_VERSION == "1.0.0"
    assert not raw.endswith(b"\n")
    assert (
        raw
        == json.dumps(
            OPENAI_PROVIDER_CONTRACT,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
            allow_nan=False,
        ).encode()
    )
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_DIGEST
    assert OPENAI_PROVIDER_CONTRACT_DIGEST == EXPECTED_DIGEST


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("origin",), "https://invalid.example"),
        (("endpoints", 0, "path"), "/v1/invalid"),
        (("headers", "required", 0), "Invalid"),
        (("responses", "fixed_values", "store"), True),
        (("responses", "fixed_values", "stream"), True),
        (("responses", "fixed_values", "background"), True),
        (("responses", "fixed_values", "parallel_tool_calls"), True),
        (("privacy", "retention_mode"), "standard"),
        (("responses", "modes", "forced", "tool_choice"), "auto"),
        (("responses", "allowed_output_items", "general", 0), "reasoning"),
        (("embeddings", "dimension_policy"), "provider_default"),
        (("privacy", "classification_policy"), "caller_selected"),
        (("privacy", "customer_project_isolation"), "shared_default"),
    ],
)
def test_contract_security_changes_alter_digest(path: tuple[object, ...], value: object) -> None:
    changed = canonical_openai_provider_contract_bytes(_mutated(path, value))
    assert hashlib.sha256(changed).hexdigest() != OPENAI_PROVIDER_CONTRACT_DIGEST
