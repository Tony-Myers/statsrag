from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from statsrag.indexing import ingest_sources
from statsrag.profiles import load_profile, merge_profiles
from statsrag.prompts import julius_prompt_from_spec
from statsrag.schema import AnalysisSpec, Transformations, Validation
from statsrag.verify import build_report

DATA_DIR = Path(os.environ.get("VO2RAG_DATA_DIR", "/data"))
SOURCES_DIR = DATA_DIR / "sources"
INDEX_DIR = DATA_DIR / "index"
RUNS_DIR = DATA_DIR / "runs"
PROFILES_DIR = Path("/app/docs/profiles")

for d in [SOURCES_DIR, INDEX_DIR, RUNS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="StatsRAG", layout="wide", page_icon="📊")

st.markdown(
    """
<style>
/* =============================================
   StatsRAG — supplementary styles
   Core theme is in .streamlit/config.toml.
   This block handles only layout and cosmetic
   details that config.toml cannot express.
   ============================================= */

/* --- Page layout --- */
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1200px;
}

/* --- Heading refinements --- */
h1, h2, h3, h4 {
    letter-spacing: -0.01em;
}
h1 { font-weight: 700; }
h2 { font-weight: 600; }
h3 { font-weight: 600; font-size: 1.15rem; }

/* Subtle blue rule below the main heading */
div[data-testid="stMarkdownContainer"] > h2:first-of-type {
    border-bottom: 2px solid #3b82f6;
    padding-bottom: 0.35rem;
    margin-bottom: 0.5rem;
}

/* --- Sidebar navigation --- */
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2 {
    font-size: 1.05rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

/* --- Metric card labels --- */
div[data-testid="stMetric"] label {
    text-transform: uppercase;
    letter-spacing: 0.03em;
    font-size: 0.78rem;
}

/* --- File uploader dashed border --- */
section[data-testid="stFileUploadDropzone"] {
    border-style: dashed;
}

/* --- Captions --- */
div[data-testid="stCaptionContainer"] {
    line-height: 1.5;
}

/* --- Dividers --- */
hr {
    margin: 1.4rem 0;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown("## StatsRAG — local RAG + verification")
st.markdown(
    '<div style="color:#64748b; font-size:0.88rem; margin-top:-0.5em; margin-bottom:1em;">'
    "Tony Myers &middot; Birmingham Newman University</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Navigation")
    step = st.radio(
        "Step",
        [
            "1) Framework",
            "2) Research brief → spec",
            "3) Sources → build index",
            "4) Generate Julius prompt",
            "5) Upload artefacts + interpretation",
            "6) Verification report",
        ],
    )
    st.caption("Docker binds to 127.0.0.1 only (see docker-compose.yml) Tony Myers.")


def load_profiles(prefix: str):
    mapping = {}
    for p in PROFILES_DIR.glob(f"{prefix}_*.json"):
        mapping[p.stem.replace(f"{prefix}_", "")] = p
    return dict(sorted(mapping.items()))


def _read_columns_from_upload(uploaded_file) -> list[str]:
    if uploaded_file is None:
        return []
    # Ensure we start at 0 (Streamlit uploads are file-like objects).
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    name = (uploaded_file.name or "").lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(uploaded_file, nrows=5)
        elif name.endswith(".xlsx"):
            df = pd.read_excel(uploaded_file, nrows=5, engine="openpyxl")
        elif name.endswith(".xls"):
            df = pd.read_excel(uploaded_file, nrows=5, engine="xlrd")
        else:
            return []
    except Exception as e:
        st.error(f"Could not read file to infer columns: {e}")
        return []
    # Reset so the same upload can be read again later (e.g., Save uploads).
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    return [str(c) for c in df.columns.tolist()]


def _build_formula(
    outcome: str,
    rhs_terms: list[str],
    outcome_transform: str = "none",
    random_effects: str = "",
) -> str:
    """Build an R-style formula with the selected outcome transformation.

    outcome_transform: one of "none", "log", "sqrt", "boxcox"
    random_effects: pre-built random-effects string, e.g. "(1|subject)"
                    or "(1 + speed|subject)" — appended to the RHS as-is.
    """
    if not outcome:
        return ""
    _wrappers = {"log": "log", "sqrt": "sqrt", "boxcox": "boxcox"}
    wrap = _wrappers.get(outcome_transform, "")
    lhs = f"{wrap}({outcome})" if wrap else outcome
    rhs = [t for t in rhs_terms if t]
    if random_effects:
        rhs.append(random_effects)
    if not rhs:
        return f"{lhs} ~ 1"
    return f"{lhs} ~ " + " + ".join(rhs)


def _flags_to_str(flags_obj) -> str:
    """Make flags safe for display even if they are dicts (future-proofing)."""
    if not flags_obj:
        return ""
    out = []
    for f in (flags_obj or []):
        if isinstance(f, str):
            out.append(f)
        elif isinstance(f, dict):
            out.append(f.get("message") or f.get("flag") or json.dumps(f, ensure_ascii=False))
        else:
            out.append(str(f))
    return "; ".join(out)


if "framework" not in st.session_state:
    st.session_state.framework = {"philosophy": "realist", "probability": "frequentist"}
if "spec" not in st.session_state:
    st.session_state.spec = None
if "last_report" not in st.session_state:
    st.session_state.last_report = ""


if step.startswith("1"):
    st.subheader("1) Choose framework")
    philos = load_profiles("philosophy")
    probs = load_profiles("prob")
    c1, c2 = st.columns(2)
    with c1:
        philosophy = st.selectbox(
            "Philosophical framework",
            list(philos.keys()),
            index=list(philos.keys()).index(st.session_state.framework["philosophy"]),
        )
    with c2:
        probability = st.selectbox(
            "Probability framework",
            list(probs.keys()),
            index=list(probs.keys()).index(st.session_state.framework["probability"]),
        )
    st.session_state.framework = {"philosophy": philosophy, "probability": probability}
    st.info("Profiles define prohibited interpretations and required reporting items. Edit/add JSON in docs/profiles/.")

elif step.startswith("2"):
    st.subheader("2) Research brief → analysis spec (offline)")
    st.write("This creates a strict `analysis_spec.json`. No LLM is used here.")

    uploaded = st.file_uploader(
        "Upload a dataset to populate variables (CSV / XLSX / XLS)",
        type=["csv", "xlsx", "xls"],
        help="The app lists columns so you can select outcome/predictors without typing.",
    )
    columns = _read_columns_from_upload(uploaded)
    if uploaded is not None and columns:
        st.success(f"Detected {len(columns)} columns.")
        st.caption(", ".join(columns[:30]) + (" ..." if len(columns) > 30 else ""))

    st.info("Changes on this page are not saved until you click **Create spec** at the bottom.")

    # --- Core fields (no form; every change triggers an immediate rerun) ---

    name = st.text_input("Spec name", value="analysis", key="spec_name")
    objective = st.selectbox("Objective", ["prediction", "explanation", "both"], index=0, key="objective")

    if columns:
        outcome = st.selectbox("Outcome column", columns, index=0, key="outcome")
        available_preds = [c for c in columns if c != outcome]
        predictors_sel = st.multiselect(
            "Predictor columns",
            available_preds,
            default=st.session_state.get("predictors_sel", []),
            key="predictors_sel",
            help="Select at least one predictor. These are saved into the analysis spec when you click Create spec.",
        )
        predictors_text = ", ".join(predictors_sel)
    else:
        st.warning("Upload a dataset to select variables. If you must proceed without upload, type column names.")
        outcome = st.text_input("Outcome column name", value="")
        predictors_text = st.text_area("Predictor column names (comma-separated)", value="", key="predictors_text")
        predictors_sel = [p.strip() for p in predictors_text.split(",") if p.strip()]

    project_brief = st.text_area("Project brief (research question, design, constraints)", value="", height=140, key="project_brief")

    # --- Analysis type selector ---

    st.markdown("### Analysis type")
    analysis_type = st.selectbox(
        "What kind of analysis?",
        ["regression", "group_comparison", "correlation"],
        format_func=lambda x: {
            "regression": "Regression / modelling (linear, GLM, mixed, Bayesian)",
            "group_comparison": "Group comparison (t-test, Wilcoxon, Bayesian difference test)",
            "correlation": "Correlation / association (Pearson, Spearman, Kendall)",
        }.get(x, x),
        index=0,
        key="analysis_type",
    )

    prob_fw = st.session_state.framework.get("probability", "frequentist")

    # ================================================================
    #  REGRESSION / MODELLING FLOW  (existing)
    # ================================================================
    if analysis_type == "regression":
        st.markdown("### Model set (deterministic template; user-controlled)")
        st.caption(
            "Select predictor terms for each candidate model below. "
            "The R formula is built automatically and updates as you add or remove terms."
        )

        outcome_kind = st.selectbox(
            "Outcome type",
            ["continuous", "binary", "count", "ordinal", "proportion", "time-to-event"],
            index=0,
            key="outcome_kind",
            help="Determines which response distributions are available below.",
        )

        # --- Response distribution / family ---

        st.markdown("### Response distribution (family)")

        prob_fw = st.session_state.framework.get("probability", "frequentist")

        # Framework-aware distribution options
        _FAMILY_OPTIONS: dict[str, list[tuple[str, str]]] = {
            # (value, label) pairs grouped by outcome type
            "continuous": [
                ("gaussian", "Gaussian (normal) — default for continuous outcomes"),
                ("student", "Student-t — robust to outliers (heavier tails than Gaussian)"),
                ("lognormal", "Log-normal — positive outcomes with right skew"),
                ("Gamma", "Gamma — positive outcomes, variance proportional to mean²"),
                ("Beta", "Beta — bounded outcomes in (0, 1), e.g. percentages, proportions"),
                ("skew_normal", "Skew-normal — allows asymmetric residuals"),
                ("exgaussian", "Ex-Gaussian — reaction time data (Gaussian + exponential tail)"),
            ],
            "binary": [
                ("bernoulli", "Bernoulli (logistic) — binary 0/1 outcomes"),
                ("bernoulli_probit", "Bernoulli (probit link) — binary, normal CDF link"),
            ],
            "count": [
                ("poisson", "Poisson — counts with mean ≈ variance"),
                ("negbinomial", "Negative binomial — overdispersed counts (variance > mean)"),
                ("zero_inflated_poisson", "Zero-inflated Poisson — excess zeros + Poisson counts"),
                ("zero_inflated_negbinomial", "Zero-inflated negative binomial — excess zeros + overdispersion"),
                ("hurdle_poisson", "Hurdle Poisson — separate zero/non-zero process"),
                ("hurdle_negbinomial", "Hurdle negative binomial — hurdle + overdispersion"),
            ],
            "ordinal": [
                ("cumulative", "Cumulative (proportional odds) — ordered categories"),
                ("sratio", "Stopping-ratio — sequential category progression"),
                ("cratio", "Continuation-ratio — category continuation probability"),
                ("acat", "Adjacent-category — pairwise adjacent comparisons"),
            ],
            "proportion": [
                ("Beta", "Beta — proportions/rates bounded in (0, 1)"),
                ("zero_one_inflated_beta", "Zero-one-inflated Beta — proportions with 0s and/or 1s"),
                ("gaussian", "Gaussian — only if logit- or arcsine-transformed first"),
            ],
            "time-to-event": [
                ("weibull", "Weibull — parametric survival model"),
                ("cox", "Cox — semi-parametric proportional hazards"),
            ],
        }

        # Families available via frequentist R packages
        # (package noted in comments for the prompt builder)
        _FREQUENTIST_FAMILIES = {
            "gaussian",         # stats::lm / stats::glm
            "Gamma",            # stats::glm(family=Gamma)
            "bernoulli",        # stats::glm(family=binomial)
            "bernoulli_probit", # stats::glm(family=binomial(link="probit"))
            "poisson",          # stats::glm(family=poisson)
            "negbinomial",      # MASS::glm.nb
            "cumulative",       # MASS::polr / ordinal::clm
            "Beta",             # betareg::betareg
            "cox",              # survival::coxph
        }

        families_for_type = _FAMILY_OPTIONS.get(outcome_kind, _FAMILY_OPTIONS["continuous"])
        if prob_fw != "bayesian":
            families_for_type = [
                (v, l) for v, l in families_for_type if v in _FREQUENTIST_FAMILIES
            ]
            if not families_for_type:
                families_for_type = [("gaussian", "Gaussian (normal) — default")]

        family_values = [v for v, _ in families_for_type]
        family_labels = {v: l for v, l in families_for_type}

        _stored_family = st.session_state.get("response_family", family_values[0])
        if _stored_family not in family_values:
            _stored_family = family_values[0]

        response_family = st.selectbox(
            "Response distribution",
            family_values,
            index=family_values.index(_stored_family),
            format_func=lambda x: family_labels.get(x, x),
            key="response_family",
        )

        # Educational captions
        _FAMILY_HELP = {
            "gaussian": (
                "The **Gaussian** (normal) family assumes residuals are symmetrically "
                "distributed with constant variance. This is the default for "
                "continuous outcomes and underlies `lm()` in R. Check residual "
                "plots for non-normality or heteroscedasticity."
            ),
            "student": (
                "The **Student-t** family adds a degrees-of-freedom parameter (ν) "
                "that controls tail heaviness. When ν is small, the distribution "
                "accommodates outliers that would unduly influence a Gaussian model. "
                "As ν → ∞ it converges to Gaussian. In brms: `family = student()`."
            ),
            "lognormal": (
                "The **log-normal** family models log(Y) ~ Normal. Unlike a "
                "log-transformed Gaussian, brms handles the back-transformation "
                "internally — posterior predictions are on the original scale. "
                "Appropriate when the outcome is strictly positive and right-skewed."
            ),
            "Gamma": (
                "The **Gamma** family is appropriate for strictly positive outcomes "
                "where variance increases with the mean (variance ∝ mean²). Common "
                "for durations, costs, and physiological measures. Uses a log link "
                "by default. In brms: `family = Gamma(link = \"log\")`."
            ),
            "skew_normal": (
                "The **skew-normal** family adds a skewness parameter (α) to the "
                "Gaussian, allowing asymmetric residuals without transformation. "
                "Useful when residuals are moderately skewed but you want to stay "
                "on the original scale. In brms: `family = skew_normal()`."
            ),
            "exgaussian": (
                "The **ex-Gaussian** (exponentially modified Gaussian) is widely "
                "used for reaction-time data. It combines a Gaussian component "
                "(the bulk of the distribution) with an exponential tail capturing "
                "occasional slow responses. In brms: `family = exgaussian()`."
            ),
            "bernoulli": (
                "The **Bernoulli** family with logistic link is the standard choice "
                "for binary (0/1) outcomes. Coefficients are log-odds; exp(b) gives "
                "the odds ratio. In R: `glm(..., family = binomial)` or brms "
                "`family = bernoulli()`."
            ),
            "bernoulli_probit": (
                "The **probit** link uses the normal CDF instead of the logistic. "
                "Coefficients represent change in Φ⁻¹(p). Probit is common in "
                "economics and psychometrics. Results are usually very similar to "
                "logistic regression."
            ),
            "poisson": (
                "The **Poisson** family assumes that the mean equals the variance. "
                "This is often violated in practice (overdispersion). Always check "
                "for overdispersion — if present, use negative binomial instead."
            ),
            "negbinomial": (
                "The **negative binomial** adds a dispersion parameter to the "
                "Poisson, allowing variance > mean (overdispersion). This is the "
                "safer default for count data. In brms: `family = negbinomial()`; "
                "in frequentist R: `MASS::glm.nb()`."
            ),
            "zero_inflated_poisson": (
                "The **zero-inflated Poisson** (ZIP) models excess zeros with a "
                "separate Bernoulli process: with probability π the outcome is "
                "always zero; with probability (1-π) it follows a Poisson. "
                "Appropriate when many observations are 'structural zeros'."
            ),
            "zero_inflated_negbinomial": (
                "The **zero-inflated negative binomial** (ZINB) combines zero "
                "inflation with overdispersion — the non-zero process uses a "
                "negative binomial rather than Poisson. Handles both excess "
                "zeros and overdispersion simultaneously."
            ),
            "hurdle_poisson": (
                "The **hurdle Poisson** models zero vs non-zero as a binary "
                "process, then the positive counts as a truncated Poisson. "
                "Unlike zero-inflation, hurdle models assume ALL zeros come "
                "from the binary process (no 'Poisson zeros')."
            ),
            "hurdle_negbinomial": (
                "The **hurdle negative binomial** uses a truncated negative "
                "binomial for positive counts. Appropriate when zeros have "
                "a distinct mechanism and positive counts are overdispersed."
            ),
            "cumulative": (
                "The **cumulative** (proportional odds) model is the most common "
                "ordinal regression. It models cumulative probabilities: "
                "P(Y ≤ k) = logistic(αₖ - Xβ). The proportional odds assumption "
                "means predictor effects are constant across thresholds."
            ),
            "sratio": (
                "The **stopping-ratio** model treats each category as a sequential "
                "stopping point: given that you haven't stopped yet, what is the "
                "probability of stopping at category k? Useful for developmental "
                "stages or sequential decision processes."
            ),
            "cratio": (
                "The **continuation-ratio** model asks: given that you reached at "
                "least category k, what is the probability of continuing to k+1? "
                "Appropriate for hierarchical progression (e.g. educational levels)."
            ),
            "acat": (
                "The **adjacent-category** model compares each category to its "
                "neighbour: P(Y = k) / P(Y = k+1). Useful when the distinction "
                "between adjacent levels is the natural comparison."
            ),
            "Beta": (
                "The **Beta** family models continuous proportions bounded in "
                "(0, 1). Uses a logit link by default. Appropriate for rates, "
                "percentages, or any outcome naturally between 0 and 1 (exclusive). "
                "In brms: `family = Beta()`."
            ),
            "zero_one_inflated_beta": (
                "The **zero-one-inflated Beta** extends the Beta family to handle "
                "exact 0s and/or exact 1s (which the standard Beta cannot). "
                "It combines a Beta distribution for (0,1) values with point-mass "
                "components at 0 and 1."
            ),
            "weibull": (
                "The **Weibull** is a parametric survival model where the hazard "
                "can increase, decrease, or remain constant over time depending "
                "on the shape parameter. More efficient than Cox when the "
                "parametric form is approximately correct."
            ),
            "cox": (
                "The **Cox** proportional hazards model is semi-parametric — it "
                "estimates hazard ratios without assuming a specific baseline "
                "hazard shape. The workhorse of survival analysis. Note: brms "
                "support for Cox models is limited; consider the `rstanarm` or "
                "`survival` packages."
            ),
        }

        if response_family in _FAMILY_HELP:
            st.caption(_FAMILY_HELP[response_family])

        if prob_fw != "bayesian" and response_family not in _FREQUENTIST_FAMILIES:
            st.warning(
                f"'{response_family}' typically requires Bayesian estimation (brms). "
                f"Consider switching to the Bayesian probability framework in Step 1."
            )

        # --- Transformations ---

        st.markdown("### Transformations")

        # If using a non-Gaussian family that handles the link internally,
        # note that a manual log transform may be redundant
        _FAMILIES_WITH_LOG_LINK = {"Gamma", "lognormal", "poisson", "negbinomial",
                                    "zero_inflated_poisson", "zero_inflated_negbinomial",
                                    "hurdle_poisson", "hurdle_negbinomial"}

        _TRANSFORM_OPTIONS = ["none", "log", "sqrt", "boxcox"]
        _TRANSFORM_LABELS = {
            "none": "None (raw scale)",
            "log": "Log (natural logarithm)",
            "sqrt": "Square-root",
            "boxcox": "Box-Cox (data-driven λ)",
        }
        _stored_transform = st.session_state.get("outcome_transform", "none")
        if _stored_transform not in _TRANSFORM_OPTIONS:
            _stored_transform = "none"
        outcome_transform = st.selectbox(
            "Outcome transformation",
            _TRANSFORM_OPTIONS,
            index=_TRANSFORM_OPTIONS.index(_stored_transform),
            format_func=lambda x: _TRANSFORM_LABELS.get(x, x),
            key="outcome_transform",
            help="Applied to the LHS of every candidate-model formula.",
        )

        # Educational captions per selection
        if outcome_transform == "log":
            st.caption(
                "**Log transform** is appropriate when the outcome is strictly positive "
                "and residual variance scales with the mean (multiplicative errors). "
                "Coefficients describe proportional changes: exp(b) gives the multiplicative "
                "effect per unit change in X. Back-transforming predictions requires a "
                "smearing estimate or half-variance correction (exp(μ + σ²/2)) because "
                "exp(E[log Y]) ≠ E[Y] (Jensen's inequality)."
            )
        elif outcome_transform == "sqrt":
            st.caption(
                "**Square-root transform** is a milder variance-stabiliser than log and "
                "is sometimes used for count-like or variance-proportional-to-mean data. "
                "Coefficients on the sqrt scale do not have a simple multiplicative "
                "interpretation; back-transformation (squaring fitted values) introduces "
                "bias analogous to the log case."
            )
        elif outcome_transform == "boxcox":
            st.caption(
                "**Box-Cox** searches over a family of power transformations (Y^λ) to find "
                "the λ that best stabilises variance and normalises residuals. Log is the "
                "special case λ = 0. Box-Cox does **not** guarantee assumptions are met — "
                "it seeks to improve them — and the chosen λ should be checked empirically. "
                "Back-transformation is non-trivial for λ ≠ 0 or 1 and requires care to "
                "avoid systematic prediction bias."
            )

        # Derive the legacy boolean flag for the Transformations schema
        log_outcome = (outcome_transform == "log")

        if outcome_transform == "log" and response_family in _FAMILIES_WITH_LOG_LINK:
            st.warning(
                f"⚠️ You have selected a **log outcome transformation** and the "
                f"**{response_family}** family, which already uses a log link internally. "
                f"This means you are log-transforming twice. Usually you want one or "
                f"the other — either use `log(Y) ~ ...` with `gaussian`, or use "
                f"`Y ~ ...` with `{response_family}` (which applies the log link itself)."
            )

        log_predictors_sel = st.multiselect(
            "Log-transform predictors (policy reminder)",
            predictors_sel,
            default=[v for v in st.session_state.get("log_predictors_sel", []) if v in predictors_sel],
            key="log_predictors_sel",
        )
        no_transform_sel = st.multiselect(
            "Do NOT transform (policy reminder)",
            predictors_sel,
            default=[v for v in st.session_state.get("no_transform_sel", []) if v in predictors_sel],
            key="no_transform_sel",
        )

        st.markdown("### Mixed-effects structure (optional)")
        st.caption(
            "Mixed-effects (multilevel) models account for non-independence in "
            "clustered or repeated-measures data. Observations within a group "
            "(e.g. same participant, same team) share a group-level deviation "
            "from the overall estimate."
        )

        re_structure = st.selectbox(
            "Random-effects structure",
            ["none", "random_intercept", "random_intercept_slope", "random_intercept_slope_uncorr"],
            format_func=lambda x: {
                "none": "None (no random effects)",
                "random_intercept": "Random intercept — (1 | group)",
                "random_intercept_slope": "Random intercept + slope — (1 + predictor | group)",
                "random_intercept_slope_uncorr": "Uncorrelated random intercept + slope — (1 | group) + (0 + predictor | group)",
            }.get(x, x),
            index=0,
            key="re_structure",
        )

        re_group = ""
        re_slope_vars: list[str] = []

        if re_structure != "none":
            re_group = st.selectbox(
                "Grouping variable (e.g. participant, team, site, school)",
                ["(choose)"] + predictors_sel,
                index=0,
                key="re_group",
                help="The variable that defines the clusters or groups.",
            )
            re_group = "" if re_group == "(choose)" else re_group

        if re_structure in ("random_intercept_slope", "random_intercept_slope_uncorr"):
            # Exclude the grouping variable from slope candidates
            slope_candidates = [p for p in predictors_sel if p != re_group]
            re_slope_vars = st.multiselect(
                "Random slope variable(s)",
                slope_candidates,
                default=[v for v in st.session_state.get("re_slope_vars", []) if v in slope_candidates],
                key="re_slope_vars",
                help="Which predictor effects should vary across groups?",
            )

        # Educational captions per RE selection
        if re_structure == "random_intercept":
            st.caption(
                "**Random intercept** `(1|group)`: each group gets its own baseline "
                "(intercept) that deviates from the population mean. The predictor "
                "effects (slopes) are assumed identical across groups. This is the "
                "most common starting point and handles simple clustering (e.g. "
                "repeated measures on the same participant, students nested in schools). "
                "In R: `lmer(Y ~ X + (1|group))` or brms equivalent."
            )
        elif re_structure == "random_intercept_slope":
            st.caption(
                "**Random intercept + correlated slope** `(1 + X|group)`: both the "
                "baseline and the effect of X are allowed to vary across groups, "
                "and the model estimates the correlation between them. This is the "
                "maximal random-effects structure recommended by Barr et al. (2013) "
                "for confirmatory analyses. It requires enough groups and within-group "
                "observations to estimate the variance-covariance matrix. "
                "In R: `lmer(Y ~ X + (1 + X|group))` or brms equivalent."
            )
        elif re_structure == "random_intercept_slope_uncorr":
            st.caption(
                "**Uncorrelated random intercept + slope** `(1|group) + (0+X|group)`: "
                "the intercept and slope vary across groups but their correlation "
                "is forced to zero. This is computationally simpler and can be "
                "useful when the correlated structure fails to converge or when "
                "you have substantive reason to assume independence. The `||` "
                "shorthand in brms achieves the same thing: `(1 + X || group)`."
            )

        # Build the random-effects formula string
        def _build_re_string() -> str:
            if re_structure == "none" or not re_group:
                return ""
            if re_structure == "random_intercept":
                return f"(1|{re_group})"
            slopes_str = " + ".join(re_slope_vars) if re_slope_vars else ""
            if re_structure == "random_intercept_slope":
                if slopes_str:
                    return f"(1 + {slopes_str}|{re_group})"
                return f"(1|{re_group})"
            if re_structure == "random_intercept_slope_uncorr":
                if slopes_str:
                    return f"(1|{re_group}) + (0 + {slopes_str}|{re_group})"
                return f"(1|{re_group})"
            return ""

        re_formula_str = _build_re_string()

        # --- Candidate model term selection + live formula display ---

        st.markdown("### Candidate models (R formulas; exactly 3 required)")
        st.caption("Select terms for each model. The formula updates live below each selector.")

        grp_for_formula = re_formula_str
        lhs_display = outcome.strip()

        # Filter stored defaults to only items still in the current predictor list
        def _safe_defaults(key: str) -> list[str]:
            stored = st.session_state.get(key, [])
            return [v for v in stored if v in predictors_sel]

        cM1, cM2, cM3 = st.columns(3)
        with cM1:
            rhs1 = st.multiselect("Model 1 terms", predictors_sel, default=_safe_defaults("rhs_1"), key="rhs_1")
            formula_1 = _build_formula(lhs_display, list(rhs1), outcome_transform, random_effects=grp_for_formula)
            if rhs1:
                st.code(formula_1, language=None)
            else:
                st.caption("Select terms above")
        with cM2:
            rhs2 = st.multiselect("Model 2 terms", predictors_sel, default=_safe_defaults("rhs_2"), key="rhs_2")
            formula_2 = _build_formula(lhs_display, list(rhs2), outcome_transform, random_effects=grp_for_formula)
            if rhs2:
                st.code(formula_2, language=None)
            else:
                st.caption("Select terms above")
        with cM3:
            rhs3 = st.multiselect("Model 3 terms", predictors_sel, default=_safe_defaults("rhs_3"), key="rhs_3")
            formula_3 = _build_formula(lhs_display, list(rhs3), outcome_transform, random_effects=grp_for_formula)
            if rhs3:
                st.code(formula_3, language=None)
            else:
                st.caption("Select terms above")

        with st.expander("Manual formula override / additional models", expanded=False):
            st.caption(
                "Edit the formulas below to override the term selectors (e.g. for interaction "
                "terms, polynomials, or splines). Leave blank to use the formula built above."
            )
            m1_override = st.text_input("Model 1 formula override", value="", key="model_1_override")
            m2_override = st.text_input("Model 2 formula override", value="", key="model_2_override")
            m3_override = st.text_input("Model 3 formula override", value="", key="model_3_override")
            extra = st.text_area("Optional Model 4–5 (one per line)", value="", key="model_extra")

            st.markdown("### Optional: model aliases (for interpretation checking)")
            st.caption("If the LLM uses names like 'linear model' or 'FFM-only model', you can map these aliases to a model number so the verifier can check them. One per line: alias = model_id")
            aliases_text = st.text_area("Model aliases", value="", key="model_aliases_text", height=90, placeholder="linear = 1\nffm_only = 2")

        # --- Validation settings ---

        prob_fw = st.session_state.framework.get("probability", "frequentist")
        prob_path = load_profiles("prob")[prob_fw]
        prob_profile = load_profile(prob_path)
        ui = prob_profile.get("ui", {})

        # --- Bayesian aim selector (only shown when probability = bayesian) ---
        bayesian_aim = "estimation"
        if prob_fw == "bayesian":
            st.markdown("### Bayesian analysis aim")
            st.caption(
                "The aim determines how the analysis is structured and what the LLM "
                "is permitted to claim. Choose the primary purpose of this Bayesian analysis."
            )
            bayesian_aim = st.selectbox(
                "Primary aim",
                ["estimation", "predictive_comparison", "hypothesis_testing"],
                format_func=lambda x: {
                    "estimation": "Estimation — posterior summaries and credible intervals",
                    "predictive_comparison": "Predictive comparison — PSIS-LOO / WAIC / ELPD",
                    "hypothesis_testing": "Hypothesis testing — Bayes factors",
                }.get(x, x),
                index=0,
                key="bayesian_aim",
            )
            _aim_notes = {
                "estimation": (
                    "The prompt will request posterior summaries, credible intervals, and "
                    "optionally ROPE analysis. LOO/WAIC may still be used for model checking "
                    "but will not be framed as the primary comparison tool."
                ),
                "predictive_comparison": (
                    "The prompt will centre on PSIS-LOO or WAIC for predictive model comparison. "
                    "Pareto-k diagnostics are required. AIC/BIC are excluded."
                ),
                "hypothesis_testing": (
                    "The prompt will request Bayes factors with explicit prior specification "
                    "and marginal likelihood caveats. The LLM must state prior model odds "
                    "and interpret BF as evidence, not probability."
                ),
            }
            st.info(_aim_notes.get(bayesian_aim, ""))

        # --- Prior specification (only shown when probability = bayesian) ---
        prior_spec: dict = {"tier": "weakly_informative"}
        if prob_fw == "bayesian":
            st.markdown("### Prior specification")
            st.caption(
                "Bayesian analysis requires prior distributions on parameters. "
                "If you are unsure, start with weakly informative defaults — "
                "these let the data dominate while keeping estimates stable."
            )

            prior_tier = st.selectbox(
                "Prior strategy",
                ["weakly_informative", "guided", "formal"],
                format_func=lambda x: {
                    "weakly_informative": "Weakly informative defaults (recommended start)",
                    "guided": "Guided — I have domain knowledge about expected effects",
                    "formal": "Formal — I will specify priors in brms/Stan syntax",
                }.get(x, x),
                index=0,
                key="prior_tier",
            )

            prior_spec = {"tier": prior_tier}

            if prior_tier == "weakly_informative":
                st.info(
                    "The prompt will instruct the LLM to use brms default weakly "
                    "informative priors (typically student-t for the intercept, "
                    "flat or weakly regularising for slopes) and to report what "
                    "it used."
                )

            elif prior_tier == "guided":
                with st.expander("Domain knowledge elicitation", expanded=True):
                    st.markdown(
                        "Answer these questions using your **domain expertise**. "
                        "You do not need to be precise — the goal is to give the "
                        "analysis sensible starting beliefs rather than relying "
                        "entirely on defaults."
                    )

                    # --- Outcome range ---
                    st.markdown("**Outcome expectations**")
                    _scale_note = ""
                    if outcome_transform == "log":
                        _scale_note = " (on the **log scale**, since you chose a log transformation)"
                    elif outcome_transform == "sqrt":
                        _scale_note = " (on the **square-root scale**, since you chose a sqrt transformation)"

                    gc1, gc2 = st.columns(2)
                    with gc1:
                        outcome_typical = st.number_input(
                            f"Typical value of the outcome{_scale_note}",
                            value=0.0,
                            format="%.3f",
                            key="prior_outcome_typical",
                            help=(
                                "What is a typical (central) value you would "
                                "expect for the outcome? E.g. for log(VO2max) "
                                "in adults, ~1.2 (i.e. ~3.3 L/min)."
                            ),
                        )
                    with gc2:
                        outcome_spread = st.number_input(
                            "Plausible spread (± from typical)",
                            value=1.0,
                            min_value=0.01,
                            format="%.3f",
                            key="prior_outcome_spread",
                            help=(
                                "How far from the typical value could the "
                                "outcome plausibly range? This sets the width of "
                                "the intercept prior. E.g. ±0.5 on the log "
                                "scale covers roughly a 60% range around the "
                                "typical value."
                            ),
                        )

                    prior_spec["outcome_typical"] = outcome_typical
                    prior_spec["outcome_spread"] = outcome_spread

                    # --- Per-predictor beliefs ---
                    st.markdown("**Expected predictor effects**")
                    st.caption(
                        "For each predictor, indicate what you expect based on "
                        "prior literature or domain knowledge. 'Uncertain' is a "
                        "perfectly valid answer — it produces a symmetric prior "
                        "centred at zero."
                    )

                    _directions = ["uncertain", "positive", "negative"]
                    _magnitudes = ["unknown", "negligible", "small", "moderate", "large"]
                    _magnitude_help = {
                        "unknown": "No prior expectation about size",
                        "negligible": "Effect near zero; included for completeness",
                        "small": "Detectable but minor effect",
                        "moderate": "Meaningful practical effect",
                        "large": "Strong, dominant effect",
                    }

                    predictor_beliefs: dict = {}
                    for pred in predictors_sel:
                        pc1, pc2, pc3 = st.columns([2, 2, 3])
                        with pc1:
                            st.markdown(f"**`{pred}`**")
                        with pc2:
                            _dir = st.selectbox(
                                "Direction",
                                _directions,
                                index=0,
                                key=f"prior_dir_{pred}",
                                label_visibility="collapsed",
                            )
                        with pc3:
                            _mag = st.selectbox(
                                "Magnitude",
                                _magnitudes,
                                index=0,
                                key=f"prior_mag_{pred}",
                                label_visibility="collapsed",
                                help="; ".join(
                                    f"{k}: {v}"
                                    for k, v in _magnitude_help.items()
                                ),
                            )
                        predictor_beliefs[pred] = {
                            "direction": _dir,
                            "magnitude": _mag,
                        }

                    prior_spec["predictor_beliefs"] = predictor_beliefs

                    # --- Optional free-text domain notes ---
                    domain_notes = st.text_area(
                        "Additional domain context (optional)",
                        value="",
                        key="prior_domain_notes",
                        height=80,
                        placeholder=(
                            "E.g. 'FFM is the strongest known predictor of "
                            "VO2max in healthy adults. Sex differences are "
                            "well-established. Age effects are modest below 60.'"
                        ),
                    )
                    if domain_notes.strip():
                        prior_spec["domain_notes"] = domain_notes.strip()

            elif prior_tier == "formal":
                st.info(
                    "Enter priors using brms syntax (e.g. "
                    "`set_prior('normal(0, 1)', class = 'b')`) or plain "
                    "descriptions. These will be passed verbatim to the LLM. "
                    "Any parameters not covered will use brms defaults."
                )
                formal_text = st.text_area(
                    "Prior specification (brms/Stan syntax or plain language)",
                    value="",
                    key="prior_formal_text",
                    height=140,
                    placeholder=(
                        "# Examples:\n"
                        "set_prior('normal(0, 1)', class = 'b')\n"
                        "set_prior('student_t(3, 1.2, 0.5)', class = 'Intercept')\n"
                        "set_prior('cauchy(0, 1)', class = 'sd')"
                    ),
                )
                prior_spec["formal_text"] = formal_text.strip()

            # --- Model priors (hypothesis testing only) ---
            if bayesian_aim == "hypothesis_testing":
                st.markdown("**Model prior probabilities**")
                st.caption(
                    "Bayes factors update prior model odds to posterior model "
                    "odds. The default is equal prior probability across all "
                    "candidate models (1/K each). If you have reasons to favour "
                    "one model a priori, you can adjust these."
                )
                model_prior_strategy = st.radio(
                    "Model priors",
                    ["equal", "custom"],
                    format_func=lambda x: {
                        "equal": "Equal prior probability (1/K each)",
                        "custom": "Custom prior odds",
                    }.get(x, x),
                    index=0,
                    key="model_prior_strategy",
                    horizontal=True,
                )
                if model_prior_strategy == "custom":
                    model_prior_text = st.text_area(
                        "Prior odds (one per line: Model N = weight)",
                        value="",
                        key="model_prior_text",
                        height=80,
                        placeholder="Model 1 = 2\nModel 2 = 1\nModel 3 = 1",
                    )
                    prior_spec["model_priors"] = {
                        "strategy": "custom",
                        "text": model_prior_text.strip(),
                    }
                else:
                    prior_spec["model_priors"] = {"strategy": "equal"}

        method_options = ui.get("validation_methods", ["kfold_cv", "bootstrap", "none"])
        metric_options = ui.get("metrics", ["rmse_log", "rmse_raw", "mae", "r2"])
        ic_options = ui.get("information_criteria", ["AIC", "BIC", "none"])

        st.markdown("### Validation")
        if prob_fw == "bayesian":
            if bayesian_aim == "hypothesis_testing":
                # BF-based: no IC-driven comparison; validation is secondary
                default_method = "none" if "none" in method_options else method_options[0]
                default_metric = "rmse_log" if "rmse_log" in metric_options else metric_options[0]
                default_ic = "none" if "none" in ic_options else ic_options[0]
            else:
                # estimation or predictive_comparison: PSIS-LOO / ELPD
                default_method = "psis_loo" if "psis_loo" in method_options else method_options[0]
                default_metric = "elpd_loo" if "elpd_loo" in metric_options else metric_options[0]
                default_ic = "LOO" if "LOO" in ic_options else ic_options[0]
        elif prob_fw == "hybrid":
            default_method = "psis_loo" if "psis_loo" in method_options else ("kfold_cv" if "kfold_cv" in method_options else method_options[0])
            default_metric = "elpd_loo" if "elpd_loo" in metric_options else metric_options[0]
            default_ic = "LOO" if "LOO" in ic_options else ic_options[0]
        else:
            default_method = "kfold_cv" if "kfold_cv" in method_options else method_options[0]
            default_metric = "rmse_log" if "rmse_log" in metric_options else metric_options[0]
            default_ic = "AIC" if "AIC" in ic_options else ic_options[0]

        method = st.selectbox(
            "Validation method",
            method_options,
            index=method_options.index(default_method) if default_method in method_options else 0,
            key="val_method",
        )
        k = st.number_input("k (if kfold)", value=10, min_value=2, key="val_k")
        seed = st.number_input("Random seed", value=20260203, min_value=1, key="val_seed")
        metric = st.selectbox(
            "Metric",
            metric_options,
            index=metric_options.index(default_metric) if default_metric in metric_options else 0,
            key="val_metric",
        )
        ic = st.selectbox(
            "Information criterion",
            ic_options,
            index=ic_options.index(default_ic) if default_ic in ic_options else 0,
            key="val_ic",
        )

        # --- Create spec button ---

        st.divider()
        if st.button("Create spec", type="primary"):
            philos_path = load_profiles("philosophy")[st.session_state.framework["philosophy"]]
            prob_path_spec = load_profiles("prob")[st.session_state.framework["probability"]]
            ph = load_profile(philos_path)
            pr = load_profile(prob_path_spec)
            prohibitions, required_reporting = merge_profiles(ph, pr)

            pred_list = list(predictors_sel) if columns else [p.strip() for p in predictors_text.split(",") if p.strip()]

            if len(pred_list) == 0:
                st.error("No predictors selected. Add predictors above and click Create spec again.")
                st.stop()

            if re_structure != "none" and not re_group:
                st.error("Random effects structure is selected but no grouping variable is chosen.")
                st.stop()

            if re_structure in ("random_intercept_slope", "random_intercept_slope_uncorr") and not re_slope_vars:
                st.error("Random slope structure is selected but no slope variable(s) are chosen.")
                st.stop()

            # Use override formulas if provided; otherwise use the live-built formulas
            final_m1 = m1_override.strip() if m1_override.strip() else formula_1
            final_m2 = m2_override.strip() if m2_override.strip() else formula_2
            final_m3 = m3_override.strip() if m3_override.strip() else formula_3

            cand = [final_m1, final_m2, final_m3]
            if extra.strip():
                cand.extend([line.strip() for line in extra.splitlines() if line.strip()])

            if any(not c.strip() for c in cand[:3]):
                st.error("Models 1–3 must each have at least one predictor term selected (or a manual formula override).")
                st.stop()

            # Parse optional model aliases (alias = model_id), stored in spec.notes for verification.
            aliases_raw = st.session_state.get("model_aliases_text", "") or ""
            model_aliases: dict[str, int] = {}
            for line in aliases_raw.splitlines():
                if not line.strip() or line.strip().startswith('#'):
                    continue
                if '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip()
                if not k or not v:
                    continue
                try:
                    model_aliases[k] = int(v)
                except Exception:
                    continue

            spec_obj = AnalysisSpec(
                name=name,
                objective=objective,
                outcome=outcome.strip(),
                predictors=pred_list,
                candidate_models=cand,
                transformations=Transformations(
                    log_outcome=log_outcome,
                    log_predictors=list(log_predictors_sel),
                    no_transform=list(no_transform_sel),
                ),
                validation=Validation(method=method, k=int(k) if method == "kfold_cv" else None, seed=int(seed), metric=metric),
                information_criterion=ic,
                prohibitions=prohibitions,
                required_reporting=required_reporting,
                notes={
                    "framework": {
                        **st.session_state.framework,
                        "bayesian_aim": bayesian_aim if prob_fw == "bayesian" else "",
                    },
                    "project_brief": project_brief.strip(),
                    "model_aliases": model_aliases,
                    "modeling": {
                        "outcome_type": outcome_kind,
                        "outcome_transform": outcome_transform,
                        "response_family": response_family,
                        "random_effects": {
                            "structure": re_structure,
                            "grouping_var": re_group if re_structure != "none" else "",
                            "slope_vars": re_slope_vars if re_structure in ("random_intercept_slope", "random_intercept_slope_uncorr") else [],
                            "formula_string": re_formula_str,
                        },
                    },
                    "priors": prior_spec if prob_fw == "bayesian" else {},
                },
            )

            st.session_state.spec = spec_obj
            st.session_state.spec_created_at = time.time()
            st.success("Spec created and validated.")
            st.caption(f"Saved predictors: {', '.join(spec_obj.predictors)}")
            st.code(spec_obj.model_dump_json(indent=2), language="json")
            st.download_button(
                "Download analysis_spec.json",
                spec_obj.model_dump_json(indent=2).encode("utf-8"),
                file_name="analysis_spec.json",
                mime="application/json",
            )

    # ================================================================
    #  GROUP COMPARISON FLOW
    # ================================================================
    elif analysis_type == "group_comparison":
        st.markdown("### Group comparison")
        st.caption(
            "For comparing two groups (independent or paired/dependent). "
            "This covers independent-samples t-tests, paired t-tests, "
            "Wilcoxon/Mann-Whitney tests, and their Bayesian equivalents."
        )

        design = st.selectbox(
            "Design",
            ["independent", "paired"],
            format_func=lambda x: {
                "independent": "Independent groups (between-subjects)",
                "paired": "Paired / dependent (within-subjects, pre–post)",
            }.get(x, x),
            index=0,
            key="comparison_design",
        )

        if design == "independent":
            st.caption(
                "**Independent groups** — two separate groups of participants are compared "
                "(e.g. treatment vs control, male vs female). Observations in one group "
                "are unrelated to observations in the other."
            )
        else:
            st.caption(
                "**Paired / dependent** — the same participants are measured under two "
                "conditions (e.g. pre vs post, left vs right). Each observation in one "
                "condition has a natural partner in the other."
            )

        if design == "independent":
            if columns:
                grouping_var = st.selectbox(
                    "Grouping variable (the two-level factor)",
                    [c for c in columns if c != outcome],
                    key="comp_grouping_var",
                )
            else:
                grouping_var = st.text_input(
                    "Grouping variable name (the two-level factor)",
                    key="comp_grouping_var",
                )
        else:
            st.info(
                "For paired designs, the app will generate `outcome ~ condition + (1|subject)` "
                "or use R's `t.test(..., paired=TRUE)`. Specify which variable indicates the "
                "pairing below."
            )
            if columns:
                grouping_var = st.selectbox(
                    "Condition / time variable (e.g. 'time', 'condition')",
                    [c for c in columns if c != outcome],
                    key="comp_condition_var",
                )
                pairing_var = st.selectbox(
                    "Pairing / subject ID variable",
                    [c for c in columns if c != outcome and c != grouping_var],
                    key="comp_pairing_var",
                )
            else:
                grouping_var = st.text_input("Condition / time variable", key="comp_condition_var")
                pairing_var = st.text_input("Pairing / subject ID variable", key="comp_pairing_var")

        # --- Non-parametric option ---
        parametric = st.selectbox(
            "Test type",
            ["parametric", "non_parametric"],
            format_func=lambda x: {
                "parametric": "Parametric (t-test / Welch's t-test)",
                "non_parametric": "Non-parametric (Wilcoxon / Mann-Whitney U)",
            }.get(x, x),
            index=0,
            key="comp_parametric",
        )

        if parametric == "parametric":
            st.caption(
                "**Parametric tests** assume approximately normal distributions "
                "(or invoke the CLT for larger samples). Welch's t-test is the default "
                "for independent groups as it does not assume equal variances."
            )
        else:
            st.caption(
                "**Non-parametric tests** make no distributional assumptions. "
                "Mann-Whitney U (independent) or Wilcoxon signed-rank (paired) "
                "test the location shift. Effect sizes use rank-biserial correlation."
            )

        # --- Effect size ---
        if parametric == "parametric":
            effect_size = st.selectbox(
                "Effect size measure",
                ["cohens_d", "hedges_g", "glasss_delta"],
                format_func=lambda x: {
                    "cohens_d": "Cohen's d (pooled SD, most common)",
                    "hedges_g": "Hedges' g (bias-corrected d, better for small samples)",
                    "glasss_delta": "Glass's Δ (uses control-group SD only)",
                }.get(x, x),
                index=0,
                key="comp_effect_size",
            )
        else:
            effect_size = st.selectbox(
                "Effect size measure",
                ["rank_biserial", "cohens_d"],
                format_func=lambda x: {
                    "rank_biserial": "Rank-biserial correlation (native to rank tests)",
                    "cohens_d": "Cohen's d (for reference, despite non-parametric test)",
                }.get(x, x),
                index=0,
                key="comp_effect_size_np",
            )

        st.caption(
            "**Effect size interpretation (Cohen, 1988):** |d| ≈ 0.2 small, "
            "≈ 0.5 medium, ≈ 0.8 large. These thresholds are conventional — "
            "practical significance depends on the domain. Always report the "
            "confidence interval around the effect size."
        )

        # --- Bayesian options ---
        if prob_fw == "bayesian":
            st.markdown("### Bayesian difference test options")
            bayes_test_method = st.selectbox(
                "Bayesian method",
                ["bayes_factor", "rope_estimation", "brms_model"],
                format_func=lambda x: {
                    "bayes_factor": "Bayes factor (BayesFactor::ttestBF) — evidence for/against null",
                    "rope_estimation": "ROPE estimation — posterior probability of practical equivalence",
                    "brms_model": "brms model — full posterior for the group difference",
                }.get(x, x),
                index=0,
                key="comp_bayes_method",
            )
            if bayes_test_method == "bayes_factor":
                st.caption(
                    "**BayesFactor::ttestBF** uses a default Cauchy prior on the "
                    "standardised effect size (r = √2/2 ≈ 0.707). The Bayes factor "
                    "quantifies evidence for H₁ (groups differ) vs H₀ (no difference). "
                    "BF₁₀ > 3 is moderate evidence; > 10 is strong (Jeffreys, 1961)."
                )
            elif bayes_test_method == "rope_estimation":
                rope_width = st.number_input(
                    "ROPE half-width (in effect-size units, e.g. 0.1)",
                    min_value=0.01, max_value=1.0, value=0.1, step=0.05,
                    key="comp_rope_width",
                )
                st.caption(
                    "**ROPE** (Region of Practical Equivalence) defines a range "
                    "around zero within which the effect is considered negligible. "
                    "If > 95% of the posterior falls inside the ROPE, the effect "
                    "is practically equivalent to zero (Kruschke, 2018)."
                )
        else:
            bayes_test_method = ""

        # --- Direction ---
        direction = st.selectbox(
            "Test direction",
            ["two_sided", "greater", "less"],
            format_func=lambda x: {
                "two_sided": "Two-sided (non-directional)",
                "greater": "One-sided: group 1 > group 2",
                "less": "One-sided: group 1 < group 2",
            }.get(x, x),
            index=0,
            key="comp_direction",
        )

        # --- Create spec button (group comparison) ---
        st.divider()
        if st.button("Create spec", type="primary", key="create_spec_gc"):
            philos_path = load_profiles("philosophy")[st.session_state.framework["philosophy"]]
            prob_path_spec = load_profiles("prob")[st.session_state.framework["probability"]]
            ph = load_profile(philos_path)
            pr = load_profile(prob_path_spec)
            prohibitions, required_reporting = merge_profiles(ph, pr)

            if not outcome.strip():
                st.error("No outcome variable specified.")
                st.stop()
            if not grouping_var:
                st.error("No grouping variable specified.")
                st.stop()

            # Build the formula
            if design == "independent":
                formula = f"{outcome} ~ {grouping_var}"
                pred_list = [grouping_var]
            else:
                formula = f"{outcome} ~ {grouping_var} + (1|{pairing_var})"
                pred_list = [grouping_var, pairing_var]

            # Build R code hint for the prompt
            if parametric == "parametric":
                if design == "independent":
                    r_code = f't.test({outcome} ~ {grouping_var}, data = df, var.equal = FALSE)'
                else:
                    r_code = f't.test({outcome} ~ {grouping_var}, data = df, paired = TRUE)'
            else:
                if design == "independent":
                    r_code = f'wilcox.test({outcome} ~ {grouping_var}, data = df)'
                else:
                    r_code = f'wilcox.test({outcome} ~ {grouping_var}, data = df, paired = TRUE)'

            comparison_notes = {
                "design": design,
                "parametric": parametric == "parametric",
                "test_direction": direction,
                "effect_size": effect_size,
                "r_code_hint": r_code,
            }
            if prob_fw == "bayesian":
                comparison_notes["bayes_method"] = bayes_test_method
                if bayes_test_method == "rope_estimation":
                    comparison_notes["rope_width"] = rope_width
            if design == "paired":
                comparison_notes["pairing_var"] = pairing_var

            spec_obj = AnalysisSpec(
                name=name,
                objective="explanation",
                outcome=outcome.strip(),
                predictors=pred_list,
                candidate_models=[formula],
                transformations=Transformations(),
                validation=Validation(method="bootstrap", k=None, seed=20260203, metric="cohens_d"),
                information_criterion="none",
                prohibitions=prohibitions,
                required_reporting=required_reporting,
                notes={
                    "framework": {
                        **st.session_state.framework,
                        "bayesian_aim": "hypothesis_testing" if prob_fw == "bayesian" else "",
                    },
                    "project_brief": project_brief.strip(),
                    "analysis_type": "group_comparison",
                    "comparison": comparison_notes,
                    "modeling": {
                        "outcome_type": "continuous",
                        "outcome_transform": "none",
                        "response_family": "gaussian",
                    },
                },
            )

            st.session_state.spec = spec_obj
            st.session_state.spec_created_at = time.time()
            st.success("Group comparison spec created.")
            st.code(spec_obj.model_dump_json(indent=2), language="json")
            st.download_button(
                "Download analysis_spec.json",
                spec_obj.model_dump_json(indent=2).encode("utf-8"),
                file_name="analysis_spec.json",
                mime="application/json",
            )

    # ================================================================
    #  CORRELATION / ASSOCIATION FLOW
    # ================================================================
    elif analysis_type == "correlation":
        st.markdown("### Correlation / association")
        st.caption(
            "For measuring the strength and direction of association "
            "between two (or more) continuous variables."
        )

        # --- Variable selection ---
        if columns:
            avail_vars = [c for c in columns if c != outcome]
            corr_vars = st.multiselect(
                "Variables to correlate with the outcome",
                avail_vars,
                default=[v for v in st.session_state.get("corr_vars", []) if v in avail_vars],
                key="corr_vars",
                help="Select one or more variables. Each will be correlated with the outcome.",
            )
        else:
            corr_vars_text = st.text_area(
                "Variables to correlate with the outcome (comma-separated)",
                key="corr_vars_text",
            )
            corr_vars = [v.strip() for v in corr_vars_text.split(",") if v.strip()]

        # --- Method ---
        corr_method = st.selectbox(
            "Correlation method",
            ["pearson", "spearman", "kendall"],
            format_func=lambda x: {
                "pearson": "Pearson r — linear association (assumes bivariate normality for inference)",
                "spearman": "Spearman ρ — monotonic association (rank-based, robust to outliers)",
                "kendall": "Kendall τ — monotonic association (more robust than Spearman, better for small N)",
            }.get(x, x),
            index=0,
            key="corr_method",
        )

        if corr_method == "pearson":
            st.caption(
                "**Pearson r** measures the strength of the linear relationship. "
                "Values range from −1 (perfect negative) to +1 (perfect positive). "
                "Inference (p-values, CIs) assumes bivariate normality, but the "
                "estimator itself is valid for any distribution. Sensitive to outliers."
            )
        elif corr_method == "spearman":
            st.caption(
                "**Spearman ρ** is the Pearson r computed on ranks. It captures "
                "any monotonic relationship (not just linear). More robust to "
                "outliers and non-normality. Appropriate when variables are "
                "ordinal or heavily skewed."
            )
        else:
            st.caption(
                "**Kendall τ** counts concordant vs discordant pairs. It is more "
                "robust than Spearman for small samples and handles ties well. "
                "Values tend to be smaller in magnitude than Spearman ρ for "
                "the same data — this is expected, not a sign of weaker association."
            )

        # --- Effect size conventions ---
        st.caption(
            "**Effect size interpretation (Cohen, 1988):** "
            "|r| ≈ 0.1 small, ≈ 0.3 medium, ≈ 0.5 large. "
            "Always report the confidence interval. For Pearson r, Fisher's z "
            "transformation gives a CI with good coverage."
        )

        # --- Bayesian options ---
        if prob_fw == "bayesian":
            st.markdown("### Bayesian correlation options")
            bayes_corr_method = st.selectbox(
                "Bayesian method",
                ["bayes_factor", "posterior_estimation"],
                format_func=lambda x: {
                    "bayes_factor": "Bayes factor (BayesFactor::correlationBF) — evidence for/against ρ = 0",
                    "posterior_estimation": "Posterior estimation — full posterior for ρ with credible interval",
                }.get(x, x),
                index=0,
                key="corr_bayes_method",
            )
            if bayes_corr_method == "bayes_factor":
                st.caption(
                    "**BayesFactor::correlationBF** uses a stretched-beta prior on ρ. "
                    "The Bayes factor quantifies evidence for a non-zero correlation "
                    "versus the null hypothesis ρ = 0."
                )
        else:
            bayes_corr_method = ""

        # --- Partial correlation option ---
        partial = st.checkbox("Partial correlation (control for covariates)", value=False, key="corr_partial")
        partial_vars: list[str] = []
        if partial:
            if columns:
                partial_candidates = [c for c in columns if c != outcome and c not in corr_vars]
                partial_vars = st.multiselect(
                    "Control variables",
                    partial_candidates,
                    key="corr_partial_vars",
                )
            else:
                partial_vars_text = st.text_input("Control variables (comma-separated)", key="corr_partial_vars_text")
                partial_vars = [v.strip() for v in partial_vars_text.split(",") if v.strip()]
            st.caption(
                "**Partial correlation** measures the association between two variables "
                "after removing the linear effect of control variables from both. "
                "In R: `ppcor::pcor.test()` or via regression residuals."
            )

        # --- Create spec button (correlation) ---
        st.divider()
        if st.button("Create spec", type="primary", key="create_spec_corr"):
            philos_path = load_profiles("philosophy")[st.session_state.framework["philosophy"]]
            prob_path_spec = load_profiles("prob")[st.session_state.framework["probability"]]
            ph = load_profile(philos_path)
            pr = load_profile(prob_path_spec)
            prohibitions, required_reporting = merge_profiles(ph, pr)

            if not outcome.strip():
                st.error("No outcome variable specified.")
                st.stop()
            if not corr_vars:
                st.error("Select at least one variable to correlate with the outcome.")
                st.stop()

            # Build formulas — one per correlation pair
            formulas = []
            for v in corr_vars:
                if partial and partial_vars:
                    ctrl = " + ".join(partial_vars)
                    formulas.append(f"cor({outcome}, {v} | {ctrl})")
                else:
                    formulas.append(f"cor({outcome}, {v})")

            # Build R code hints
            if corr_method == "pearson":
                r_code = f'cor.test(df${outcome}, df$VAR, method = "pearson")'
            elif corr_method == "spearman":
                r_code = f'cor.test(df${outcome}, df$VAR, method = "spearman")'
            else:
                r_code = f'cor.test(df${outcome}, df$VAR, method = "kendall")'

            corr_notes = {
                "method": corr_method,
                "variables": corr_vars,
                "partial": partial,
                "partial_vars": partial_vars if partial else [],
                "r_code_hint": r_code,
            }
            if prob_fw == "bayesian":
                corr_notes["bayes_method"] = bayes_corr_method

            spec_obj = AnalysisSpec(
                name=name,
                objective="explanation",
                outcome=outcome.strip(),
                predictors=corr_vars + (partial_vars if partial else []),
                candidate_models=formulas,
                transformations=Transformations(),
                validation=Validation(method="none", k=None, seed=20260203, metric="r"),
                information_criterion="none",
                prohibitions=prohibitions,
                required_reporting=required_reporting,
                notes={
                    "framework": {
                        **st.session_state.framework,
                        "bayesian_aim": "estimation" if prob_fw == "bayesian" else "",
                    },
                    "project_brief": project_brief.strip(),
                    "analysis_type": "correlation",
                    "correlation": corr_notes,
                    "modeling": {
                        "outcome_type": "continuous",
                        "outcome_transform": "none",
                        "response_family": "gaussian",
                    },
                },
            )

            st.session_state.spec = spec_obj
            st.session_state.spec_created_at = time.time()
            st.success("Correlation spec created.")
            st.code(spec_obj.model_dump_json(indent=2), language="json")
            st.download_button(
                "Download analysis_spec.json",
                spec_obj.model_dump_json(indent=2).encode("utf-8"),
                file_name="analysis_spec.json",
                mime="application/json",
            )

elif step.startswith("3"):
    st.subheader("3) Sources → build/refresh index")
    st.write(f"Put your sources into: `{SOURCES_DIR}` (mounted from `./data/sources`).")
    st.write(f"Index output: `{INDEX_DIR}` (mounted from `./data/index`).")

    # --- Index status ---
    _manifest_path = INDEX_DIR / "manifest.json"
    _index_path = INDEX_DIR / "tfidf_index.joblib"
    if _index_path.exists() and _manifest_path.exists():
        try:
            _manifest = json.loads(_manifest_path.read_text(encoding="utf-8"))
            _n_chunks = _manifest.get("n_chunks", "?")
            import datetime as _dt
            _mtime = _dt.datetime.fromtimestamp(_index_path.stat().st_mtime)
            st.success(
                f"Existing index found: {_n_chunks} chunks, "
                f"last built {_mtime:%Y-%m-%d %H:%M}. "
                f"You only need to rebuild if you have changed the source documents."
            )
        except Exception:
            st.success("Existing index found. You only need to rebuild if source documents have changed.")
    else:
        st.warning("No index found. Build one below before running verification.")

    _SKIP_NAMES = {".DS_Store", ".gitkeep"}

    top_folders = sorted([
        p.name for p in SOURCES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ])
    top_files = sorted([
        p.name for p in SOURCES_DIR.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.name not in _SKIP_NAMES
    ])

    with st.expander("Optional: select which sources are indexed", expanded=False):
        sel_folders = st.multiselect(
            "Include folders",
            options=top_folders,
            default=[x for x in st.session_state.get("index_include_folders", top_folders) if x in top_folders],
            key="index_include_folders",
        )
        sel_files = st.multiselect(
            "Include individual files in the root of sources",
            options=top_files,
            default=[x for x in st.session_state.get("index_include_files", top_files) if x in top_files],
            key="index_include_files",
        )

    def _resolve_include_paths():
        if set(sel_folders) == set(top_folders) and set(sel_files) == set(top_files):
            return None
        include = []
        for fn in sel_folders:
            include.append(SOURCES_DIR / fn)
        for f in sel_files:
            include.append(SOURCES_DIR / f)
        return include

    if st.button("Build / rebuild index"):
        include_paths = _resolve_include_paths()

        # Pre-flight check: warn if pypdf is missing and PDFs are present
        from statsrag.indexing import PYPDF_AVAILABLE
        _pdf_files = [p for p in SOURCES_DIR.rglob("*.pdf") if p.is_file()]
        if _pdf_files and not PYPDF_AVAILABLE:
            st.error(
                f"⚠️ **pypdf is not installed** but {len(_pdf_files)} PDF files "
                f"were found in sources. PDFs will be skipped entirely.\n\n"
                f"Fix: add `pypdf` to your Docker image requirements "
                f"(e.g. `pip install pypdf`) and rebuild."
            )

        with st.spinner("Indexing sources..."):
            start = time.time()
            n = ingest_sources(SOURCES_DIR, INDEX_DIR, include_paths=include_paths)
            elapsed = time.time() - start
            sel = {"include_folders": sel_folders, "include_files": sel_files}
            try:
                (INDEX_DIR / "selection.json").write_text(json.dumps(sel, indent=2), encoding="utf-8")
            except Exception:
                pass
            st.success(f"Indexed **{n} chunks** in {elapsed:.1f}s.")

            # Show diagnostics from manifest
            try:
                _m = json.loads((INDEX_DIR / "manifest.json").read_text(encoding="utf-8"))
                _d = _m.get("diagnostics", {})
                if _d:
                    diag_parts = []
                    if _d.get("processed", 0) > 0:
                        diag_parts.append(f"✅ {_d['processed']} files produced text")
                    if _d.get("pdf_count", 0) > 0:
                        diag_parts.append(f"📄 {_d['pdf_count']} PDFs found")
                    if not _d.get("pypdf_available", True):
                        diag_parts.append("❌ **pypdf not installed** — all PDFs skipped")
                    if _d.get("skipped_empty_text", 0) > 0:
                        diag_parts.append(
                            f"⚠️ {_d['skipped_empty_text']} files returned no text "
                            f"(scanned PDF? or pypdf missing?)"
                        )
                    if _d.get("skipped_unsupported", 0) > 0:
                        diag_parts.append(
                            f"ℹ️ {_d['skipped_unsupported']} files with unsupported "
                            f"extensions skipped (.txt/.md/.pdf only)"
                        )
                    if _d.get("skipped_filter", 0) > 0:
                        diag_parts.append(
                            f"🔽 {_d['skipped_filter']} files excluded by folder/file filter"
                        )
                    if diag_parts:
                        st.info("**Build diagnostics:**\n\n" + "\n\n".join(diag_parts))
            except Exception:
                pass

    # Filtered file listing (exclude hidden files and system placeholders)
    files = sorted([
        p.relative_to(SOURCES_DIR)
        for p in SOURCES_DIR.rglob("*")
        if p.is_file() and not p.name.startswith(".") and p.name not in _SKIP_NAMES
    ])
    if files:
        with st.expander(f"Source files ({len(files)})", expanded=False):
            st.write(files[:200])
            if len(files) > 200:
                st.caption(f"Showing first 200 of {len(files)}.")
    else:
        st.info("No source files yet.")

elif step.startswith("4"):
    st.subheader("4) Generate Julius prompt")
    if st.session_state.spec is None:
        st.warning("Create a spec first (Step 2).")
    else:
        prompt = julius_prompt_from_spec(st.session_state.spec)
        st.text_area("Copy/paste into Julius", value=prompt, height=420)
        st.download_button("Download julius_prompt.txt", prompt.encode("utf-8"), file_name="julius_prompt.txt", mime="text/plain")

elif step.startswith("5"):
    st.subheader("5) Upload artefacts + LLM interpretation")
    if st.session_state.spec is None:
        st.warning("Create a spec first (Step 2).")
    else:
        run_id = st.text_input("Run ID (blank = auto)", value="")
        if not run_id.strip():
            run_id = str(uuid.uuid4())[:8]
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Initialise session-state caches for uploaded file bytes
        for _key in ["_up_comp", "_up_coeff", "_up_diags", "_up_interp", "_up_spec_file"]:
            if _key not in st.session_state:
                st.session_state[_key] = None

        col1, col2 = st.columns(2)
        with col1:
            comp = st.file_uploader("model_comparison.csv", type=["csv"])
            coeff = st.file_uploader("model_coefficients.csv", type=["csv"])
            diags = st.file_uploader("diagnostics.json", type=["json"])
        with col2:
            interp = st.file_uploader("LLM interpretation (txt)", type=None)
            spec_file = st.file_uploader("analysis_spec.json (optional override)", type=["json"])

        # Persist bytes into session state on each new upload
        if comp is not None:
            st.session_state["_up_comp"] = comp.read()
            comp.seek(0)
        if coeff is not None:
            st.session_state["_up_coeff"] = coeff.read()
            coeff.seek(0)
        if diags is not None:
            st.session_state["_up_diags"] = diags.read()
            diags.seek(0)
        if interp is not None:
            st.session_state["_up_interp"] = interp.read()
            interp.seek(0)
        if spec_file is not None:
            st.session_state["_up_spec_file"] = spec_file.read()
            spec_file.seek(0)

        # Show what is currently held (uploaded or cached)
        cached = [
            ("model_comparison.csv", "_up_comp"),
            ("model_coefficients.csv", "_up_coeff"),
            ("diagnostics.json", "_up_diags"),
            ("interpretation.txt", "_up_interp"),
            ("analysis_spec.json", "_up_spec_file"),
        ]
        held = [label for label, key in cached if st.session_state.get(key) is not None]
        if held:
            st.info("Staged (retained across steps): " + ", ".join(held))

        if st.button("Save uploads"):
            _comp_bytes = st.session_state.get("_up_comp")
            _coeff_bytes = st.session_state.get("_up_coeff")
            _diags_bytes = st.session_state.get("_up_diags")
            _interp_bytes = st.session_state.get("_up_interp")
            _spec_bytes = st.session_state.get("_up_spec_file")

            if _spec_bytes is not None:
                spec_json = _spec_bytes.decode("utf-8", errors="ignore")
                st.session_state.spec = AnalysisSpec.model_validate_json(spec_json)
                (run_dir / "analysis_spec.json").write_text(spec_json, encoding="utf-8")
            else:
                (run_dir / "analysis_spec.json").write_text(st.session_state.spec.model_dump_json(indent=2), encoding="utf-8")

            brief = ""
            try:
                brief = st.session_state.spec.notes.get("project_brief", "").strip()
            except Exception:
                brief = ""
            if brief:
                (run_dir / "project_brief.md").write_text(brief + "\n", encoding="utf-8")

            if _comp_bytes:
                (run_dir / "model_comparison.csv").write_bytes(_comp_bytes)
            if _coeff_bytes:
                (run_dir / "model_coefficients.csv").write_bytes(_coeff_bytes)
            if _diags_bytes:
                (run_dir / "diagnostics.json").write_bytes(_diags_bytes)
            if _interp_bytes:
                (run_dir / "interpretation.txt").write_bytes(_interp_bytes)

            st.success(f"Saved run folder: {run_dir}")


elif step.startswith("6"):
    st.subheader("6) Verification")

    runs = sorted([p.name for p in RUNS_DIR.iterdir() if p.is_dir()])
    if not runs:
        st.warning("No runs saved yet (Step 5).")
        st.stop()

    run_id = st.selectbox("Run folder", runs, index=len(runs) - 1)
    run_dir = RUNS_DIR / run_id

    # Load spec + interpretation
    spec_path = run_dir / "analysis_spec.json"
    interp_path = run_dir / "interpretation.txt"
    if not spec_path.exists():
        st.error("Missing analysis_spec.json in run folder.")
        st.stop()

    spec = AnalysisSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    interpretation = interp_path.read_text(encoding="utf-8", errors="ignore") if interp_path.exists() else ""

    # Lightweight run summary cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Objective", str(spec.objective))
    c2.metric("Outcome", str(spec.outcome))
    c3.metric("Candidate models", len(spec.candidate_models))
    c4.metric("Criterion", str(spec.information_criterion))

    # Optional: limit verification retrieval to source folders
    top_folders = sorted([p.name for p in SOURCES_DIR.iterdir() if p.is_dir() and not p.name.startswith('.')])
    stored = st.session_state.get("verify_allowed_folders", top_folders)
    opt_map = {opt.strip(): opt for opt in top_folders}
    cleaned = []
    seen = set()
    for v in stored:
        key = str(v).strip()
        if key in opt_map:
            actual = opt_map[key]
            if actual not in seen:
                cleaned.append(actual)
                seen.add(actual)
    if not cleaned:
        cleaned = top_folders
    st.session_state["verify_allowed_folders"] = cleaned

    allowed_folders = st.multiselect(
        "Verify against which source folders?",
        options=top_folders,
        default=cleaned,
        key="verify_allowed_folders",
        help="Filters which indexed documents can be retrieved for verification.",
    )
    allowed_prefixes = [f"{name}/" for name in allowed_folders] if allowed_folders else None

    tab_report, tab_visual, tab_evidence, tab_files = st.tabs(
        ["Verification report", "Visual checks", "Retrieved evidence", "Raw files"]
    )

    # --------------------------
    # Tab: Verification report
    # --------------------------
    with tab_report:
        st.markdown("### Generate report")
        st.caption("This runs deterministic checks plus local retrieval. It writes report.md into the run folder.")

        if st.button("Generate report", type="primary"):
            with st.spinner("Building verification report..."):
                try:
                    report = build_report(
                        spec=spec,
                        run_dir=run_dir,
                        interpretation=interpretation,
                        index_dir=INDEX_DIR,
                        sources_dir=SOURCES_DIR,
                        allowed_prefixes=allowed_prefixes,
                    )
                    st.session_state.last_report = report
                    (run_dir / "report.md").write_text(report, encoding="utf-8")
                    st.success(f"Report saved to: {run_dir / 'report.md'}")
                except Exception as e:
                    st.error("Report generation failed.")
                    st.exception(e)

        rpt_path = run_dir / "report.md"
        if rpt_path.exists():
            rpt = rpt_path.read_text(encoding="utf-8", errors="ignore")
            st.download_button("Download report.md", rpt.encode("utf-8"), file_name="report.md", mime="text/markdown")

            # Quick summary of major issues
            if "## Major issues detected" in rpt:
                block = rpt.split("## Major issues detected", 1)[1]
                block = block.split("\n## ", 1)[0]
                issues = [ln.strip() for ln in block.splitlines() if "**PROBLEM:**" in ln]
                if issues:
                    st.error(f"Major issues detected: {len(issues)}")
                    for ln in issues[:20]:
                        st.write("• " + ln.replace("- **PROBLEM:**", "").strip())
                    if len(issues) > 20:
                        st.caption(f"Showing first 20 of {len(issues)}.")
                else:
                    st.success("No major issues detected by the current rule set (not a guarantee).")
            st.markdown("---")
            st.markdown(rpt)

    # --------------------------
    # Tab: Visual checks (optional)
    # --------------------------
    with tab_visual:
        st.markdown("### Visual evidence check (optional)")
        st.caption(
            "These summaries are intended as a fast sanity-check for demonstrations. "
            "They do not replace the report."
        )

        # Always load the artefact CSVs (lightweight)
        comp_df = None
        coef_df = None
        try:
            comp_path = run_dir / "model_comparison.csv"
            if comp_path.exists():
                comp_df = pd.read_csv(comp_path)
        except Exception:
            comp_df = None
        try:
            coef_path = run_dir / "model_coefficients.csv"
            if coef_path.exists():
                coef_df = pd.read_csv(coef_path)
        except Exception:
            coef_df = None

        # ---- Delta-IC table (always shown) ----
        st.subheader("Model comparison (Δ table)")
        if comp_df is None or comp_df.empty:
            st.info("model_comparison.csv not found (or empty).")
        else:
            df_comp = comp_df.copy()
            if "model_id" in df_comp.columns:
                df_comp["model_id"] = df_comp["model_id"].astype(str)

            # Add formula column from spec
            _fm: dict[str, str] = {}
            try:
                for _i, _f in enumerate(spec.candidate_models, start=1):
                    _fm[str(_i)] = _f
            except Exception:
                pass
            if _fm and "model_id" in df_comp.columns:
                df_comp.insert(1, "Formula", df_comp["model_id"].map(_fm).fillna(""))

            # Build a short label for charts: "M1: log(vo2) ~ LnFFF + Sex..."
            def _short_label(row):
                mid = str(row.get("model_id", ""))
                formula = str(row.get("Formula", ""))
                if formula:
                    # Truncate long formulas for chart readability
                    if len(formula) > 45:
                        formula = formula[:42] + "..."
                    return f"M{mid}: {formula}"
                return f"Model {mid}"

            if "model_id" in df_comp.columns:
                df_comp["_label"] = df_comp.apply(_short_label, axis=1)

            # Metrics where lower is better: delta = value - min
            _LOWER_BETTER = ["aic", "bic", "looic", "waic", "rmse_log", "rmse_raw", "mae", "bf01"]
            # Metrics where higher is better: delta = max - value
            _HIGHER_BETTER = ["elpd_loo", "elpd_waic", "r2", "bf10"]

            delta_cols: list[str] = []
            for col in _LOWER_BETTER:
                if col in df_comp.columns:
                    vals = pd.to_numeric(df_comp[col], errors="coerce")
                    if vals.notna().any():
                        dcol = f"Δ{col.upper()}"
                        df_comp[dcol] = vals - vals.min()
                        delta_cols.append(dcol)
            for col in _HIGHER_BETTER:
                if col in df_comp.columns:
                    vals = pd.to_numeric(df_comp[col], errors="coerce")
                    if vals.notna().any():
                        dcol = f"Δ{col.upper()}"
                        df_comp[dcol] = vals.max() - vals
                        delta_cols.append(dcol)

            if not delta_cols:
                st.info("No recognised comparison metric columns found in model_comparison.csv.")
            else:
                # Display table: model_id + formula + delta columns (rounded for readability)
                _id_cols = ["model_id"] if "model_id" in df_comp.columns else []
                _formula_cols = ["Formula"] if "Formula" in df_comp.columns else []
                show_cols = _id_cols + _formula_cols + delta_cols
                display_df = df_comp[show_cols].copy()
                for dc in delta_cols:
                    display_df[dc] = display_df[dc].round(2)
                st.dataframe(display_df, use_container_width=True, hide_index=True)

                st.caption(
                    "Δ = distance from best model (0 = best). For information criteria, "
                    "Burnham & Anderson (2002) thresholds: **Δ < 2** substantial support; "
                    "**2–7** some support; **> 10** essentially none. These thresholds "
                    "apply to AIC/BIC/LOOIC/WAIC; they do not apply directly to RMSE, "
                    "R², or Bayes factors."
                )

        # ---- Delta plots (opt-in) ----
        show_plots = st.checkbox("Show Δ plots", value=False, help="Opt-in: bar charts of Δ values.")
        if show_plots and comp_df is not None and not comp_df.empty:
            if delta_cols:
                st.subheader("Δ plots")
                _label_col = "_label" if "_label" in df_comp.columns else "model_id"
                for dcol in delta_cols:
                    if dcol in df_comp.columns and _label_col in df_comp.columns:
                        chart_data = df_comp[[_label_col, dcol]].dropna().set_index(_label_col)
                        if not chart_data.empty:
                            st.caption(f"`{dcol}` by model (0 = best)")
                            st.bar_chart(chart_data[dcol])

        st.markdown("---")

        # ---- Coefficients ----
        show_svalues = st.checkbox(
            "Show S-values (pedagogical, frequentist p-values only)",
            value=False,
            help="Only meaningful if your coefficients table includes p-values. Not used for Bayesian inference.",
        )

        st.subheader("Coefficients")
        if coef_df is None or coef_df.empty:
            st.info("model_coefficients.csv not found (or empty).")
        else:
            st.dataframe(coef_df.head(50), use_container_width=True, height=260)
            st.caption(
                "**Note:** Coefficient magnitude does not directly indicate predictor importance. "
                "Comparisons across predictors depend on scaling, collinearity, and the model set. "
                "Claims such as 'X is the single best predictor' cannot be verified from "
                "coefficients alone."
            )

            if show_svalues:
                prob_mode = str(spec.notes.get("framework", {}).get("probability", "")).strip().lower() if isinstance(spec.notes, dict) else ""
                if prob_mode == "bayesian":
                    st.warning("S-values are a p-value transformation and are not a Bayesian evidential quantity.")
                p_col = None
                for c in coef_df.columns:
                    if str(c).strip().lower() in {"p.value", "p_value", "pval", "p", "pr(>|t|)", "pr(>|z|)"}:
                        p_col = c
                        break
                if p_col is None:
                    st.info("No p-value column detected in coefficients table.")
                else:
                    import numpy as np
                    s = pd.to_numeric(coef_df[p_col], errors="coerce").clip(lower=1e-300)
                    s_bits = (-np.log2(s)).rename("s_value_bits")
                    tmp = coef_df.copy()
                    tmp["s_value_bits"] = s_bits
                    term_col = "term" if "term" in tmp.columns else tmp.columns[0]
                    ss = tmp[[term_col, "s_value_bits"]].dropna().head(30).set_index(term_col)
                    st.caption("S-values (bits) for first 30 terms. 4.3 bits ≈ p=0.05.")
                    st.bar_chart(ss["s_value_bits"])

    # --------------------------
    # Tab: Retrieved evidence (claim-level or global retrieval)
    # --------------------------
    with tab_evidence:
        st.markdown("### Retrieved evidence")
        claim_path = run_dir / "retrieval_claims.json"
        global_path = run_dir / "retrieval.json"

        if claim_path.exists():
            st.caption("Claim-level retrieval (retrieval_claims.json).")
            try:
                retrieval = json.loads(claim_path.read_text(encoding="utf-8"))
            except Exception:
                retrieval = []
            if not retrieval:
                st.info("retrieval_claims.json exists but contains no entries.")
            else:
                # Summary table
                rows = []
                for r in retrieval:
                    rows.append({
                        "claim_id": r.get("claim_id"),
                        "claim": (r.get("claim") or "")[:120],
                        "n_hits": len(r.get("hits") or []),
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=220)

                sel = st.selectbox("Select claim", options=list(range(len(retrieval))), format_func=lambda i: f"Claim {retrieval[i].get('claim_id')}: {(retrieval[i].get('claim') or '')[:80]}")
                item = retrieval[sel]
                st.markdown(f"**Claim:** {item.get('claim','')}")
                hits = item.get("hits") or []
                if not hits:
                    st.info("No retrieval hits recorded for this claim.")
                else:
                    for h in hits:
                        st.markdown("---")
                        st.markdown(f"**Source:** `{h.get('source','')}` (score={h.get('score',0):.3f}, chunk={h.get('chunk',-1)})")
                        st.text_area("Chunk text", value=(h.get("text") or "")[:4000], height=180, key=f"chunk_{sel}_{h.get('chunk',-1)}")

                st.download_button(
                    "Download retrieval_claims.json",
                    claim_path.read_bytes(),
                    file_name="retrieval_claims.json",
                    mime="application/json",
                )

        elif global_path.exists():
            st.caption("Global retrieval (retrieval.json) produced from the whole document.")
            try:
                retrieval = json.loads(global_path.read_text(encoding="utf-8"))
            except Exception:
                retrieval = []
            if not retrieval:
                st.info("retrieval.json exists but contains no entries.")
            else:
                df_ret = pd.DataFrame(retrieval)
                cols = [c for c in ["score", "source", "chunk"] if c in df_ret.columns]
                st.dataframe(df_ret[cols], use_container_width=True, height=220)
                sel = st.selectbox(
                    "Select a retrieved chunk to view",
                    options=list(range(len(retrieval))),
                    format_func=lambda i: f"{retrieval[i].get('source','')} (chunk {retrieval[i].get('chunk',-1)}, score {retrieval[i].get('score',0):.3f})",
                )
                st.text_area("Chunk text", value=(retrieval[sel].get("text","") or "")[:4000], height=260)
                st.download_button(
                    "Download retrieval.json",
                    global_path.read_bytes(),
                    file_name="retrieval.json",
                    mime="application/json",
                )
        else:
            st.info("No retrieval file found yet. Generate the report first.")

    # --------------------------
    # Tab: Raw files
    # --------------------------
    with tab_files:
        st.markdown("### Run folder contents")
        files = sorted([p for p in run_dir.glob("*") if p.is_file()])
        if not files:
            st.info("No files in this run folder.")
        else:
            st.write([p.name for p in files])
            # Convenience preview
            for name in ["analysis_spec.json", "model_comparison.csv", "model_coefficients.csv", "diagnostics.json", "interpretation.txt"]:
                p = run_dir / name
                if p.exists():
                    st.markdown(f"#### {name}")
                    if name.endswith(".csv"):
                        try:
                            st.dataframe(pd.read_csv(p).head(50), use_container_width=True)
                        except Exception:
                            st.code(p.read_text(encoding="utf-8", errors="ignore")[:4000])
                    else:
                        st.code(p.read_text(encoding="utf-8", errors="ignore")[:6000])
