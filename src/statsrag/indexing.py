from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache as _lru_cache
from pathlib import Path
from typing import List, Tuple
import re, json
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SKIP_FILENAMES = {".DS_Store", ".gitkeep"}

def _should_skip_file(path: Path) -> bool:
    name = path.name
    if name in SKIP_FILENAMES:
        return True
    if name.startswith("."):
        return True
    # skip empty files (often placeholder markers)
    try:
        if path.is_file() and path.stat().st_size == 0:
            return True
    except Exception:
        pass
    return False

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except Exception:
    PdfReader = None
    PYPDF_AVAILABLE = False

CHUNK_CHARS = 1800
CHUNK_OVERLAP = 250

def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in [".txt", ".md"]:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(str(path))
            parts = []
            for page in reader.pages:
                txt = page.extract_text() or ""
                parts.append(txt)
            return "\n".join(parts)
        except Exception:
            return ""
    return ""

def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def _chunk(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
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

@dataclass
class IndexBundle:
    vectorizer: TfidfVectorizer
    matrix: any
    meta: List[dict]

def ingest_sources(sources_dir: Path, index_dir: Path, include_paths: list[Path] | None = None) -> int:
    # Invalidate caches when rebuilding the index
    _load_cached.cache_clear()
    _read_text_cached.cache_clear()

    index_dir.mkdir(parents=True, exist_ok=True)
    meta = []
    texts = []

    # Diagnostics: track what happened to each file
    _diag: dict = {"processed": 0, "skipped_hidden": 0, "skipped_empty_text": 0,
                    "skipped_unsupported": 0, "skipped_filter": 0,
                    "pdf_count": 0, "pypdf_available": PYPDF_AVAILABLE}

    all_files = [x for x in sources_dir.rglob("*") if x.is_file()]

    if include_paths is not None:
        # None = no filter (all files). [] = nothing selected. [paths] = filter.
        rel_includes: list[Path] = []
        for ip in include_paths:
            try:
                rel_includes.append(ip.relative_to(sources_dir))
            except Exception:
                rel_includes.append(ip)

        def _allowed(p: Path) -> bool:
            rel = p.relative_to(sources_dir)
            for inc in rel_includes:
                # include file exactly, or any file under an included folder
                if rel == inc or str(rel).startswith(str(inc).rstrip("/") + "/"):
                    return True
            return False

        pre_count = len(all_files)
        all_files = [p for p in all_files if _allowed(p)]
        _diag["skipped_filter"] = pre_count - len(all_files)

    for p in sorted(all_files):
        # Skip hidden/system files and placeholders
        if p.name.startswith('.') or p.name in {'.DS_Store', '.gitkeep'}:
            _diag["skipped_hidden"] += 1
            continue

        if p.suffix.lower() == ".pdf":
            _diag["pdf_count"] += 1

        raw = _read_text(p)
        raw = _clean(raw)
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
    vectorizer = TfidfVectorizer(stop_words="english", max_features=60000)
    matrix = vectorizer.fit_transform(texts) if texts else None
    bundle = IndexBundle(vectorizer=vectorizer, matrix=matrix, meta=meta)
    joblib.dump(bundle, index_dir / "tfidf_index.joblib")
    (index_dir / "manifest.json").write_text(
        json.dumps({"n_chunks": len(texts), "diagnostics": _diag}, indent=2),
        encoding="utf-8",
    )
    return len(texts)

def _load(index_dir: Path) -> IndexBundle:
    """Load the index bundle, using an LRU cache to avoid repeated joblib.load()."""
    return _load_cached(str(index_dir))


@_lru_cache(maxsize=4)
def _load_cached(index_dir_str: str) -> IndexBundle:
    return joblib.load(Path(index_dir_str) / "tfidf_index.joblib")


def clear_caches() -> None:
    """Clear all internal caches (index bundle + file text).

    Call after rebuilding the index or when source files change.
    """
    _load_cached.cache_clear()
    _read_text_cached.cache_clear()


def query(
    index_dir: Path,
    question: str,
    top_k: int = 6,
    allowed_prefixes: list[str] | None = None,
) -> List[Tuple[float, dict]]:
    bundle = _load(index_dir)
    if bundle.matrix is None:
        return []
    qv = bundle.vectorizer.transform([question])
    sims = cosine_similarity(qv, bundle.matrix).ravel()
    # Optionally filter by allowed path prefixes (e.g. folder names)
    ordered = sims.argsort()[::-1]
    out: List[Tuple[float, dict]] = []
    for i in ordered:
        m = bundle.meta[int(i)]
        p = m.get("path", "")
        if allowed_prefixes:
            ok = False
            for pref in allowed_prefixes:
                pref = pref.strip().rstrip("/")
                if not pref:
                    continue
                if p == pref or p.startswith(pref + "/"):
                    ok = True
                    break
            if not ok:
                continue
        out.append((float(sims[i]), m))
        if len(out) >= top_k:
            break
    return out


def get_chunk_text(sources_dir: Path, rel_path: str, chunk_id: int) -> str:
    """Reconstruct a chunk's text deterministically from the stored source file.

    Uses an LRU cache so each PDF/text file is only read and parsed once
    per process lifetime (cleared on index rebuild).
    """
    try:
        p = sources_dir / rel_path
        raw = _read_text_cached(str(p))
        chunks = _chunk(raw)
        if chunk_id < 0 or chunk_id >= len(chunks):
            return ""
        return chunks[chunk_id]
    except Exception:
        return ""


@_lru_cache(maxsize=256)
def _read_text_cached(path_str: str) -> str:
    """Read and clean a source file, caching the result.

    PDF parsing via pypdf is expensive (page-by-page text extraction).
    This cache ensures each file is read at most once per session.
    """
    raw = _read_text(Path(path_str))
    return _clean(raw)
