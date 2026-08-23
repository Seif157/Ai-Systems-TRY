"""Unicode-safe deterministic text normalization without content filtering."""

import unicodedata


def normalize_text(value: str) -> str:
    """Normalize NFC/newlines and surrounding space while preserving content and paragraphs."""

    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    for character in normalized:
        if character == "\x00" or (
            unicodedata.category(character) == "Cc" and character not in {"\n", "\t"}
        ):
            raise ValueError("text contains an unsafe control character")
    normalized = normalized.strip()
    if not normalized:
        raise ValueError("text must not be blank")
    return normalized


def utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))
