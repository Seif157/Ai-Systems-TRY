"""Controlled, catalog-driven source adapters."""

from erp_ai.knowledge.sources.catalog import parse_source_catalog
from erp_ai.knowledge.sources.markdown import MarkdownSourceAdapter
from erp_ai.knowledge.sources.models import MarkdownSourceCatalog, MarkdownSourceEntry

__all__ = [
    "MarkdownSourceAdapter",
    "MarkdownSourceCatalog",
    "MarkdownSourceEntry",
    "parse_source_catalog",
]
