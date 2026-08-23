from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from erp_ai.knowledge.sources import parse_source_catalog


def catalog_bytes(
    *, version: int = 1, path: str = "product/hr/leave.md", document_version: str = "1.0.0"
) -> bytes:
    return f'''catalog_version = {version}
[[entries]]
path = "{path}"
raw_sha256 = "{"a" * 64}"
document_id = "00000000-0000-0000-0000-000000000001"
document_version = "{document_version}"
namespace = "hr"
source_type = "product_documentation"
title = "Leave guide"
language = "en"
modules = ["hr_core", "leave"]
permissions = ["leave.policy.read"]
allowed_purposes = ["employee_self_service"]
legal_entities = []
classification = "internal"
effective_from = 2026-01-01T00:00:00Z
approval_reference = "approval-1"
approved_at = 2026-01-01T00:00:00Z
'''.encode()


def test_catalog_parses_strict_immutable_metadata() -> None:
    catalog = parse_source_catalog(b"\xef\xbb\xbf" + catalog_bytes())
    entry = catalog.entries[0]
    assert catalog.catalog_version == 1
    assert entry.document_id == UUID("00000000-0000-0000-0000-000000000001")
    assert entry.effective_from == datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        entry.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("version", [0, 2])
def test_catalog_rejects_unsupported_version(version: int) -> None:
    with pytest.raises(ValidationError):
        parse_source_catalog(catalog_bytes(version=version))


@pytest.mark.parametrize(
    "document_version",
    ("1", "1.0", "01.0.0", "1.0.0-alpha", "1.0.0+build", " 1.0.0 "),
)
def test_catalog_rejects_noncanonical_document_version(document_version: str) -> None:
    with pytest.raises(ValidationError):
        parse_source_catalog(catalog_bytes(document_version=document_version))


@pytest.mark.parametrize(
    "path", ["/outside.md", "C:/outside.md", "../outside.md", "guide.txt", "./guide.md"]
)
def test_catalog_rejects_unsafe_or_wrong_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        parse_source_catalog(catalog_bytes(path=path))


def test_catalog_rejects_duplicates_unknown_fields_and_invalid_metadata() -> None:
    original = catalog_bytes()
    entry = original.decode().split("[[entries]]\n", maxsplit=1)[1]
    with pytest.raises(ValidationError, match="duplicate catalog paths"):
        parse_source_catalog(original + b"[[entries]]\n" + entry.encode())

    changed_id = entry.replace("000000000001", "000000000002").replace(
        'path = "product/hr/leave.md"', 'path = "product/hr/other.md"'
    )
    duplicate_id = entry.replace('path = "product/hr/leave.md"', 'path = "product/hr/other.md"')
    with pytest.raises(ValidationError, match="duplicate document IDs"):
        parse_source_catalog(original + b"[[entries]]\n" + duplicate_id.encode())
    assert parse_source_catalog(original + b"[[entries]]\n" + changed_id.encode()).entries[1]

    with pytest.raises(ValidationError):
        parse_source_catalog(original.replace(b'title = "Leave guide"', b'unknown = "x"'))
    with pytest.raises((ValidationError, ValueError)):
        parse_source_catalog(original.replace(b"a" * 64, b"bad"))
    with pytest.raises(ValueError):
        parse_source_catalog(original.replace(b"00000000-0000-0000-0000-000000000001", b"bad"))


def test_catalog_rejects_duplicate_scope_and_naive_or_inverted_dates() -> None:
    raw = catalog_bytes()
    with pytest.raises(ValidationError):
        parse_source_catalog(raw.replace(b'["hr_core", "leave"]', b'["leave", "leave"]'))
    with pytest.raises(ValidationError, match="timezone-aware"):
        parse_source_catalog(raw.replace(b"2026-01-01T00:00:00Z", b"2026-01-01T00:00:00", 1))
    with pytest.raises(ValidationError, match="effective_to"):
        parse_source_catalog(
            raw.replace(
                b"approval_reference",
                b"effective_to = 2025-01-01T00:00:00Z\napproval_reference",
            )
        )
