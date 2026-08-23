import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from markdown_it.token import Token
from pydantic import ValidationError

from erp_ai.capabilities import DataClassification
from erp_ai.knowledge import KnowledgeSourceType
from erp_ai.knowledge.ingestion import prepare_knowledge_document
from erp_ai.knowledge.sources import MarkdownSourceAdapter, MarkdownSourceEntry
from erp_ai.knowledge.sources.markdown import (
    _ComponentInspection,
    _inline_text,
    _inspect_component,
    _inspect_relative_components,
    _same_file_identity,
    _sections,
)


def entry(raw: bytes, *, path: str = "guide.md") -> MarkdownSourceEntry:
    return MarkdownSourceEntry(
        path=path,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        document_version="1.0.0",
        namespace="hr",
        source_type=KnowledgeSourceType.PRODUCT_DOCUMENTATION,
        customer_environment_id=None,
        title="Approved guide",
        language="en",
        modules=("hr_core",),
        permissions=("hr.knowledge.read",),
        allowed_purposes=("employee_self_service",),
        legal_entities=(),
        classification=DataClassification.INTERNAL,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=None,
        approval_reference="approval-1",
        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def load(tmp_path: Path, raw: bytes, *, catalog_entry: MarkdownSourceEntry | None = None):
    (tmp_path / "guide.md").write_bytes(raw)
    return MarkdownSourceAdapter(tmp_path).load(catalog_entry or entry(raw))


def test_extracts_supported_markdown_without_destinations_and_prepares(tmp_path: Path) -> None:
    raw = b"""Preamble [portal](https://secret.example/path).

# Parent
Paragraph with **bold**, *emphasis*, `inline` and ![diagram alt](C:/secret/image.png).  
continued

> Quoted text

- first
- second

| Name | Value |
| --- | --- |
| one | two |

```python
print("untrusted")
```

---

    indented code

## Child
Child text.
"""
    draft = load(tmp_path, raw)
    blocks = "\n".join(block for section in draft.sections for block in section.text_blocks)
    assert tuple(section.heading for section in draft.sections) == (
        "Document",
        "Parent",
        "Parent",
        "Parent > Child",
    )
    assert "portal" in blocks and "diagram alt" in blocks and "print" in blocks
    assert "https://" not in blocks and "C:/secret" not in blocks
    assert {"Quoted text", "first", "second", "Name", "Value", "one", "two"} <= set(
        block for section in draft.sections for block in section.text_blocks
    )
    bundle = prepare_knowledge_document(draft)
    assert bundle.manifest.source_provenance == draft.source_provenance
    assert all("guide.md" not in chunk.model_dump_json() for chunk in bundle.chunks)


def test_arabic_headingless_bom_and_determinism(tmp_path: Path) -> None:
    raw = b"\xef\xbb\xbf" + "سياسة الإجازات\n\nLeave policy".encode()
    first = load(tmp_path, raw)
    second = MarkdownSourceAdapter(tmp_path).load(entry(raw))
    assert first == second
    assert first.sections[0].section_key == "preamble"
    assert first.sections[0].text_blocks == ("سياسة الإجازات", "Leave policy")
    assert prepare_knowledge_document(first) == prepare_knowledge_document(second)


def test_duplicate_headings_have_stable_unique_sections(tmp_path: Path) -> None:
    raw = b"# Same\nOne\n# Same\nTwo"
    draft = load(tmp_path, raw)
    assert tuple(section.heading for section in draft.sections) == ("Same", "Same")
    assert tuple(section.section_key for section in draft.sections) == (
        "section_0001",
        "section_0002",
    )


def test_parser_provenance_changes_fingerprint(tmp_path: Path) -> None:
    raw = b"# Guide\nText"
    draft = load(tmp_path, raw)
    assert draft.source_provenance is not None
    assert draft.source_provenance.parser_name == "markdown-it-py"
    assert draft.source_provenance.parser_major_version == 4
    changed = draft.model_copy(
        update={
            "source_provenance": draft.source_provenance.model_copy(
                update={"parser_major_version": 5}
            )
        }
    )
    assert (
        prepare_knowledge_document(draft).manifest.document_fingerprint
        != prepare_knowledge_document(changed).manifest.document_fingerprint
    )


def test_front_matter_cannot_override_catalog_governance(tmp_path: Path) -> None:
    raw = b"---\nnamespace: payroll\ntitle: Attack\n---\n# Safe\nApproved body"
    draft = load(tmp_path, raw)
    serialized = draft.model_dump_json()
    assert draft.namespace == "hr" and draft.title == "Approved guide"
    assert "payroll" not in serialized and "Attack" not in serialized


@pytest.mark.parametrize(
    "raw",
    [
        b"---\nnever closed",
        b"<div>raw html</div>",
        b"# Heading only",
        b"---",
        b"paragraph\x00bad",
        b"paragraph\x01bad",
    ],
)
def test_rejects_unsafe_or_empty_markdown(tmp_path: Path, raw: bytes) -> None:
    with pytest.raises(ValueError):
        load(tmp_path, raw)


def test_hash_invalid_utf8_and_catalog_version_fail_safely(tmp_path: Path) -> None:
    raw = b"Safe"
    (tmp_path / "guide.md").write_bytes(raw)
    adapter = MarkdownSourceAdapter(tmp_path)
    wrong = entry(b"different")
    with pytest.raises(ValueError, match="hash") as error:
        adapter.load(wrong)
    assert str(tmp_path) not in str(error.value)
    invalid = b"\xff"
    (tmp_path / "guide.md").write_bytes(invalid)
    with pytest.raises(ValueError, match="UTF-8"):
        adapter.load(entry(invalid))
    with pytest.raises(ValueError, match="catalog version"):
        adapter.load(entry(invalid), catalog_version=2)


def test_path_file_type_size_and_missing_checks(tmp_path: Path) -> None:
    adapter = MarkdownSourceAdapter(tmp_path)
    with pytest.raises(ValueError, match="unavailable"):
        adapter.load(entry(b"x"))
    directory = tmp_path / "guide.md"
    directory.mkdir()
    with pytest.raises(ValueError, match="regular"):
        adapter.load(entry(b"x"))
    directory.rmdir()
    directory.write_bytes(b"x" * 1_048_577)
    with pytest.raises(ValueError, match="size"):
        adapter.load(entry(b"x" * 1_048_577))
    with pytest.raises(ValueError, match="root"):
        MarkdownSourceAdapter(tmp_path / "missing")
    file_root = tmp_path / "root.txt"
    file_root.write_text("x")
    with pytest.raises(ValueError, match="directory"):
        MarkdownSourceAdapter(file_root)


def test_oversized_file_is_rejected_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"x" * 1_048_577
    (tmp_path / "guide.md").write_bytes(raw)

    def forbidden_open(*args: object, **kwargs: object) -> int:
        raise AssertionError("oversized source must not be opened")

    monkeypatch.setattr(os, "open", forbidden_open)
    with pytest.raises(ValueError, match="size"):
        MarkdownSourceAdapter(tmp_path).load(entry(raw))


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_rejects_symlink_file_and_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    link = tmp_path / "guide.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="unsafe"):
        MarkdownSourceAdapter(tmp_path).load(entry(b"outside"))
    link.unlink()
    real = tmp_path / "real"
    real.mkdir()
    (real / "guide.md").write_text("inside")
    parent_link = tmp_path / "linked"
    parent_link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe"):
        MarkdownSourceAdapter(tmp_path).load(entry(b"inside", path="linked/guide.md"))


def test_empty_front_matter_and_unsupported_inline_are_rejected(tmp_path: Path) -> None:
    raw = b"+++\nkey = 'value'\n+++\n# Good\nBody"
    assert load(tmp_path, raw).sections[0].heading == "Good"
    with pytest.raises(ValidationError):
        entry(b"x", path="../guide.md")


def test_defensive_token_validation_rejects_malformed_sequences() -> None:
    inline = Token("inline", "", 0)
    with pytest.raises(ValueError, match="malformed inline"):
        _inline_text(inline)
    inline.children = [Token("unsupported", "", 0)]
    with pytest.raises(ValueError, match="unsupported inline"):
        _inline_text(inline)
    inline.children = [Token("html_inline", "", 0)]
    with pytest.raises(ValueError, match="raw HTML"):
        _inline_text(inline)
    malformed_heading = Token("heading_open", "bad", 1)
    with pytest.raises(ValueError, match="malformed heading"):
        _sections([malformed_heading])
    with pytest.raises(ValueError, match="heading has no text"):
        _sections([Token("heading_open", "h1", 1), Token("heading_close", "h1", -1)])
    with pytest.raises(ValueError, match="heading has no text"):
        _sections([Token("heading_open", "h1", 1)])
    with pytest.raises(ValueError, match="raw HTML"):
        _sections([Token("html_block", "", 0)])
    with pytest.raises(ValueError, match="unsupported Markdown"):
        _sections([Token("unsupported", "", 0)])


def test_empty_document_and_root_symlink_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no supported text"):
        _sections([])
    real = tmp_path / "real-root"
    real.mkdir()
    linked = tmp_path / "linked-root"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="unsafe"):
        MarkdownSourceAdapter(linked)


