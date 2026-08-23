"""Deterministic section-local chunking on block and Unicode whitespace boundaries."""

from dataclasses import dataclass

from erp_ai.knowledge.ingestion.models import IngestionLimits, KnowledgeSection
from erp_ai.knowledge.ingestion.normalization import utf8_size


@dataclass(frozen=True, slots=True)
class SectionChunk:
    section_key: str
    heading: str
    content: str


def _fits(value: str, limits: IngestionLimits) -> bool:
    return (
        len(value) <= limits.maximum_chunk_characters
        and utf8_size(value) <= limits.maximum_chunk_bytes
    )


def _split_block(block: str, limits: IngestionLimits) -> tuple[str, ...]:
    if _fits(block, limits):
        return (block,)
    words = block.split()
    if not words:
        raise ValueError("normalized block must not be blank")
    pieces: list[str] = []
    current = ""
    for word in words:
        if not _fits(word, limits):
            raise ValueError("indivisible token exceeds prepared chunk limit")
        candidate = word if not current else f"{current} {word}"
        if _fits(candidate, limits):
            current = candidate
        else:
            pieces.append(current)
            current = word
    pieces.append(current)
    return tuple(pieces)


def _overlap_suffix(content: str, limits: IngestionLimits) -> str:
    if limits.overlap_characters == 0:
        return ""
    suffix = content[-limits.overlap_characters :].strip()
    if len(content) > limits.overlap_characters:
        first_space = suffix.find(" ")
        if first_space >= 0:
            suffix = suffix[first_space + 1 :].strip()
    return suffix


def chunk_sections(
    sections: tuple[KnowledgeSection, ...], limits: IngestionLimits
) -> tuple[SectionChunk, ...]:
    """Preserve section order and never overlap across a section boundary."""

    chunks: list[SectionChunk] = []
    for section in sections:
        units = tuple(unit for block in section.text_blocks for unit in _split_block(block, limits))
        current = ""
        for unit in units:
            candidate = unit if not current else f"{current}\n\n{unit}"
            if _fits(candidate, limits):
                current = candidate
                continue
            if current:
                chunks.append(SectionChunk(section.section_key, section.heading, current))
            overlap = _overlap_suffix(current, limits)
            candidate = f"{overlap}\n\n{unit}" if overlap else unit
            current = candidate if _fits(candidate, limits) else unit
        if current:
            chunks.append(SectionChunk(section.section_key, section.heading, current))
    if any(not chunk.content.strip() for chunk in chunks):
        raise ValueError("blank prepared chunks are forbidden")
    return tuple(chunks)
