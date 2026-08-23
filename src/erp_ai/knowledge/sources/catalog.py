"""Standard-library TOML parsing for the trusted source allowlist."""

import tomllib
from typing import Any
from uuid import UUID

from erp_ai.knowledge.sources.models import MarkdownSourceCatalog


def parse_source_catalog(raw_catalog: bytes) -> MarkdownSourceCatalog:
    """Parse catalog bytes without discovering or reading any source file."""

    data: dict[str, Any] = tomllib.loads(raw_catalog.decode("utf-8-sig"))
    entries = data.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("document_id"), str):
                entry["document_id"] = UUID(entry["document_id"])
    return MarkdownSourceCatalog.model_validate(data)
