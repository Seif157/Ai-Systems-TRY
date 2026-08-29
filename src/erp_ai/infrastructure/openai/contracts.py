"""Frozen provider wire and policy constants and canonical contract identity."""

import json
from copy import deepcopy
from typing import Final

OPENAI_ORIGIN: Final = "https://api.openai.com"
OPENAI_RESPONSES_PATH: Final = "/v1/responses"
OPENAI_EMBEDDINGS_PATH: Final = "/v1/embeddings"
OPENAI_ALLOWED_ENDPOINTS: Final = (OPENAI_RESPONSES_PATH, OPENAI_EMBEDDINGS_PATH)
OPENAI_ATTESTATION_CONTRACT_VERSION: Final = "1.0.0"
OPENAI_USAGE_CLASSIFICATION: Final = "production_zdr_only"
OPENAI_PROVIDER_CONTRACT_VERSION: Final = "1.0.0"

# This insertion order is part of the contract. Canonicalization deliberately does not sort keys
# and does not depend on Pydantic JSON Schema generation.
OPENAI_PROVIDER_CONTRACT: Final[dict[str, object]] = {
    "domain": "erp_ai.openai.production_provider",
    "version": OPENAI_PROVIDER_CONTRACT_VERSION,
    "origin": OPENAI_ORIGIN,
    "endpoints": [
        {"method": "POST", "path": OPENAI_RESPONSES_PATH},
        {"method": "POST", "path": OPENAI_EMBEDDINGS_PATH},
    ],
    "headers": {
        "required": [
            "Authorization",
            "OpenAI-Organization",
            "OpenAI-Project",
            "Content-Type",
            "Accept",
            "Accept-Encoding",
            "Content-Length",
        ],
        "forbidden": [
            "customer_environment_id",
            "user_id",
            "employee_id",
            "authorization_snapshot_id",
            "request_id",
            "purpose",
            "roles",
            "permissions",
            "enabled_modules",
        ],
    },
    "responses": {
        "common_fields": [
            "model",
            "input",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "reasoning",
            "text",
            "max_output_tokens",
            "store",
            "stream",
            "background",
        ],
        "fixed_values": {
            "store": False,
            "stream": False,
            "background": False,
            "parallel_tool_calls": False,
        },
        "modes": {
            "general": {"tools": 0, "tool_choice": "none"},
            "forced": {"tools": 1, "tool_choice": "exact_named_function"},
            "final": {"tools": 0, "tool_choice": "none", "interactions": 1},
        },
        "allowed_output_items": {
            "general": ["message.output_text"],
            "forced": ["function_call"],
            "final": ["message.output_text"],
        },
        "reasoning_output_policy": "reject",
    },
    "embeddings": {
        "request_fields": ["model", "input", "dimensions", "encoding_format"],
        "input_count": 1,
        "encoding_format": "float",
        "dimension_policy": "exact_configured_step28_dimension",
        "response_projection": ["model", "data[0].index", "data[0].embedding"],
    },
    "privacy": {
        "retention_mode": "zero_data_retention",
        "training_data_sharing_opt_in": False,
        "classification_policy": "server_monotonic_max_restricted_highly_restricted_denied",
        "customer_project_isolation": "one_customer_one_exact_project_no_default",
        "credential_order": "authorize_then_resolve_once_then_send_once",
    },
    "prohibitions": {
        "retry": True,
        "fallback": True,
        "response_storage": True,
        "api_streaming": True,
        "background": True,
        "hosted_tools": True,
        "provider_state": True,
    },
    "lifecycle": {
        "construction_io": False,
        "startup_provider_request": False,
        "open_at_most_once": True,
        "close_at_most_once": True,
        "isolated_runtime_state": True,
    },
}


def canonical_openai_provider_contract_bytes(
    descriptor: dict[str, object] | None = None,
) -> bytes:
    """Return compact insertion-ordered finite UTF-8 JSON with no trailing newline."""

    value = deepcopy(OPENAI_PROVIDER_CONTRACT if descriptor is None else descriptor)
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=False, allow_nan=False
    ).encode("utf-8")


OPENAI_PROVIDER_CONTRACT_DIGEST: Final = (
    "04560be15e5927e68a35fad77fd8b25c9598bde693971944bac4562a4a0fa51d"
)

FINAL_ANSWER_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "response_type",
        "answer",
        "answer_basis",
        "evidence_call_ids",
        "citation_ids",
    ],
    "properties": {
        "response_type": {"type": "string", "const": "final_answer"},
        "answer": {"type": "string", "minLength": 1, "maxLength": 8000},
        "answer_basis": {
            "type": "string",
            "enum": ["general", "knowledge", "erp_data", "mixed"],
        },
        "evidence_call_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 128},
            "maxItems": 4,
            "uniqueItems": True,
        },
        "citation_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 128},
            "maxItems": 20,
            "uniqueItems": True,
        },
    },
}
