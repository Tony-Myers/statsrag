"""Source indexing: TF-IDF (always available) + sentence-transformers (optional).

The backend is chosen at index time. If sentence-transformers is installed,
the UI offers both; otherwise TF-IDF is used automatically. The manifest
records which backend was used, and query() dispatches accordingly.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from functools import lru_cache as _lru_cache
from pathlib import Path
from typing import List, Tuple, Optional, Any
import re, json, logging
import numpy as np
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

log = logging.getLogger(__name__)

SKIP_FILENAMES = {".DS_Store", ".gitkeep"}

# ── Sentence-transformers availability ──
try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    SentenceTransformer = None  # type: ignore[misc, assignment]
    EMBEDDINGS_AVAILABLE = False

# ── pypdf availability ──
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except Exception:
    PdfReader = None  # type: ignore[misc, assignment]
    PYPDF_AVAILABLE = False

# ── Default embedding model ──
DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"

CHUNK_CHARS = 1800
CHUNK_OVERLAP = 250


# ================================================================
# File reading helpers
# ================================================================

def _should_skip_file(path: Path) -> bool:
    name = path.name
    if name in SKIP_FILENAMES or name.startswith("."):
        return True
    try:
        if path.is_file() and path.stat().st_size == 0:
            return True
    except Exception:
        pass
    return False


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in [".txt", ".md"]:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    return ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _chunk(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    chunks: List[str] = []
    i = 0
    while i < len(text):
        j = min(len(text), i + CHUNK_CHARS)
        chunks.append(text[i:j])
        i = j - CHUNK_OVERLAP
        if i < 0:
            i = 0
        if j == len(text):
            break
    return chunks


# ================================================================
# Index bundle — supports both backends
# ================================================================

@dataclass
class IndexBundle:
    """Holds a searchable index of source chunks.

    backend == "tfidf":
        vectorizer: TfidfVectorizer, matrix: sparse CSR
    backend == "embedding":
        embeddings: np.ndarray (n_chunks x dim), model_name: str
    """
    backend: str = "tfidf"
    # TF-IDF fields
    vectorizer: Any = None
    matrix: Any = None
    # Embedding fields
    embeddings: Any = None      # np.ndarray or None
    model_name: str = ""
    # Common
    meta: List[dict] = field(default_factory=list)


# ================================================================
# Embedding model cache (lazy singleton)
# ================================================================

@_lru_cache(maxsize=1)
def _get_embed_model(model_name: str) -> Any:
    """Load the SentenceTransformer model once per process."""
    if not EMBEDDINGS_AVAILABLE:
        raise ImportError("sentence-transformers is not installed.")
    log.info("Loading embedding model '%s' (first time may download ~80 MB)...", model_name)
    return SentenceTransformer(model_name)


# ================================================================
# Ingest / build index
# ================================================================

def ingest_sources(
    sources_dir: Path,
    index_dir: Path,
    include_paths: Optional[list[Path]] = None,
    backend: str = "auto",
    embed_model: str = DEFAULT_EMBED_MODEL,
) -> int:
    """Build or rebuild the index.

    Parameters
    ----------
    backend : str
        "tfidf" -- always available, keyword matching.
        "embedding" -- semantic search (requires sentence-transformers).
        "auto" -- use embeddings if available, else TF-IDF.
    embed_model : str
        HuggingFace model name for the embedding backend.
    """
    # Invalidate caches
    _load_cached.cache_clear()
    _read_text_cached.cache_clear()

    # Resolve backend
    if backend == "auto":
        backend = "embedding" if EMBEDDINGS_AVAILABLE else "tfidf"
    if backend == "embedding" and not EMBEDDINGS_AVAILABLE:
        log.warning("sentence-transformers not installed; falling back to TF-IDF.")
        backend = "tfidf"

    index_dir.mkdir(parents=True, exist_ok=True)
    meta: List[dict] = []
    texts: List[str] = []

    _diag: dict = {
        "processed": 0, "skipped_hidden": 0, "skipped_empty_text": 0,
        "skipped_unsupported": 0, "skipped_filter": 0,
        "pdf_count": 0, "pypdf_available": PYPDF_AVAILABLE,
    }

    all_files = [x for x in sources_dir.rglob("*") if x.is_file()]

    if include_paths is not None:
        rel_includes: list[Path] = []
        for ip in include_paths:
            try:
                rel_includes.append(ip.relative_to(sources_dir))
            except Exception:
                rel_includes.append(ip)

        def _allowed(p: Path) -> bool:
            rel = p.relative_to(sources_dir)
            return any(
                rel == inc or str(rel).startswith(str(inc).rstrip("/") + "/")
                for inc in rel_includes
            )

        pre_count = len(all_files)
        all_files = [p for p in all_files if _allowed(p)]
        _diag["skipped_filter"] = pre_count - len(all_files)

    for p in sorted(all_files):
        if p.name.startswith('.') or p.name in SKIP_FILENAMES:
            _diag["skipped_hidden"] += 1
            continue

        if p.suffix.lower() == ".pdf":
            _diag["pdf_count"] += 1

        raw = _clean(_read_text(p))
        if not raw:
            if p.suffix.lower() in (".txt", ".md", ".pdf"):
                _diag["skipped_empty_text"] += 1
            else:
                _diag["skipped_unsupported"] += 1
            continue

        _diag["processed"] += 1
        for k, ch in enumerate(_chunk(raw)):
            texts.append(ch)
            meta.append({"path": str(p.relative_to(sources_dir)), "chunk": k})

    # -- Build index --
    if backend == "embedding" and texts:
        model = _get_embed_model(embed_model)
        emb = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)
        bundle = IndexBundle(
            backend="embedding",
            embeddings=np.array(emb, dtype=np.float32),
            model_name=embed_model,
            meta=meta,
        )
    elif texts:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=60000)
        matrix = vectorizer.fit_transform(texts)
        bundle = IndexBundle(
            backend="tfidf",
            vectorizer=vectorizer,
            matrix=matrix,
            meta=meta,
        )
    else:
        # Empty index
        bundle = IndexBundle(backend=backend, meta=meta)

    joblib.dump(bundle, index_dir / "tfidf_index.joblib")
    (index_dir / "manifest.json").write_text(
        json.dumps({
            "n_chunks": len(texts),
            "backend": backend,
            "model_name": embed_model if backend == "embedding" else "",
            "diagnostics": _diag,
        }, indent=2),
        encoding="utf-8",
    )
    return len(texts)


# ================================================================
# Loading
# ================================================================

def _load(index_dir: Path) -> IndexBundle:
    return _load_cached(str(index_dir))


@_lru_cache(maxsize=4)
def _load_cached(index_dir_str: str) -> IndexBundle:
    return joblib.load(Path(index_dir_str) / "tfidf_index.joblib")


def clear_caches() -> None:
    """Clear all internal caches."""
    _load_cached.cache_clear()
    _read_text_cached.cache_clear()


# ================================================================
# Query
# ================================================================

def query(
    index_dir: Path,
    question: str,
    top_k: int = 6,
    allowed_prefixes: Optional[list[str]] = None,
) -> List[Tuple[float, dict]]:
    """Query the index. Dispatches based on which backend was used at build time."""
    bundle = _load(index_dir)

    if bundle.backend == "embedding":
        return _query_embedding(bundle, question, top_k, allowed_prefixes)
    else:
        return _query_tfidf(bundle, question, top_k, allowed_prefixes)


def _query_tfidf(
    bundle: IndexBundle,
    question: str,
    top_k: int,
    allowed_prefixes: Optional[list[str]],
) -> List[Tuple[float, dict]]:
    if bundle.matrix is None:
        return []
    qv = bundle.vectorizer.transform([question])
    sims = cosine_similarity(qv, bundle.matrix).ravel()
    return _collect_results(sims, bundle.meta, top_k, allowed_prefixes)


def _query_embedding(
    bundle: IndexBundle,
    question: str,
    top_k: int,
    allowed_prefixes: Optional[list[str]],
) -> List[Tuple[float, dict]]:
    if bundle.embeddings is None or len(bundle.embeddings) == 0:
        return []
    model = _get_embed_model(bundle.model_name)
    q_emb = model.encode([question], normalize_embeddings=True)
    sims = cosine_similarity(q_emb, bundle.embeddings).ravel()
    return _collect_results(sims, bundle.meta, top_k, allowed_prefixes)


def _collect_results(
    sims: np.ndarray,
    meta: List[dict],
    top_k: int,
    allowed_prefixes: Optional[list[str]],
) -> List[Tuple[float, dict]]:
    ordered = sims.argsort()[::-1]
    out: List[Tuple[float, dict]] = []
    for i in ordered:
        m = meta[int(i)]
        p = m.get("path", "")
        if allowed_prefixes:
            ok = any(
                p == pref.strip().rstrip("/") or p.startswith(pref.strip().rstrip("/") + "/")
                for pref in allowed_prefixes if pref.strip()
            )
            if not ok:
                continue
        out.append((float(sims[i]), m))
        if len(out) >= top_k:
            break
    return out


# ================================================================
# Chunk text retrieval
# ================================================================

def get_chunk_text(sources_dir: Path, rel_path: str, chunk_id: int) -> str:
    """Reconstruct a chunk's text from the stored source file."""
    try:
        raw = _read_text_cached(str(sources_dir / rel_path))
        chunks = _chunk(raw)
        if 0 <= chunk_id < len(chunks):
            return chunks[chunk_id]
        return ""
    except Exception:
        return ""


@_lru_cache(maxsize=256)
def _read_text_cached(path_str: str) -> str:
    raw = _read_text(Path(path_str))
    return _clean(raw)
