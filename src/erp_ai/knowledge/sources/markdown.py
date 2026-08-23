"""Controlled Markdown token adapter with no discovery, rendering, or fetching."""

import hashlib
import hmac
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Final

from markdown_it import MarkdownIt
from markdown_it.token import Token

from erp_ai.knowledge.ingestion.models import (
    KnowledgeDocumentDraft,
    KnowledgeSection,
    SourceProvenance,
)
from erp_ai.knowledge.ingestion.normalization import normalize_text
from erp_ai.knowledge.sources.models import MarkdownSourceEntry

MAXIMUM_RAW_SOURCE_BYTES: Final = 1_048_576
ADAPTER_CONTRACT_VERSION: Final = 1
PARSER_NAME: Final = "markdown-it-py"
_REPARSE_ATTRIBUTE: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True, slots=True)
class _ComponentInspection:
    mode: int
    size: int
    device: int | None
    inode: int | None
    symbolic_link: bool
    junction: bool
    reparse_point: bool


def _metadata_from_stat(
    metadata: os.stat_result, *, junction: bool = False
) -> _ComponentInspection:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return _ComponentInspection(
        mode=metadata.st_mode,
        size=metadata.st_size,
        device=getattr(metadata, "st_dev", None),
        inode=getattr(metadata, "st_ino", None) or None,
        symbolic_link=stat.S_ISLNK(metadata.st_mode),
        junction=junction,
        reparse_point=bool(attributes & _REPARSE_ATTRIBUTE),
    )


def _inspect_component(path: Path) -> _ComponentInspection:
    """Inspect one component without following it; this private seam is replaceable in tests."""

    try:
        metadata = path.lstat()
        junction = path.is_junction() if hasattr(path, "is_junction") else False
    except OSError:
        raise ValueError("approved source component cannot be safely inspected") from None
    return _metadata_from_stat(metadata, junction=junction)


def _reject_indirection(component: _ComponentInspection) -> None:
    if component.symbolic_link or component.junction or component.reparse_point:
        raise ValueError("filesystem indirection is forbidden")


def _inspect_relative_components(
    root: Path,
    relative_parts: tuple[str, ...],
    *,
    inspect: Callable[[Path], _ComponentInspection] = _inspect_component,
) -> tuple[Path, _ComponentInspection]:
    """Inspect every enumerated relative component without resolving through indirection."""

    cursor = root
    final: _ComponentInspection | None = None
    for component in relative_parts:
        cursor = cursor / component
        final = inspect(cursor)
        _reject_indirection(final)
    if final is None:
        raise ValueError("approved Markdown source path is invalid")
    return cursor, final


def _same_file_identity(inspected: _ComponentInspection, opened: _ComponentInspection) -> bool:
    if inspected.device is None or inspected.inode is None:
        return True
    if opened.device is None or opened.inode is None:
        return True
    return (inspected.device, inspected.inode) == (opened.device, opened.inode)


def _read_bounded(descriptor: int) -> bytes:
    remaining = MAXIMUM_RAW_SOURCE_BYTES + 1
    pieces: list[bytes] = []
    while remaining:
        piece = os.read(descriptor, remaining)
        if not piece:
            break
        pieces.append(piece)
        remaining -= len(piece)
    return b"".join(pieces)


def _parser_major() -> int:
    return int(version(PARSER_NAME).split(".", maxsplit=1)[0])


def _parser() -> MarkdownIt:
    parser = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": False, "typographer": False, "maxNesting": 20},
    )
    parser.enable("table")
    return parser


def _reject_raw_html(text: str) -> None:
    probe = MarkdownIt(
        "commonmark",
        {"html": True, "linkify": False, "typographer": False, "maxNesting": 20},
    )
    if any(
        token.type in {"html_block", "html_inline"}
        or any(child.type == "html_inline" for child in (token.children or ()))
        for token in probe.parse(text)
    ):
        raise ValueError("raw HTML is unsupported")