def component(
    *, symbolic_link: bool = False, junction: bool = False, reparse_point: bool = False
) -> _ComponentInspection:
    return _ComponentInspection(
        mode=stat.S_IFREG | 0o600,
        size=4,
        device=1,
        inode=2,
        symbolic_link=symbolic_link,
        junction=junction,
        reparse_point=reparse_point,
    )


@pytest.mark.parametrize(
    ("unsafe_index", "unsafe"),
    [
        (0, component(symbolic_link=True)),
        (1, component(symbolic_link=True)),
        (0, component(junction=True)),
        (1, component(junction=True)),
        (0, component(reparse_point=True)),
        (1, component(reparse_point=True)),
    ],
    ids=[
        "intermediate-symlink",
        "final-symlink",
        "intermediate-windows-junction",
        "final-windows-junction",
        "intermediate-generic-reparse",
        "final-generic-reparse",
    ],
)
def test_component_inspection_rejects_all_indirection_without_os_privileges(
    tmp_path: Path, unsafe_index: int, unsafe: _ComponentInspection
) -> None:
    calls = 0

    def inspect(_path: Path) -> _ComponentInspection:
        nonlocal calls
        selected = unsafe if calls == unsafe_index else component()
        calls += 1
        return selected

    with pytest.raises(ValueError, match="indirection"):
        _inspect_relative_components(tmp_path, ("parent", "guide.md"), inspect=inspect)


