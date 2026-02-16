"""Retrieval helpers (stable import path).

Some versions of the UI/verification code import `statsrag.retrieval`.
The project currently uses a local TF-IDF index implemented in
`statsrag.indexing`. This module simply re-exports a small, stable API.

No network calls are made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .indexing import query as _query
from .indexing import get_chunk_text as _get_chunk_text


def rag_query(
    index_dir: Path,
    text: str,
    k: int = 6,
    allowed_prefixes: Optional[list[str]] = None,
):
    """Return top-k retrieved chunks for `text`.

    Parameters
    ----------
    index_dir:
        Path to the index directory (e.g., /data/index).
    text:
        Query string.
    k:
        Number of results.
    allowed_prefixes:
        Optional list of folder prefixes (e.g., ["Interpretation_guardrails/"]).

    Returns
    -------
    list[tuple[float, dict]]
        Each item is (score, meta_dict) where meta_dict has 'path' and 'chunk'.
    """
    return _query(index_dir=index_dir, question=text, top_k=k, allowed_prefixes=allowed_prefixes)


def get_chunk_text(sources_dir: Path, rel_path: str, chunk_id: int) -> str:
    """Fetch exact chunk text by source path and chunk id."""
    return _get_chunk_text(sources_dir=sources_dir, rel_path=rel_path, chunk_id=chunk_id)