def _without_front_matter(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() not in {"---", "+++"}:
        return text
    delimiter = lines[0].strip()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == delimiter or (delimiter == "---" and line.strip() == "..."):
            return "".join(lines[index + 1 :])
    raise ValueError("unterminated Markdown front matter")


def _inline_text(token: Token) -> str:
    children = token.children
    if children is None:
        raise ValueError("malformed inline token")
    parts: list[str] = []
    active_link_destination: str | None = None
    wrappers = {
        "em_open",
        "em_close",
        "strong_open",
        "strong_close",
        "s_open",
        "s_close",
        "link_open",
        "link_close",
    }
    for child in children:
        if child.type in {"text", "code_inline"}:
            if active_link_destination is None or child.content != active_link_destination:
                parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif child.type == "image":
            parts.append(child.content)
        elif child.type == "link_open":
            destination = child.attrGet("href")
            active_link_destination = destination if isinstance(destination, str) else None
        elif child.type == "link_close":
            active_link_destination = None
        elif child.type in wrappers:
            continue
        elif child.type == "html_inline":
            raise ValueError("raw HTML is unsupported")
        else:
            raise ValueError("unsupported inline Markdown token")
    return normalize_text("".join(parts))


def _sections(tokens: list[Token]) -> tuple[KnowledgeSection, ...]:
    heading_path: list[str] = []
    current_heading = "Document"
    current_blocks: list[str] = []
    sections: list[KnowledgeSection] = []
    saw_heading = False
    pending_heading_level: int | None = None

    def flush() -> None:
        nonlocal current_blocks
        if current_blocks:
            key = (
                "preamble"
                if not saw_heading and not sections
                else f"section_{len(sections) + 1:04d}"
            )
            sections.append(
                KnowledgeSection(
                    section_key=key, heading=current_heading, text_blocks=tuple(current_blocks)
                )
            )
            current_blocks = []

    structural = {
        "paragraph_open",
        "paragraph_close",
        "bullet_list_open",
        "bullet_list_close",
        "ordered_list_open",
        "ordered_list_close",
        "list_item_open",
        "list_item_close",
        "blockquote_open",
        "blockquote_close",
        "table_open",
        "table_close",
        "thead_open",
        "thead_close",
        "tbody_open",
        "tbody_close",
        "tr_open",
        "tr_close",
        "th_open",
        "th_close",
        "td_open",
        "td_close",
    }
    for token in tokens:
        if token.type == "heading_open":
            flush()
            if not token.tag.startswith("h") or not token.tag[1:].isdigit():
                raise ValueError("malformed heading token")
            pending_heading_level = int(token.tag[1:])
        elif token.type == "heading_close":
            if pending_heading_level is not None:
                raise ValueError("heading has no text")
        elif token.type == "inline":
            content = _inline_text(token)
            if pending_heading_level is not None:
                level = pending_heading_level
                heading_path[level - 1 :] = [content]
                current_heading = " > ".join(heading_path)
                pending_heading_level = None
                saw_heading = True
            else:
                current_blocks.append(content)
        elif token.type in {"fence", "code_block"}:
            current_blocks.append(normalize_text(token.content))
        elif token.type == "hr":
            flush()
        elif token.type in structural:
            continue
        elif token.type in {"html_block"}:
            raise ValueError("raw HTML is unsupported")
        else:
            raise ValueError("unsupported Markdown token")
    if pending_heading_level is not None:
        raise ValueError("heading has no text")
    flush()
    if not sections:
        raise ValueError("Markdown source contains no supported text")
    return tuple(sections)


class MarkdownSourceAdapter:
    """Read only one trusted catalog entry beneath one resolved approved root."""

    __slots__ = ("_root",)

    def __init__(self, approved_root: Path) -> None:
        try:
            _reject_indirection(_inspect_component(approved_root))
        except ValueError:
            raise ValueError("approved source root is unavailable or unsafe") from None
        try:
            root = approved_root.resolve(strict=True)
        except OSError:
            raise ValueError("approved source root is unavailable") from None
        if not root.is_dir():
            raise ValueError("approved source root is not a directory")
        self._root = root

    def _validated_file(self, entry: MarkdownSourceEntry) -> tuple[Path, _ComponentInspection]:
        relative = tuple(entry.path.split("/"))
        try:
            candidate, inspected = _inspect_relative_components(self._root, relative)
        except ValueError:
            raise ValueError("approved Markdown source is unavailable or unsafe") from None
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            raise ValueError("approved Markdown source is unavailable or unsafe") from None
        try:
            resolved.relative_to(self._root)
        except ValueError:  # pragma: no cover - lexical validation makes this defensive
            raise ValueError("approved Markdown source escapes its root") from None
        if not stat.S_ISREG(inspected.mode):
            raise ValueError("approved Markdown source is not a regular file")
        if inspected.size > MAXIMUM_RAW_SOURCE_BYTES:
            raise ValueError("approved Markdown source exceeds the raw size limit")
        return candidate, inspected

    def load(
        self, entry: MarkdownSourceEntry, *, catalog_version: int = 1
    ) -> KnowledgeDocumentDraft:
        """Validate, parse, and adapt one explicitly selected catalog entry."""

        if catalog_version != 1:
            raise ValueError("unsupported catalog version")
        source, inspected = self._validated_file(entry)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(source, flags)
        except OSError:
            raise ValueError("approved Markdown source cannot be safely opened") from None
        try:
            try:
                opened = _metadata_from_stat(os.fstat(descriptor))
            except OSError:
                raise ValueError("approved Markdown source handle cannot be validated") from None
            _reject_indirection(opened)
            if not stat.S_ISREG(opened.mode):
                raise ValueError("approved Markdown source handle is not a regular file")
            if not _same_file_identity(inspected, opened):
                raise ValueError("approved Markdown source changed before opening")
            try:
                raw = _read_bounded(descriptor)
            except OSError:
                raise ValueError("approved Markdown source cannot be safely read") from None
        finally:
            os.close(descriptor)
        if len(raw) > MAXIMUM_RAW_SOURCE_BYTES:
            raise ValueError("approved Markdown source exceeds the raw size limit")
        digest = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(digest, entry.raw_sha256):
            raise ValueError("approved Markdown source hash does not match catalog")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("approved Markdown source is not valid UTF-8") from error
        normalized = normalize_text(_without_front_matter(text))
        _reject_raw_html(normalized)
        sections = _sections(_parser().parse(normalized))
        provenance = SourceProvenance(
            catalog_version=1,
            raw_source_sha256=digest,
            parser_name=PARSER_NAME,
            parser_major_version=_parser_major(),
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
        )
        return KnowledgeDocumentDraft(
            document_id=entry.document_id,
            document_version=entry.document_version,
            namespace=entry.namespace,
            source_type=entry.source_type,
            customer_environment_id=entry.customer_environment_id,
            title=entry.title,
            language=entry.language,
            required_modules_all=entry.modules,
            required_permissions_all=entry.permissions,
            allowed_purposes=entry.allowed_purposes,
            legal_entity_ids=entry.legal_entities,
            data_classification=entry.classification,
            effective_from=entry.effective_from,
            effective_to=entry.effective_to,
            approval_reference=entry.approval_reference,
            approved_at=entry.approved_at,
            source_provenance=provenance,
            sections=sections,
        )