def test_component_inspection_permission_failure_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "private" / "guide.md"

    def denied(_path: Path) -> os.stat_result:
        raise PermissionError(str(secret))

    monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(ValueError, match="safely inspected") as error:
        _inspect_component(secret)
    assert str(secret) not in str(error.value)


def test_empty_component_sequence_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="path is invalid"):
        _inspect_relative_components(tmp_path, ())


def opened_stat(*, mode: int, device: int = 1, inode: int = 2, size: int = 4) -> object:
    return SimpleNamespace(
        st_mode=mode,
        st_size=size,
        st_dev=device,
        st_ino=inode,
        st_file_attributes=0,
    )


def test_file_replaced_between_inspection_and_open_fails_identity_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"safe"
    (tmp_path / "guide.md").write_bytes(raw)
    monkeypatch.setattr(
        os,
        "fstat",
        lambda _descriptor: opened_stat(mode=stat.S_IFREG | 0o600, device=999, inode=999),
    )
    with pytest.raises(ValueError, match="changed"):
        MarkdownSourceAdapter(tmp_path).load(entry(raw))


def test_identity_comparison_requires_matching_available_identity() -> None:
    inspected = component()
    assert _same_file_identity(inspected, inspected)
    assert not _same_file_identity(
        inspected,
        _ComponentInspection(
            mode=inspected.mode,
            size=inspected.size,
            device=1,
            inode=3,
            symbolic_link=False,
            junction=False,
            reparse_point=False,
        ),
    )
    unavailable = _ComponentInspection(
        mode=inspected.mode,
        size=inspected.size,
        device=None,
        inode=None,
        symbolic_link=False,
        junction=False,
        reparse_point=False,
    )
    assert _same_file_identity(inspected, unavailable)
    assert _same_file_identity(unavailable, inspected)


