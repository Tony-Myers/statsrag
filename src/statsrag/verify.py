from __future__ import annotations

import errno
import io
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import numpy as np

from statsrag.schema import AnalysisSpec
from statsrag.indexing import query as rag_query, get_chunk_text

# ============================================================
# IO helpers (macOS bind-mount robustness)
# ============================================================

def _read_file_bytes_with_retry(path: Path, *, retries: int = 6, sleep_s: float = 0.15) -> bytes:
    """
    On macOS Docker bind mounts, a just-written file can briefly raise:
      OSError: [Errno 35] Resource deadlock avoided
    We retry a few times.
    """
    last_err: OSError | None = None
    for i in range(retries):
        try:
            return path.read_bytes()
        except OSError as e:
            last_err = e
            if getattr(e, "errno", None) == errno.EDEADLK:
                time.sleep(sleep_s * (i + 1))
                continue
            raise
    assert last_err is not None
    raise last_err


def _load_csv(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    data = _read_file_bytes_with_retry(path)
    try:
        return pd.read_csv(io.BytesIO(data))
    except Exception:
        return pd.read_csv(io.BytesIO(data), engine="python")


def _df_to_markdown(df: Optional[pd.DataFrame]) -> str:
    """Render a small DataFrame to Markdown without requiring tabulate."""
    if df is None or df.empty:
        return "(no rows)"
    cols = list(df.columns)
    out: list[str] = []
    out.append("| " + " | ".join(str(c) for c in cols) + " |")
    out.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for _, row in df.iterrows():
        out.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(out)


# -------------------------
# Optional pedagogical metrics (Frequentist p-values only)
# -------------------------

def _add_s_values(coefs: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Add S-values (surprisal) column: S = -log2(p).

    This is optional and only meaningful when the coefficients table includes p-values.
    """
    if coefs is None or coefs.empty:
        return coefs
    df = coefs.copy()
    p_col = next(
        (c for c in df.columns if c.lower() in ["p", "p_value", "p.value", "pval", "p-value", "pr(>|t|)", "pr(>|z|)"]),
        None,
    )
    if not p_col:
        return df
    p_vals = pd.to_numeric(df[p_col], errors="coerce")
    df["s_value_bits"] = -np.log2(p_vals + 1e-300)
    return df


def _s_value_exaggeration_flags(coefs: Optional[pd.DataFrame], interpretation: str) -> list[str]:
    """Flag exaggerated evidential language when S-values are weak.

    Heuristic: S ≈ 4.3 corresponds to p=0.05; S ≈ 6.6 to p=0.01; S ≈ 10 to p≈0.001.
    """
    if coefs is None or coefs.empty or "s_value_bits" not in coefs.columns:
        return []
    term_col = next((c for c in coefs.columns if c.lower() in ["term", "predictor", "variable"]), None)
    if not term_col:
        return []
    t = (interpretation or "").lower()
    flags: list[str] = []
    strong_phrases = ["strong evidence", "highly significant", "conclusive", "robust", "clear evidence", "definitive"]
    for _, row in coefs.iterrows():
        term = str(row.get(term_col, "")).strip()
        if not term:
            continue
        try:
            s_val = float(row.get("s_value_bits"))
        except Exception:
            continue
        if pd.isna(s_val):
            continue
        # If S < 4.3 (~p>0.05), treat as weak evidence
        if s_val < 4.3:
            for phrase in strong_phrases:
                # term near phrase within 40 chars
                pattern = rf"({re.escape(phrase)}.{{0,40}}{re.escape(term.lower())}|{re.escape(term.lower())}.{{0,40}}{re.escape(phrase)})"
                if re.search(pattern, t):
                    flags.append(
                        f"Evidence exaggeration: text claims '{phrase}' for '{term}', but S-value is only {s_val:.1f} bits (weak evidence).\n"
                        "Consider more cautious language or report uncertainty explicitly."
                    )
                    break
    return flags
# ============================================================
# Normalisation helpers
# ============================================================

def _normalise_model_id(comp: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Ensure model_id contains plain integers.
    Handles values like 'Model1', 'Model 2', 'model_3', or already-numeric IDs.
    """
    if comp is None or comp.empty or "model_id" not in comp.columns:
        return comp
    comp = comp.copy()
    comp["model_id"] = comp["model_id"].astype(str).str.replace(r"[^0-9]", "", regex=True)
    comp["model_id"] = pd.to_numeric(comp["model_id"], errors="coerce").astype("Int64")
    return comp


def _safe_sources_dir(sources_dir: Optional[Path], index_dir: Path) -> Optional[Path]:
    """
    If UI does not pass sources_dir, try to infer it from the default /data layout.
    """
    if sources_dir is not None:
        return sources_dir
    cand = index_dir.parent / "sources"
    return cand if cand.exists() else None

# ============================================================
# Claim parsing (deterministic, high-recall)
# ============================================================

def _clean_claim(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -•\t")


def extract_claims(text: str) -> list[str]:
    """
    Deterministic claim extraction:
    - Uses numbered bullets (1), 2), etc) when present
    - Otherwise splits by blank lines/bullets, then sentence-ish splits for long blocks
    """
    t = (text or "").strip()
    if not t:
        return []

    numbered = re.findall(
        r"(?:^|\n)\s*\d+\)\s*(.+?)(?=(?:\n\s*\d+\)\s)|\Z)",
        t,
        flags=re.S,
    )
    claims = [_clean_claim(x) for x in numbered if _clean_claim(x)]
    if claims:
        return claims

    parts = re.split(r"(?:\n\s*\n)|(?:\n\s*[-•]\s+)", t)
    parts = [_clean_claim(p) for p in parts if _clean_claim(p)]

    out: list[str] = []
    for p in parts:
        if len(p) <= 220:
            out.append(p)
        else:
            sent = re.split(r"(?<=[.!?])\s+", p)
            out.extend([_clean_claim(s) for s in sent if _clean_claim(s)])

    # de-duplicate preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for c in out:
        k = c.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq[:30]

# ============================================================
# RAG retrieval utilities
# ============================================================

def _retrieve_for_query(
    index_dir: Path,
    query: str,
    *,
    top_k: int = 4,
    allowed_prefixes: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    hits_out: list[dict[str, Any]] = []
    try:
        hits = rag_query(index_dir, query, top_k=top_k, allowed_prefixes=allowed_prefixes)
    except Exception:
        hits = []

    for score, meta in hits or []:
        src = str(meta.get("path") or meta.get("source") or "")
        chunk = meta.get("chunk", -1)
        try:
            chunk_i = int(chunk)
        except Exception:
            chunk_i = -1
        hits_out.append(
            {
                "score": float(score),
                "source": src,
                "chunk": chunk_i,
                "meta": {k: v for k, v in meta.items() if k not in ("text", "content")},
            }
        )
    return hits_out


def _hydrate_chunk_text(sources_dir: Path, hit: dict[str, Any]) -> dict[str, Any]:
    rel = str(hit.get("source") or "")
    chunk = int(hit.get("chunk", -1))
    try:
        txt = get_chunk_text(sources_dir, rel, chunk)
    except Exception:
        txt = ""
    out = dict(hit)
    out["text"] = txt
    return out

# ============================================================
# Interpretation flags (cross-paradigm + frequentist + bayesian)
# ============================================================

def _has_any(t: str, words: list[str]) -> bool:
    return any(w in t for w in words)


# ============================================================
# Philosophy-aware verification
# ============================================================

# Maps each philosophy to the RAG queries most likely to retrieve
# relevant methodology literature from the philosophical sources.
_PHILOSOPHY_RAG_QUERIES: dict[str, list[str]] = {
    "realist": [
        "estimand causal identification strategy observational study",
        "model assumptions limitations specification realist",
        "statistical inference true parameter estimation",
    ],
    "constructivist": [
        "construct measurement operationalisation context dependent",
        "statistical quantification evidence constructivist Hennig",
        "alternative operationalisations measurement choices",
    ],
    "scientific_antirealist": [
        "instrumentally useful prediction empirical adequacy van Fraassen",
        "sensitivity modelling assumptions antirealist",
        "parameters mechanisms truth scientific image",
    ],
}

# Source-file prefixes expected for philosophy texts in the RAG index.
# Users should place these PDFs under a "Philosophy/" (or similar) folder
# within their sources directory.
_PHILOSOPHY_SOURCE_PREFIXES = [
    "Philosophy/",
    "philosophy/",
    "Philosophy_of_Statistics/",
    "philosophy_of_statistics/",
]


def _resolve_philosophy(spec: AnalysisSpec) -> str:
    """Return the declared philosophy name, or 'unknown'.

    Checks spec.notes["framework"]["philosophy"] first, then falls back
    to heuristic detection from the prohibitions text.
    """
    try:
        name = str(
            spec.notes.get("framework", {}).get("philosophy", "")
        ).strip().lower()
        if name in {"realist", "constructivist", "scientific_antirealist"}:
            return name
    except Exception:
        pass

    # Fallback: infer from prohibition / required-reporting content
    all_text = " ".join(spec.prohibitions + spec.required_reporting).lower()
    if "context-free facts" in all_text or "operationalis" in all_text:
        return "constructivist"
    if "instrumentally useful" in all_text or "not literal" in all_text:
        return "scientific_antirealist"
    if "estimand" in all_text or "causal identification" in all_text:
        return "realist"
    return "unknown"


def _negation_aware_match(text: str, trigger: str, window: int = 50) -> bool:
    """Return True if *trigger* appears in *text* WITHOUT a preceding negation.

    Searches all occurrences; returns True only if at least one is
    un-negated.  This lets correct disclaimers ("should not be
    interpreted as causal") suppress the flag while still catching
    genuine violations ("X causes Y").

    The window is 50 chars (≈ 8–10 words) to catch negations across
    typical clause structures like "does not establish that sex causes".
    """
    t = text.lower()
    trigger_l = trigger.lower()
    _NEG_RE = re.compile(r"\b(not|no|nor|isn'?t|never|should not|cannot|does not|do not|without)\b")
    start = 0
    while True:
        idx = t.find(trigger_l, start)
        if idx < 0:
            return False
        prefix = t[max(0, idx - window): idx]
        if not _NEG_RE.search(prefix):
            return True  # un-negated occurrence
        start = idx + 1


# ----------------------------------------------------------------
# Required-reporting compliance
# ----------------------------------------------------------------

# Each key is a normalised substring of a required_reporting item.
# The value is a list of keyword signatures whose presence in the
# interpretation suggests the requirement was met.
_COMPLIANCE_SIGNALS: dict[str, list[str]] = {
    # --- Realist ---
    "state the estimand": [
        "estimand", "predictive target", "quantity of interest",
        "target variable", "prediction target",
    ],
    "state model assumptions": [
        "assumption", "limitation", "linearity", "independence",
        "homoscedasticity", "constant variance", "residual",
    ],
    # --- Constructivist ---
    "describe how constructs": [
        "construct", "operationalis", "measurement choice",
        "how we define", "how we measure",
    ],
    "discuss alternative operationalisations": [
        "alternative operationalis", "alternative measure",
        "could also be measured", "other ways to measure",
        "different operationalis",
    ],
    # --- Scientific antirealist ---
    "frame conclusions as instrumentally useful": [
        "instrumental", "useful summar", "predictive tool",
        "not literal", "empirical adequacy", "predictive device",
    ],
    "report sensitivity": [
        "sensitivity", "robust to", "alternative specification",
        "sensitivity analysis", "sensitivity of",
    ],
    # --- Frequentist ---
    "define what a confidence interval means": [
        "repeated sampling", "long-run", "coverage",
        "repeated many times", "sampling and modelling procedure",
    ],
    "report effect sizes with confidence intervals": [
        "effect size", "confidence interval", " ci ", "95% ci",
    ],
    # --- Bayesian ---
    "state priors": [
        "prior", "weakly informative", "prior distribution",
    ],
    "report posterior summaries": [
        "posterior", "credible interval", "cri",
    ],
    "report psis-loo": [
        "pareto-k", "pareto k", "psis", "loo diagnostic",
    ],
    # --- Hybrid ---
    "clearly label which quantities are frequentist": [
        "frequentist", "bayesian",
    ],
}


def _required_reporting_flags(spec: AnalysisSpec, interpretation: str) -> list[str]:
    """Flag required-reporting items that appear absent from the interpretation."""
    t = (interpretation or "").lower()
    if not t.strip():
        return []
    flags: list[str] = []

    for req in (spec.required_reporting or []):
        req_lower = req.lower()
        # Find the best matching compliance-signal set
        signals: Optional[list[str]] = None
        for key, sigs in _COMPLIANCE_SIGNALS.items():
            if key in req_lower:
                signals = sigs
                break

        if signals is None:
            # No heuristic available — skip rather than false-positive
            continue

        if not any(s in t for s in signals):
            flags.append(
                f"Required reporting gap: the analysis profile requires "
                f"'{req}', but no evidence of this was found in the "
                f"interpretation text."
            )

    return flags


# ----------------------------------------------------------------
# Prohibition violation detection
# ----------------------------------------------------------------

# Each entry maps a normalised substring of a prohibition to:
#   (trigger_phrases, exoneration_phrases)
# A flag fires when a trigger is found WITHOUT a nearby exoneration.
_VIOLATION_PATTERNS: dict[str, tuple[list[str], list[str]]] = {
    # Realist: causal language
    "do not claim causal effects unless": (
        [
            "causes", "caused by", "causal effect of",
            "leads to", "results in", "drives",
        ],
        [
            "causal design", "causal identification", "randomised",
            "randomized", "propensity", "instrumental variable",
            "should not be interpreted as causal",
            "no causal", "not causal", "not be interpreted as causal",
            "without a causal", "no causal interpretation",
            "does not establish", "cannot establish",
            "associations are descriptive", "descriptive; causal",
            "causal interpretation requires", "causal claims require",
            "does not imply causation", "does not imply causal",
            "not imply causation", "observational design",
        ],
    ),
    # Realist: model fit ≠ truth
    "do not treat model fit as proof of truth": (
        [
            "proves the model is true", "proof that the model",
            "the true model", "model is true",
        ],
        [
            "does not prove", "not proof", "not the true model",
            "not imply", "does not imply",
        ],
    ),
    # Constructivist: context-free facts
    "do not present measurement/model outputs as context-free facts": (
        [
            "the data show that", "the results prove",
            "this demonstrates that", "the model reveals",
            "objectively shows", "the data confirm",
        ],
        [
            "in this context", "given the operationalisation",
            "under these measurement assumptions",
            "within this framework", "as operationalised",
        ],
    ),
    # Scientific antirealist: mechanisms
    "do not interpret parameters as revealing": (
        [
            "true underlying mechanism", "true mechanism",
            "reveals the mechanism", "true data-generating",
            "the real mechanism",
        ],
        [
            "instrumental", "useful summary", "as if",
            "not necessarily the true", "predictive device",
            "empirical adequacy",
        ],
    ),
    # Bayesian: CI vs CrI
    "do not interpret a credible interval as a frequentist confidence interval": (
        ["confidence interval"],
        ["credible interval", "credibility interval", "cri"],
    ),
    # Frequentist: CI probability statement
    "do not interpret a 95% confidence interval as a 95% probability statement": (
        ["95% probability that the true", "probability that the parameter"],
        [
            "not a 95% probability", "is not a probability statement",
            "repeated sampling",
        ],
    ),
}


def _prohibition_violation_flags(
    spec: AnalysisSpec, interpretation: str
) -> list[str]:
    """Flag interpretation text that appears to violate declared prohibitions."""
    t = (interpretation or "").lower()
    raw = (interpretation or "").strip()
    if not t.strip():
        return []
    flags: list[str] = []

    # Pre-split sentences for excerpt finding
    _sents = re.split(r'(?<=[.!?])\s+', raw)
    _sents = [s.strip() for s in _sents if s.strip()]

    def _find_excerpt(trigger: str, max_len: int = 120) -> str:
        for s in _sents:
            if trigger.lower() in s.lower():
                excerpt = s if len(s) <= max_len else s[:max_len].rsplit(" ", 1)[0] + " …"
                return f'\n  ↳ Found in: "{excerpt}"'
        return ""

    for prohibition in (spec.prohibitions or []):
        p_lower = prohibition.lower()
        for key, (triggers, exonerations) in _VIOLATION_PATTERNS.items():
            if key not in p_lower:
                continue
            for trigger in triggers:
                if _negation_aware_match(t, trigger):
                    # Check for exonerating context anywhere in text
                    if any(e in t for e in exonerations):
                        break  # likely a correct disclaimer
                    flags.append(
                        f"Possible prohibition violation: '{prohibition}' — "
                        f"detected '{trigger}' in interpretation without "
                        f"qualifying language."
                        + _find_excerpt(trigger)
                    )
                    break  # one flag per prohibition is enough
            break  # only match one pattern block per prohibition

    return flags


# ----------------------------------------------------------------
# Philosophy RAG retrieval (targeted queries against source texts)
# ----------------------------------------------------------------

def _philosophy_rag_retrieval(
    philosophy: str,
    interpretation: str,
    index_dir: Path,
    sources_dir: Optional[Path],
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Run philosophy-specific queries against the RAG index.

    Queries are designed to retrieve chunks from the philosophical
    methodology literature (Mayo, van Fraassen, Hennig, Bernardo & Smith,
    etc.) that are most relevant to verifying compliance with the
    declared framework.

    Returns a flat list of hits (de-duplicated by source+chunk).
    """
    queries = _PHILOSOPHY_RAG_QUERIES.get(philosophy, [])
    if not queries:
        return []

    seen: set[tuple[str, int]] = set()
    all_hits: list[dict[str, Any]] = []

    for q in queries:
        hits = _retrieve_for_query(
            index_dir,
            q,
            top_k=top_k,
            allowed_prefixes=_PHILOSOPHY_SOURCE_PREFIXES,
        )
        # If no hits with philosophy prefixes, try without prefix filter
        # (user may have placed sources in the root)
        if not hits:
            hits = _retrieve_for_query(index_dir, q, top_k=top_k)

        for h in hits:
            key = (h["source"], h["chunk"])
            if key not in seen:
                seen.add(key)
                if sources_dir is not None:
                    h = _hydrate_chunk_text(sources_dir, h)
                all_hits.append(h)

    return all_hits


def _coefficient_direction_flags(coefs: Optional[pd.DataFrame], interpretation: str) -> list[str]:
    """
    Heuristic check: If text mentions a predictor and a direction ('increase', 'positive'),
    ensure the coefficient sign matches.
    """
    if coefs is None or coefs.empty:
        return []
        
    flags = []
    t = (interpretation or "").lower()
    
    # Map common semantic direction words to sign
    dir_map = {
        "positive": 1, "increases": 1, "higher": 1, "associated with higher": 1,
        "negative": -1, "decreases": -1, "lower": -1, "associated with lower": -1
    }
    
    # Iterate over predictors found in the CSV (assuming column 'term' or 'predictor')
    # You might need to normalise column names in your CSV loader
    term_col = next((c for c in coefs.columns if c.lower() in ['term', 'predictor', 'variable']), None)
    estimate_col = next((c for c in coefs.columns if c.lower() in ['estimate', 'coef', 'beta']), None)
    
    if not term_col or not estimate_col:
        return []

    sentences = re.split(r'[.!?]', t)
    
    for _, row in coefs.iterrows():
        term = str(row[term_col]).strip()
        val = pd.to_numeric(row[estimate_col], errors='coerce')
        if pd.isna(val) or val == 0:
            continue
            
        real_sign = 1 if val > 0 else -1
        
        # Simple regex to find the term in a sentence
        # (This is heuristic; dependency parsing would be better but requires spaCy)
        for sent in sentences:
            if re.search(r"\b" + re.escape(term.lower()) + r"\b", sent):
                # Check for direction words in the SAME sentence
                for word, implied_sign in dir_map.items():
                    if f" {word} " in sent:
                        if implied_sign != real_sign:
                            flags.append(
                                f"Direction contradiction for **{term}**: Text says '{word}' "
                                f"but coefficient is {val:.4f} (sign: {'+' if real_sign>0 else '-'}). "
                                f"Context: \"...{sent.strip()}...\""
                            )
    return flags

def _interpretation_flags(interpretation: str, prob_mode: str) -> list[str]:
    t = (interpretation or "").lower()
    raw = (interpretation or "").strip()  # preserve original case for quoting
    flags: list[str] = []

    # Split into sentences once (used by all excerpt-finding below)
    _sentences_raw = re.split(r'(?<=[.!?])\s+', raw)
    _sentences_raw = [s.strip() for s in _sentences_raw if s.strip()]

    def _excerpt(phrases: list[str], *, max_quotes: int = 3, max_len: int = 120) -> str:
        """Find sentences containing any of the phrases and return formatted excerpts."""
        found: list[str] = []
        for s in _sentences_raw:
            sl = s.lower()
            for p in phrases:
                if p.lower() in sl:
                    # Truncate long sentences
                    excerpt = s if len(s) <= max_len else s[:max_len].rsplit(" ", 1)[0] + " …"
                    if excerpt not in found:
                        found.append(excerpt)
                    break
            if len(found) >= max_quotes:
                break
        if not found:
            return ""
        quoted = " | ".join(f'"{f}"' for f in found)
        return f"\n  ↳ Found in: {quoted}"

    # Cross-paradigm: causal language without causal design
    causal_phrases = [
        "causes", "caused by", "causing", "leads to", "results in",
        "drives", "will increase", "will decrease",
    ]
    # Formal causal design terms — if ANY appears anywhere, suppress the flag
    causal_design_words = [
        "randomised", "randomized", "instrument", "iv ", "dag",
        "identification", "causal design", "causal inference",
        "propensity", "quasi-experiment", "difference-in-differences",
        "regression discontinuity", "matching",
    ]
    # Document-level disclaimers — if ANY appears anywhere, suppress the flag
    causal_disclaimers_global = [
        "associations are descriptive",
        "descriptive; causal",
        "descriptive, causal",
        "causal interpretation requires",
        "causal claims require",
        "not be interpreted as causal",
        "should not be interpreted causally",
        "no causal interpretation",
        "no causal claims",
        "not imply causation",
        "does not imply causation",
        "does not imply causal",
        "correlation does not imply",
        "association does not imply",
        "observational design limits causal",
        "observational study",
    ]
    # Sentence-level negation / qualifying context — suppress for THAT sentence only
    _causal_negations = [
        "does not establish", "do not establish",
        "does not cause", "do not cause",
        "does not imply", "do not imply",
        "not causal", "no causal",
        "not establish that", "cannot establish",
        "rather than causal", "not necessarily causal",
        "without causal", "absent causal",
        "causal interpretation requires",
        "causal claims require",
        "descriptive",
    ]

    _has_design_word = _has_any(t, causal_design_words)
    _has_global_disclaimer = _has_any(t, causal_disclaimers_global)

    if not _has_design_word and not _has_global_disclaimer:
        # Sentence-level check: only flag sentences with assertive causal language
        _causal_offenders: list[str] = []
        for s in _sentences_raw:
            sl = s.lower()
            # Does this sentence contain a causal phrase?
            has_causal = any(cp in sl for cp in causal_phrases)
            if not has_causal:
                continue
            # Is it negated / disclaimed within the same sentence?
            is_negated = any(neg in sl for neg in _causal_negations)
            if is_negated:
                continue
            # This sentence makes an assertive causal claim
            excerpt = s if len(s) <= 120 else s[:120].rsplit(" ", 1)[0] + " …"
            if excerpt not in _causal_offenders:
                _causal_offenders.append(excerpt)
            if len(_causal_offenders) >= 3:
                break

        if _causal_offenders:
            quoted = " | ".join(f'"{e}"' for e in _causal_offenders)
            flags.append(
                "Causal language detected without an explicit causal identification strategy. "
                "Prefer 'associated with' / 'predicts' unless a causal design is declared."
                f"\n  ↳ Found in: {quoted}"
            )

    # Cross-paradigm: overclaims
    if re.search(r"\b(proves?|proof\s+that|proven)\b", t):
        flags.append(
            "Overstatement: 'proves' / 'proof' is too strong for statistical evidence; "
            "use calibrated language such as 'suggests', 'supports', or 'is consistent with'."
            + _excerpt(["proves", "proof that", "proven", "proof "])
        )
    if re.search(r"\bguarantees?\b", t):
        flags.append(
            "Overstatement: 'guarantees' is too strong. Statistical transformations and "
            "procedures do not guarantee assumptions are met."
            + _excerpt(["guarantee", "guarantees"])
        )
    if re.search(r"\b(always|in all settings|in all cases|in every case|never)\b", t):
        flags.append(
            "Overgeneralisation: universal claims ('always', 'in all settings', 'never') "
            "are rarely justified from a single analysis."
            + _excerpt(["always", "in all settings", "in all cases", "in every case", "never"])
        )

    # Cross-paradigm: diagnostics dismissal
    if re.search(
        r"\b(no\s+(?:further|additional)\s+diagnostics?\s+(?:needed|necessary|required)|"
        r"diagnostics?\s+(?:are\s+)?unnecessary)\b",
        t,
    ):
        flags.append(
            "Claim that no further diagnostics are needed. Model diagnostics should always "
            "be reviewed; this claim requires explicit justification."
            + _excerpt(["no further diagnostic", "no additional diagnostic", "diagnostics unnecessary",
                        "diagnostics are unnecessary", "diagnostics needed", "diagnostics necessary"])
        )

    # Cross-paradigm: uncertainty reporting dismissal
    if re.search(
        r"\bno\s+(?:further|additional)\s+(?:uncertainty\s+)?reporting\s+(?:is\s+)?(?:needed|necessary|required)\b",
        t,
    ):
        flags.append(
            "Uncertainty-reporting dismissal detected. Uncertainty quantification (intervals, "
            "calibration, prediction intervals) should always be reported alongside point estimates."
            + _excerpt(["no further reporting", "no additional reporting",
                        "no further uncertainty", "no additional uncertainty"])
        )

    # Transportability / external validation
    if re.search(r"\bwithout\s+(?:the\s+need\s+for\s+)?external\s+validation\b", t) and re.search(r"\bgenerali[sz]e", t):
        flags.append(
            "Claim that results generalise without external validation. Internal cross-validation "
            "does not establish transportability to new populations."
            + _excerpt(["without external validation", "generalise", "generalize"])
        )

    # Frequentist-specific
    if prob_mode == "frequentist":
        # CI misinterpretation — but allow correct disclaimers like
        # "It is not a 95% probability statement about the parameter"
        _ci_misinterp = False
        _ci_match_text = ""
        if "confidence interval" in t:
            for _ci_pat in [r"95%\s+probability", r"probability\s+that\s+the\s+true"]:
                for _m in re.finditer(_ci_pat, t):
                    # Check whether the match is preceded by a negation within 20 chars
                    _prefix = t[max(0, _m.start() - 20) : _m.start()]
                    if not re.search(r"\bnot\b|\bnor\b|\bisn'?t\b|\bnever\b|\bno\b|\bnot a\b", _prefix):
                        _ci_misinterp = True
                        # Extract surrounding context from the raw text for the excerpt
                        _ci_match_text = raw[max(0, _m.start() - 40) : min(len(raw), _m.end() + 60)].strip()
                        break
                if _ci_misinterp:
                    break
        if _ci_misinterp:
            _ci_excerpt = f'\n  ↳ Found in: "…{_ci_match_text}…"' if _ci_match_text else ""
            flags.append(
                "Confidence interval misinterpretation: a 95% CI is not a 95% probability "
                "statement about the parameter."
                + _ci_excerpt
            )

        # p-value misinterpretation — same negation-aware logic
        _pv_misinterp = False
        _pv_match_text = ""
        if "p-value" in t:
            for _pv_pat in [r"probability\s+that\s+the\s+null", r"probability\s+the\s+null\s+is\s+true"]:
                for _m in re.finditer(_pv_pat, t):
                    _prefix = t[max(0, _m.start() - 20) : _m.start()]
                    if not re.search(r"\bnot\b|\bnor\b|\bisn'?t\b|\bnever\b|\bno\b|\bnot a\b", _prefix):
                        _pv_misinterp = True
                        _pv_match_text = raw[max(0, _m.start() - 40) : min(len(raw), _m.end() + 60)].strip()
                        break
                if _pv_misinterp:
                    break
        if _pv_misinterp:
            _pv_excerpt = f'\n  ↳ Found in: "…{_pv_match_text}…"' if _pv_match_text else ""
            flags.append(
                "p-value misinterpretation: a p-value is not the probability that the null "
                "hypothesis is true."
                + _pv_excerpt
            )
        if ("aic" in t or "bic" in t) and re.search(r"\b(true\s+with\s+high\s+probability|therefore\s+it\s+is\s+true)\b", t):
            flags.append(
                "Model selection overclaim: information criteria do not imply a model is "
                "'true' or 'true with high probability'."
                + _excerpt(["true with high probability", "therefore it is true"])
            )
        if re.search(r"\b(aic|bic)\b", t) and re.search(r"\bno\s+(?:additional|further)\s+uncertainty\b", t):
            flags.append(
                "Uncertainty reporting overclaim: selecting by AIC/BIC does not remove uncertainty; "
                "report uncertainty (intervals, calibration, prediction intervals) for the chosen model."
                + _excerpt(["no additional uncertainty", "no further uncertainty"])
            )

    # Bayesian-specific
    if prob_mode == "bayesian":
        if "confidence interval" in t and "credible interval" not in t and "credibility interval" not in t:
            flags.append(
                "Bayesian reporting: uses 'confidence interval' language; prefer 'credible "
                "interval' for posterior intervals."
                + _excerpt(["confidence interval"])
            )
        if "bayes factor" in t and re.search(r"\b(true|proved|proves)\b", t):
            flags.append(
                "Bayes factor overclaim: Bayes factors compare relative evidence; they do not prove a model is true."
                + _excerpt(["bayes factor", "true", "proved", "proves"])
            )
        if re.search(r"\b(highest|largest)\s+(looic|waic)\b", t):
            flags.append(
                "Direction error: LOOIC/WAIC are on a deviance scale — lower is better (analogous to AIC)."
                + _excerpt(["highest looic", "largest looic", "highest waic", "largest waic"])
            )
        if re.search(r"\b(smallest|lowest)\s+elpd\b", t):
            flags.append(
                "Direction error: ELPD — higher is better. 'Lowest ELPD' indicates the worst predictive performance."
                + _excerpt(["smallest elpd", "lowest elpd"])
            )
        if re.search(r"\bposterior probability\b", t) and re.search(r"\b(aic|bic)\b", t):
            flags.append(
                "Framework mixing: posterior probability claims are not supported by AIC/BIC."
                + _excerpt(["posterior probability"])
            )

    # CV vs LOO equivalence claim
    if re.search(r"\b(k[-\s]?fold|kfold)\b.*\b(equivalent|same as)\b.*\b(loo|psis[-\s]?loo|elpd)\b", t, flags=re.S):
        flags.append(
            "Method equivalence claim: k-fold RMSE is not generally equivalent to PSIS-LOO ELPD; "
            "they target different quantities and scales."
            + _excerpt(["equivalent", "same as"])
        )

    return flags


def _interpretation_flags_grouped(interpretation: str, prob_mode: str) -> dict[str, list[str]]:
    """Return interpretation flags grouped into (cross, frequentist, bayesian, hybrid)."""
    prob_mode = (prob_mode or "").strip().lower()
    if prob_mode not in {"frequentist", "bayesian", "hybrid"}:
        prob_mode = "frequentist"

    # Get the full list using the existing rule set
    all_flags = _interpretation_flags(interpretation, prob_mode)

    grouped: dict[str, list[str]] = {"cross": [], "frequentist": [], "bayesian": [], "hybrid": []}

    # Heuristic grouping based on rule text. (Keeps behaviour stable while improving report structure.)
    for f in all_flags:
        fl = f.lower()
        if "bayesian" in fl or "credible" in fl or "posterior" in fl or "bayes factor" in fl or "looic/waic" in fl or "elpd" in fl:
            grouped["bayesian"].append(f)
        elif "confidence interval misinterpretation" in fl or "p-value misinterpretation" in fl or "aic/bic" in fl or "information criterion" in fl:
            grouped["frequentist"].append(f)
        elif "equivalence" in fl or "k-fold" in fl or "psis-loo" in fl:
            grouped["hybrid"].append(f)
        else:
            grouped["cross"].append(f)

    # Additional Bayesian-specific checks that are easy to miss
    t = (interpretation or "").lower()
    if prob_mode in {"bayesian", "hybrid"}:
        if re.search(r"\bposterior probability\b", t) and re.search(r"\b(aic|bic)\b", t):
            grouped["bayesian"].append("Bayesian/frequentist mixing: posterior probability claims are not supported by AIC/BIC.")
        if re.search(r"\bposterior probability\b", t) and re.search(r"\bbayes factor\b|\bbf\b", t) and not re.search(r"prior odds|model prior|prior probability", t):
            grouped["bayesian"].append("Posterior model probability claim: if using Bayes factors, posterior probabilities require explicit model priors (and prior odds).")

        if re.search(r"\bbayes factor\b|\bbf\b", t) and re.search(r"probability that", t):
            grouped["bayesian"].append("Bayes factor misinterpretation: a Bayes factor is a likelihood ratio (evidence multiplier), not a posterior probability.")

    return grouped


def _transformation_mismatch_flags(spec: AnalysisSpec, interpretation: str) -> list[str]:
    t = (interpretation or "").lower()
    flags: list[str] = []

    # Read the declared transformation from schema and/or notes
    spec_log_outcome = False
    try:
        spec_log_outcome = bool(spec.transformations.log_outcome)
    except Exception:
        pass

    spec_transform = "none"
    try:
        spec_transform = str(spec.notes.get("modeling", {}).get("outcome_transform", "")).strip().lower()
    except Exception:
        pass
    if not spec_transform or spec_transform not in ("log", "sqrt", "boxcox", "none"):
        spec_transform = "log" if spec_log_outcome else "none"

    claims_boxcox = bool(re.search(r"\bbox[\s-]?(?:and\s+)?cox\b", t))
    claims_log = bool(re.search(r"\blog[\s-]?transform", t))
    claims_sqrt = bool(re.search(r"\bsquare[\s-]?root\s+transform", t))

    # Mismatch: spec says log but interpretation says Box-Cox
    if spec_transform == "log" and claims_boxcox:
        flags.append(
            "Transformation mismatch: the analysis spec declares a standard log transform for the outcome, "
            "but the interpretation refers to a Box–Cox transformation. Log is a special case (λ = 0) "
            "within Box–Cox, but claiming Box–Cox was used when only log was specified is inaccurate."
        )

    # Mismatch: spec says boxcox but interpretation says plain log
    if spec_transform == "boxcox" and claims_log and not claims_boxcox:
        flags.append(
            "Transformation mismatch: the analysis spec declares a Box-Cox transformation, "
            "but the interpretation refers only to a log transform. If Box-Cox selected "
            "λ ≈ 0, state this explicitly; otherwise the interpretation does not match "
            "the declared procedure."
        )

    # Mismatch: spec says sqrt but interpretation says log or boxcox
    if spec_transform == "sqrt" and (claims_log or claims_boxcox):
        claimed_name = "Box-Cox" if claims_boxcox else "log"
        flags.append(
            "Transformation mismatch: the analysis spec declares a square-root transform, "
            f"but the interpretation refers to a {claimed_name} transformation."
        )

    # Overclaim regardless of spec
    if claims_boxcox and re.search(r"\bguarantees?\b", t):
        flags.append(
            "Box–Cox overclaim: Box–Cox may improve normality/variance stabilisation, but it does not guarantee "
            "normality, homoscedasticity, or independence."
        )
    return flags


def _diagnostics_contradiction_flags(diags: Optional[dict], interpretation: str) -> list[str]:
    if diags is None:
        return []
    t = (interpretation or "").lower()
    diags_str = json.dumps(diags).lower()
    flags: list[str] = []
    claims_no_diagnostics = bool(
        re.search(
            r"\b(no\s+(?:further|additional)\s+diagnostics?\s+(?:needed|necessary|required)|diagnostics?\s+(?:are\s+)?unnecessary)\b",
            t,
        )
    )
    has_influential = any(w in diags_str for w in ["cook", "influential", "high leverage", "outlier", "dfbetas"])
    if has_influential and claims_no_diagnostics:
        flags.append(
            "Diagnostics contradiction: diagnostics.json indicates potential influential observations/outliers, "
            "but the interpretation claims no further diagnostics are needed. Influential points typically warrant sensitivity checks."
        )
    return flags


def _transformation_notes(spec: AnalysisSpec) -> list[str]:
    """
    Return informational advisories (not errors) about the declared
    transformation.  These appear in the report as notes, not problems.
    """
    notes: list[str] = []

    # Determine the declared transformation
    spec_log_outcome = False
    try:
        spec_log_outcome = bool(spec.transformations.log_outcome)
    except Exception:
        pass

    spec_transform = "none"
    try:
        spec_transform = str(spec.notes.get("modeling", {}).get("outcome_transform", "")).strip().lower()
    except Exception:
        pass
    if not spec_transform or spec_transform not in ("log", "sqrt", "boxcox", "none"):
        spec_transform = "log" if spec_log_outcome else "none"

    if spec_transform == "log":
        notes.append(
            "**Log-transform rationale:** A log transformation of the outcome is often "
            "appropriate when the outcome is strictly positive and the residual variance "
            "scales with the mean (multiplicative errors). For body-size/performance "
            "data this is common because biological scaling relationships are "
            "typically allometric (power-law), and log-linearisation converts them "
            "to additive models suitable for OLS or mixed-effects regression."
        )
        notes.append(
            "**Back-transformation caution:** Coefficients fitted on the log scale "
            "describe proportional (multiplicative) rather than absolute changes. "
            "Exponentiating a log-scale coefficient gives a ratio (e.g. exp(b) ≈ 1.05 "
            "means a ≈5 % increase per unit change in X). However, back-transforming "
            "predictions requires care: exp(E[log Y]) ≠ E[Y] due to Jensen's inequality. "
            "If absolute-scale predictions are needed, apply a smearing estimate "
            "(Duan, 1983) or half-variance correction (exp(μ + σ²/2)) to avoid "
            "systematic under-prediction. Report whether results are presented on "
            "the log scale or the original scale, and which correction (if any) was used."
        )
        notes.append(
            "**Alternative transformations:** While the current spec uses a standard "
            "log (λ = 0 in the Box-Cox family), other transformations may be worth "
            "considering. A Box-Cox profile-likelihood search over λ can identify "
            "whether a different power transformation better stabilises variance "
            "and normalises residuals. However, Box-Cox does not guarantee that "
            "assumptions are met — it seeks to improve them — and the chosen λ "
            "should be checked empirically via residual diagnostics."
        )

    elif spec_transform == "sqrt":
        notes.append(
            "**Square-root transform rationale:** A square-root transformation is a "
            "milder variance-stabiliser than log and is sometimes used for count-like "
            "data or when variance is roughly proportional to the mean (Poisson-type "
            "structure). It belongs to the Box-Cox family at λ = 0.5."
        )
        notes.append(
            "**Back-transformation caution:** Coefficients on the sqrt scale do not "
            "have a simple multiplicative interpretation. Back-transforming predictions "
            "by squaring fitted values introduces bias analogous to the log case "
            "(E[√Y]² ≠ E[Y]). If absolute-scale predictions are required, a bias "
            "correction should be applied."
        )

    elif spec_transform == "boxcox":
        notes.append(
            "**Box-Cox rationale:** A Box-Cox transformation searches over the family "
            "Y^(λ) (with log as the special case λ = 0) to find the power that best "
            "stabilises variance and normalises residuals. The profile-likelihood "
            "estimate of λ should be reported alongside diagnostic checks confirming "
            "the transformation achieved its intended effect."
        )
        notes.append(
            "**Back-transformation caution:** For λ ≠ 0 and λ ≠ 1, back-transforming "
            "predictions from the Box-Cox scale to the original scale is non-trivial. "
            "A naive inverse (raising to the power 1/λ) introduces systematic bias. "
            "Bias-corrected back-transformation (e.g. Taylor-expansion or simulation-"
            "based methods) should be used, and the report should state which "
            "correction was applied and on which scale results are presented."
        )
        notes.append(
            "**Box-Cox does not guarantee assumptions are met.** It seeks to improve "
            "normality and homoscedasticity but the result must be verified empirically "
            "via residual diagnostics. Over-reliance on the transformation without "
            "checking residuals is a common error."
        )

    return notes


# ============================================================
# Model selection verification (AIC/BIC/LOOIC/WAIC/ELPD/BF)
# ============================================================

@dataclass
class BestEntry:
    model_id: int
    value: float
    col: str


def _best_min(comp: pd.DataFrame, col: str) -> Optional[BestEntry]:
    if col not in comp.columns:
        return None
    s = pd.to_numeric(comp[col], errors="coerce")
    if s.isna().all():
        return None
    i = s.idxmin()
    row = comp.loc[i]
    if pd.isna(row["model_id"]):
        return None
    return BestEntry(model_id=int(row["model_id"]), value=float(s.loc[i]), col=col)


def _best_max(comp: pd.DataFrame, col: str) -> Optional[BestEntry]:
    if col not in comp.columns:
        return None
    s = pd.to_numeric(comp[col], errors="coerce")
    if s.isna().all():
        return None
    i = s.idxmax()
    row = comp.loc[i]
    if pd.isna(row["model_id"]):
        return None
    return BestEntry(model_id=int(row["model_id"]), value=float(s.loc[i]), col=col)


def _find_best_models(comp: Optional[pd.DataFrame]) -> dict[str, BestEntry]:
    comp = _normalise_model_id(comp)
    if comp is None or comp.empty or "model_id" not in comp.columns:
        return {}
    best: dict[str, BestEntry] = {}
    for col in ["aic", "bic", "looic", "waic", "rmse_log", "rmse_raw", "mae", "bf01"]:
        r = _best_min(comp, col)
        if r:
            best[col] = r
    for col in ["elpd_loo", "elpd_waic", "r2", "bf10"]:
        r = _best_max(comp, col)
        if r:
            best[col] = r
    return best


def _format_model_row(
    comp: Optional[pd.DataFrame],
    model_id: int,
    formula_map: Optional[dict[int, str]] = None,
) -> str:
    if comp is None or comp.empty or "model_id" not in comp.columns:
        return f"model_id={model_id}"
    comp = _normalise_model_id(comp)
    sub = comp.loc[comp["model_id"] == model_id]
    if sub.empty:
        return f"model_id={model_id}"
    row = sub.iloc[0].to_dict()
    keys = ["model_id", "aic", "bic", "looic", "waic", "elpd_loo", "rmse_log", "rmse_raw", "mae", "r2", "bf10", "bf01"]
    parts: list[str] = []
    for k in keys:
        if k in row and pd.notna(row[k]):
            if k == "model_id":
                parts.append(f"model_id={int(row[k])}")
            else:
                try:
                    parts.append(f"{k}={float(row[k]):.4g}")
                except Exception:
                    parts.append(f"{k}={row[k]}")
    base = ", ".join(parts)
    if formula_map and model_id in formula_map:
        base += f" | `{formula_map[model_id]}`"
    return base


_MODEL_CLAIM_PATTERNS = [
    (re.compile(r"\bmodel\s*([0-9]+)\b.*?\b(lowest|smallest)\s+aic\b", re.I | re.S), "aic", "AIC (lowest)"),
    (re.compile(r"\b(lowest|smallest)\s+aic\b.*?\bmodel\s*([0-9]+)\b", re.I | re.S), "aic", "AIC (lowest)"),
    (re.compile(r"\bmodel\s*([0-9]+)\b.*?\b(lowest|smallest)\s+bic\b", re.I | re.S), "bic", "BIC (lowest)"),
    (re.compile(r"\b(lowest|smallest)\s+bic\b.*?\bmodel\s*([0-9]+)\b", re.I | re.S), "bic", "BIC (lowest)"),
    (re.compile(r"\bmodel\s*([0-9]+)\b.*?\b(lowest|smallest)\s+looic\b", re.I | re.S), "looic", "LOOIC (lowest)"),
    (re.compile(r"\b(lowest|smallest)\s+looic\b.*?\bmodel\s*([0-9]+)\b", re.I | re.S), "looic", "LOOIC (lowest)"),
    (re.compile(r"\bmodel\s*([0-9]+)\b.*?\b(lowest|smallest)\s+waic\b", re.I | re.S), "waic", "WAIC (lowest)"),
    (re.compile(r"\b(lowest|smallest)\s+waic\b.*?\bmodel\s*([0-9]+)\b", re.I | re.S), "waic", "WAIC (lowest)"),
    (re.compile(r"\bmodel\s*([0-9]+)\b.*?\b(highest|largest)\s+elpd\b", re.I | re.S), "elpd_loo", "ELPD (highest)"),
    (re.compile(r"\b(highest|largest)\s+elpd\b.*?\bmodel\s*([0-9]+)\b", re.I | re.S), "elpd_loo", "ELPD (highest)"),
    (re.compile(r"\bmodel\s*([0-9]+)\b.*?\b(highest|largest)\s+bayes\s+factor\b", re.I | re.S), "bf10", "Bayes factor BF10 (highest)"),
    (re.compile(r"\bmodel\s*([0-9]+)\b.*?\b(lowest|smallest)\s+bf01\b", re.I | re.S), "bf01", "Bayes factor BF01 (lowest)"),
]

_BEST_MODEL_RE = re.compile(
    r"\bmodel\s*([0-9]+)\s+(?:is|was|seems|appears)\s+(?:the\s+)?(?:best|preferred|optimal)\b",
    re.I,
)


def _model_selection_flags(interpretation: str, spec: AnalysisSpec, comp: Optional[pd.DataFrame]) -> list[str]:
    comp = _normalise_model_id(comp)
    if comp is None or comp.empty:
        return []

    best = _find_best_models(comp)
    flags: list[str] = []
    text = interpretation or ""

    # Build formula lookup from spec (1-indexed)
    formula_map: dict[int, str] = {}
    try:
        for i, f in enumerate(spec.candidate_models, start=1):
            formula_map[i] = f
    except Exception:
        pass

    for rx, key, label in _MODEL_CLAIM_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        g1 = m.group(1) if m.groups() else None
        g2 = m.group(2) if len(m.groups()) >= 2 else None
        model_str = g1 if (g1 and str(g1).isdigit()) else (g2 if (g2 and str(g2).isdigit()) else None)
        if not model_str:
            continue
        claimed = int(model_str)

        actual = best.get(key)
        if actual is None and key == "elpd_loo":
            actual = best.get("elpd_waic")
        if actual is None:
            continue

        if claimed != actual.model_id:
            flags.append(
                f"Model-selection contradiction ({label}): interpretation claims Model {claimed}, but "
                f"model_comparison.csv indicates Model {actual.model_id}. "
                f"(Claimed: {_format_model_row(comp, claimed, formula_map)} ; "
                f"Actual best: {_format_model_row(comp, actual.model_id, formula_map)})."
            )

    m = _BEST_MODEL_RE.search(text)
    if m:
        claimed = int(m.group(1))
        ic = (spec.information_criterion or "").strip().lower()
        ic_map = {"aic": "aic", "bic": "bic", "loo": "looic", "looic": "looic", "waic": "waic"}
        col = ic_map.get(ic)

        actual = best.get(col) if col else None
        if actual is None:
            for c in ["aic", "looic", "waic", "bic"]:
                if c in best:
                    col = c
                    actual = best[c]
                    break

        if actual is not None and claimed != actual.model_id:
            flags.append(
                f"Wrong 'best model' claim under {str(col).upper()}: interpretation says Model {claimed} is best, "
                f"but model_comparison.csv indicates Model {actual.model_id} is best under {str(col).upper()}. "
                f"(Claimed: {_format_model_row(comp, claimed, formula_map)} ; "
                f"Actual best: {_format_model_row(comp, actual.model_id, formula_map)})."
            )

    if re.search(r"\b(aic|bic|looic|waic)\b", text.lower()) and re.search(r"\b(true\s+with\s+high\s+probability|therefore\s+it\s+is\s+true)\b", text.lower()):
        flags.append("Model selection overclaim: information criteria do not imply a model is true or true with high probability.")

    return flags

# ============================================================
# Main report builder
# ============================================================

def build_report(
    spec: AnalysisSpec,
    run_dir: Path,
    interpretation: str,
    index_dir: Path,
    sources_dir: Optional[Path] = None,
    allowed_prefixes: Optional[list[str]] = None,
    include_s_values: bool = False,
) -> str:
    _t0 = time.monotonic()
    _timings: dict[str, float] = {}

    sources_dir = _safe_sources_dir(sources_dir, index_dir)

    comp = _load_csv(run_dir / "model_comparison.csv")
    comp = _normalise_model_id(comp)
    best_models: dict[str, Any] = _find_best_models(comp) if comp is not None and not comp.empty else {}
    coefs = _load_csv(run_dir / "model_coefficients.csv")

    diags = None
    diag_path = run_dir / "diagnostics.json"
    if diag_path.exists():
        try:
            diags = json.loads(diag_path.read_text(encoding="utf-8"))
        except Exception:
            diags = None

    brief = ""
    if isinstance(spec.notes, dict):
        brief = (spec.notes.get("project_brief") or "").strip()

    prob_mode = ""
    try:
        prob_mode = str(spec.notes.get("framework", {}).get("probability", "")).strip().lower()
    except Exception:
        prob_mode = ""
    if prob_mode not in {"frequentist", "bayesian", "hybrid"}:
        prob_mode = "frequentist"

    # Resolve the philosophical framework
    philosophy = _resolve_philosophy(spec)

    # Optional: compute S-values (Frequentist p-values only; opt-in)
    if include_s_values and prob_mode == "frequentist":
        coefs = _add_s_values(coefs)

    lines: list[str] = []
    lines.append(f"# statsrag verification report — run `{run_dir.name}`\n")

    if brief:
        lines.append("## Project brief\n")
        lines.append(brief + "\n")

    lines.append("## Spec summary")
    lines.append(f"- Objective: {spec.objective}")
    lines.append(f"- Outcome: `{spec.outcome}`")

    # Analysis type
    _analysis_type = str((spec.notes or {}).get("analysis_type", "regression")).strip().lower()
    _atype_labels = {
        "regression": "regression / modelling",
        "group_comparison": "group comparison (difference test)",
        "correlation": "correlation / association",
    }
    lines.append(f"- Analysis type: {_atype_labels.get(_analysis_type, _analysis_type)}")

    # Analysis-type-specific details
    if _analysis_type == "group_comparison":
        _comp = (spec.notes or {}).get("comparison", {})
        lines.append(f"- Design: {_comp.get('design', '?')}")
        lines.append(f"- Parametric: {'yes' if _comp.get('parametric', True) else 'no (non-parametric)'}")
        lines.append(f"- Effect size: {_comp.get('effect_size', '?')}")
        if _comp.get("bayes_method"):
            lines.append(f"- Bayesian method: {_comp['bayes_method']}")
    elif _analysis_type == "correlation":
        _corr = (spec.notes or {}).get("correlation", {})
        lines.append(f"- Correlation method: {_corr.get('method', '?')}")
        lines.append(f"- Variables: {', '.join(_corr.get('variables', []))}")
        if _corr.get("partial"):
            lines.append(f"- Partial correlation, controlling for: {', '.join(_corr.get('partial_vars', []))}")
        if _corr.get("bayes_method"):
            lines.append(f"- Bayesian method: {_corr['bayes_method']}")

    # Determine the declared transformation for display
    _spec_transform = "none"
    try:
        _spec_transform = str(spec.notes.get("modeling", {}).get("outcome_transform", "")).strip().lower()
    except Exception:
        pass
    if not _spec_transform or _spec_transform not in ("log", "sqrt", "boxcox", "none"):
        try:
            _spec_transform = "log" if spec.transformations.log_outcome else "none"
        except Exception:
            _spec_transform = "none"
    _transform_labels = {
        "none": "none (raw scale)", "log": "log (natural logarithm)",
        "sqrt": "square-root", "boxcox": "Box-Cox (data-driven λ)",
    }
    lines.append(f"- Outcome transformation: {_transform_labels.get(_spec_transform, _spec_transform)}")

    # Response distribution / family
    _modeling = {}
    try:
        _modeling = spec.notes.get("modeling", {}) or {}
    except Exception:
        pass
    _resp_family = str(_modeling.get("response_family", "gaussian")).strip()
    if _resp_family and _resp_family != "gaussian":
        lines.append(f"- Response distribution: {_resp_family}")

    # Random effects
    _re_info = _modeling.get("random_effects", {})
    if isinstance(_re_info, dict) and _re_info.get("structure", "none") != "none":
        _re_str = _re_info.get("formula_string", "")
        if _re_str:
            lines.append(f"- Random effects: `{_re_str}`")
    else:
        # Backward compat: old random_intercept field
        _ri = _modeling.get("random_intercept", "")
        if _ri:
            lines.append(f"- Random intercept: `(1|{_ri})`")

    lines.append(f"- Candidate models in spec: {len(spec.candidate_models)}")
    lines.append(f"- Validation: {spec.validation.method} (metric: {spec.validation.metric}, seed: {spec.validation.seed})")
    lines.append(f"- Information criterion (as chosen in spec): {spec.information_criterion}")
    lines.append(f"- Probability framework: {prob_mode}")
    lines.append(f"- Philosophical framework: {philosophy}")
    lines.append("")

    # Build formula lookup (1-indexed model_id → R formula string)
    formula_map: dict[int, str] = {}
    try:
        for _i, _f in enumerate(spec.candidate_models, start=1):
            formula_map[_i] = _f
    except Exception:
        pass

    if formula_map:
        lines.append("### Model definitions")
        lines.append("| Model | Formula |")
        lines.append("| --- | --- |")
        for mid, formula in formula_map.items():
            lines.append(f"| Model {mid} | `{formula}` |")
        lines.append("")

    _t_analysis = time.monotonic()
    lines.append("## Artefact checks")
    lines.append(f"- model_comparison.csv present: {'YES' if comp is not None else 'NO'}")
    lines.append(f"- model_coefficients.csv present: {'YES' if coefs is not None else 'NO'}")
    lines.append(f"- diagnostics.json present: {'YES' if diags is not None else 'NO'}")
    lines.append(f"- interpretation.txt present: {'YES' if bool((interpretation or '').strip()) else 'NO'}\n")


    # -------------------------
    # Ground truth summary (computed from model_comparison.csv)
    # -------------------------
    if best_models:
        lines.append("## Ground truth summary (auto-generated)")
        lines.append("Computed directly from **model_comparison.csv** (not from the LLM).\n")
        lines.append("| Criterion | Best model | Formula | Value |")
        lines.append("| --- | --- | --- | --- |")
        for crit, rec in best_models.items():
            if isinstance(rec, dict):
                mid = rec.get("model_id")
                val = rec.get("value")
            else:
                mid = getattr(rec, "model_id", None)
                val = getattr(rec, "value", None)
            try:
                val_num = float(val) if val is not None else None
                val_str = f"{val_num:.4g}" if val_num is not None else ""
            except Exception:
                val_str = str(val) if val is not None else ""
            formula_str = f"`{formula_map[mid]}`" if mid in formula_map else ""
            lines.append(f"| {crit.upper()} | Model {mid} | {formula_str} | {val_str} |")
        lines.append("")
    else:
        lines.append("## Ground truth summary (auto-generated)")
        lines.append("(No usable model_comparison.csv metrics were available to determine best models.)\n")

    # -------------------------
    # Major issues section
    # -------------------------

    # Grouped issues so the report is easy to scan in a live demo
    grouped = _interpretation_flags_grouped(interpretation, prob_mode)
    major_cross: list[str] = list(grouped.get("cross") or [])
    major_freq: list[str] = list(grouped.get("frequentist") or [])
    major_bayes: list[str] = list(grouped.get("bayesian") or [])
    major_hybrid: list[str] = list(grouped.get("hybrid") or [])

    major_data: list[str] = []
    major_data.extend(_transformation_mismatch_flags(spec, interpretation))
    major_data.extend(_diagnostics_contradiction_flags(diags, interpretation))
    major_data.extend(_model_selection_flags(interpretation, spec, comp))

    # Optional: S-values (Frequentist p-values only; opt-in)
    if include_s_values and prob_mode == "frequentist":
        major_freq.extend(_s_value_exaggeration_flags(coefs, interpretation))

    # Philosophy compliance checks (required reporting + prohibition violations)
    major_philosophy: list[str] = []
    if philosophy != "unknown":
        major_philosophy.extend(_required_reporting_flags(spec, interpretation))
        major_philosophy.extend(_prohibition_violation_flags(spec, interpretation))

    lines.append("## Major issues detected")

    any_issues = any([major_cross, major_freq, major_bayes, major_hybrid, major_data, major_philosophy])

    if not any_issues:
        lines.append("- No major issues detected by the current rule set (this is not a guarantee).")
        lines.append("")
    else:
        if major_cross:
            lines.append("### Cross-paradigm (language and logic)")
            for msg in major_cross:
                lines.append(f"- **PROBLEM:** {msg}")
            lines.append("")
        if major_freq:
            lines.append("### Frequentist-specific")
            for msg in major_freq:
                lines.append(f"- **PROBLEM:** {msg}")
            lines.append("")
        if major_bayes:
            lines.append("### Bayesian-specific")
            for msg in major_bayes:
                lines.append(f"- **PROBLEM:** {msg}")
            lines.append("")
        if major_hybrid:
            lines.append("### Hybrid / method-mixing")
            for msg in major_hybrid:
                lines.append(f"- **PROBLEM:** {msg}")
            lines.append("")
        if major_data:
            lines.append("### Data contradictions and artefact-based checks")
            for msg in major_data:
                lines.append(f"- **PROBLEM:** {msg}")
            lines.append("")
        if major_philosophy:
            lines.append("### Philosophical framework compliance")
            lines.append(f"*Active framework: **{philosophy}***\n")
            for msg in major_philosophy:
                lines.append(f"- **PROBLEM:** {msg}")
            lines.append("")

    # -------------------------
    # Transformation notes (informational, not errors)
    # -------------------------
    t_notes = _transformation_notes(spec)
    if t_notes:
        lines.append("## Transformation notes")
        lines.append("*Informational advisories — not errors.*\n")
        for note in t_notes:
            lines.append(f"- {note}")
        lines.append("")

    _timings["flag_analysis"] = time.monotonic() - _t_analysis

    # -------------------------
    # Philosophy RAG retrieval (targeted queries against source texts)
    # -------------------------
    _t_philo = time.monotonic()
    if philosophy != "unknown":
        philo_hits = _philosophy_rag_retrieval(
            philosophy, interpretation, index_dir, sources_dir,
        )

        # Persist for UI
        try:
            (run_dir / "retrieval_philosophy.json").write_text(
                json.dumps(
                    [
                        {
                            "score": h["score"],
                            "source": h["source"],
                            "chunk": h["chunk"],
                            "text": h.get("text", ""),
                        }
                        for h in philo_hits
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

        lines.append("## Philosophy RAG retrieval")
        lines.append(
            f"Targeted retrieval for **{philosophy}** framework "
            f"against indexed methodology literature.\n"
        )
        if not philo_hits:
            lines.append(
                "- No philosophy source chunks retrieved. "
                "Ensure philosophical methodology texts are indexed "
                "(e.g. under a `Philosophy/` folder in the sources directory)."
            )
        else:
            for h in philo_hits:
                lines.append(
                    f"- score={h['score']:.3f} source={h['source']} "
                    f"chunk={h['chunk']}"
                )
        lines.append("")

    # -------------------------
    # Claim-by-claim retrieval (evidence linking)
    # -------------------------
    _timings["philosophy_rag"] = time.monotonic() - _t_philo
    _t_claims = time.monotonic()
    claim_list = extract_claims((interpretation or "").strip())
    retrieval_claims: list[dict[str, Any]] = []

    lines.append("## Claim-by-claim evidence (local RAG)")
    if not claim_list:
        lines.append("(No claims could be extracted from interpretation.txt.)\n")
    else:
        lines.append("This section retrieves evidence for each claim separately.\n")
        for i, claim in enumerate(claim_list, start=1):
            title = claim[:80] + ("…" if len(claim) > 80 else "")
            lines.append(f"## Claim {i}: {title}\n")

            q = (brief + "\n" + claim).strip() if brief else claim
            hits = _retrieve_for_query(index_dir, q, top_k=4, allowed_prefixes=allowed_prefixes)

            saved_hits: list[dict[str, Any]] = []
            if sources_dir is not None:
                for h in hits:
                    saved_hits.append(_hydrate_chunk_text(sources_dir, h))
            else:
                saved_hits = hits

            retrieval_claims.append({"claim_id": i, "claim": claim, "query": q, "hits": saved_hits})

            if not hits:
                lines.append("- No matching chunks were retrieved for this claim.\n")
                continue

            lines.append("### Retrieved chunks")
            for h in hits:
                lines.append(f"- score={h['score']:.3f} source={h['source']} chunk={h['chunk']}")
            lines.append("")

    # Persist per-claim retrieval for UI
    try:
        (run_dir / "retrieval_claims.json").write_text(json.dumps(retrieval_claims, indent=2), encoding="utf-8")
    except Exception:
        pass

    # -------------------------
    # Snapshots
    # -------------------------
    _timings["claim_retrieval"] = time.monotonic() - _t_claims
    _timings["n_claims"] = len(claim_list)
    _t_rest = time.monotonic()
    if comp is not None:
        lines.append("## Model comparison snapshot (all rows)\n")
        lines.append(_df_to_markdown(comp) + "\n")

    if coefs is not None:
        lines.append("## Coefficients snapshot (first 20 rows)\n")
        lines.append(_df_to_markdown(coefs.head(20)) + "\n")

    if diags is not None:
        lines.append("## Diagnostics summary (as provided)")
        lines.append("```json")
        lines.append(json.dumps(diags, indent=2)[:20000])
        lines.append("```\n")

    # -------------------------
    # Backward-compatible: global retrieval for whole document
    # -------------------------
    lines.append("## RAG retrieval (top matches, whole document)")
    q_global = (brief + "\n" + (interpretation or "")).strip() or "model interpretation and validation"
    hits_global = _retrieve_for_query(index_dir, q_global, top_k=6, allowed_prefixes=allowed_prefixes)

    retrieval_global: list[dict[str, Any]] = []
    if sources_dir is not None and hits_global:
        retrieval_global = [_hydrate_chunk_text(sources_dir, h) for h in hits_global]
    else:
        retrieval_global = hits_global

    try:
        (run_dir / "retrieval.json").write_text(json.dumps(retrieval_global, indent=2), encoding="utf-8")
    except Exception:
        pass

    if not hits_global:
        lines.append("No index results available (build index in Step 3).\n")
    else:
        for h in hits_global:
            lines.append(f"- score={h['score']:.3f} source={h['source']} chunk={h['chunk']}")
        lines.append("")

    # -------------------------
    # Full interpretation
    # -------------------------
    lines.append("## Full LLM interpretation (as uploaded)\n```")
    lines.append((interpretation or "").strip()[:25000])
    lines.append("```\n")

    # -------------------------
    # Performance diagnostics
    # -------------------------
    _timings["snapshots_and_global_rag"] = time.monotonic() - _t_rest
    _timings["total"] = time.monotonic() - _t0

    lines.append("## Performance diagnostics")
    lines.append("| Phase | Time (s) |")
    lines.append("| --- | ---: |")
    for k, v in _timings.items():
        if k == "n_claims":
            lines.append(f"| Claims extracted | {int(v)} |")
        else:
            lines.append(f"| {k.replace('_', ' ').title()} | {v:.2f} |")
    lines.append("")

    try:
        (run_dir / "timings.json").write_text(
            json.dumps({k: round(v, 3) for k, v in _timings.items()}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    return "\n".join(lines)