def test_non_regular_opened_handle_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"safe"
    (tmp_path / "guide.md").write_bytes(raw)
    monkeypatch.setattr(
        os,
        "fstat",
        lambda _descriptor: opened_stat(mode=stat.S_IFDIR | 0o700),
    )
    with pytest.raises(ValueError, match="handle is not a regular file"):
        MarkdownSourceAdapter(tmp_path).load(entry(raw))


def test_growth_during_bounded_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"safe"
    (tmp_path / "guide.md").write_bytes(raw)
    calls = 0

    def growing_read(_descriptor: int, maximum: int) -> bytes:
        nonlocal calls
        calls += 1
        return b"x" * maximum

    monkeypatch.setattr(os, "read", growing_read)
    with pytest.raises(ValueError, match="size"):
        MarkdownSourceAdapter(tmp_path).load(entry(raw))
    assert calls == 1


def test_source_is_opened_once_and_read_from_validated_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"safe"
    (tmp_path / "guide.md").write_bytes(raw)
    real_open = os.open
    calls = 0

    def counting_open(path: Path, flags: int) -> int:
        nonlocal calls
        calls += 1
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", counting_open)
    assert MarkdownSourceAdapter(tmp_path).load(entry(raw)).sections
    assert calls == 1


def test_open_failure_never_exposes_absolute_source_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"safe"
    secret = tmp_path / "guide.md"
    secret.write_bytes(raw)

    def denied_open(_path: Path, _flags: int) -> int:
        raise PermissionError(str(secret))

    monkeypatch.setattr(os, "open", denied_open)
    with pytest.raises(ValueError, match="safely opened") as error:
        MarkdownSourceAdapter(tmp_path).load(entry(raw))
    assert str(secret) not in str(error.value)


def test_resolution_failures_are_path_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "guide.md"
    secret.write_bytes(b"safe")
    real_resolve = Path.resolve

    def root_failure(_path: Path, *, strict: bool = False) -> Path:
        raise PermissionError(str(secret))

    monkeypatch.setattr(Path, "resolve", root_failure)
    with pytest.raises(ValueError, match="root is unavailable") as root_error:
        MarkdownSourceAdapter(tmp_path)
    assert str(secret) not in str(root_error.value)

    monkeypatch.setattr(Path, "resolve", real_resolve)
    adapter = MarkdownSourceAdapter(tmp_path)
    monkeypatch.setattr(Path, "resolve", root_failure)
    with pytest.raises(ValueError, match="unavailable or unsafe") as source_error:
        adapter.load(entry(b"safe"))
    assert str(secret) not in str(source_error.value)


def test_fstat_and_read_failures_are_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = b"safe"
    secret = tmp_path / "guide.md"
    secret.write_bytes(raw)

    def denied_fstat(_descriptor: int) -> os.stat_result:
        raise PermissionError(str(secret))

    monkeypatch.setattr(os, "fstat", denied_fstat)
    with pytest.raises(ValueError, match="handle cannot be validated") as fstat_error:
        MarkdownSourceAdapter(tmp_path).load(entry(raw))
    assert str(secret) not in str(fstat_error.value)

    monkeypatch.undo()

    def denied_read(_descriptor: int, _maximum: int) -> bytes:
        raise PermissionError(str(secret))

    monkeypatch.setattr(os, "read", denied_read)
    with pytest.raises(ValueError, match="safely read") as read_error:
        MarkdownSourceAdapter(tmp_path).load(entry(raw))
    assert str(secret) not in str(read_error.value)
