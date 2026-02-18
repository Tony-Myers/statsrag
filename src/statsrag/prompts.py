from __future__ import annotations
from typing import List
from statsrag.schema import AnalysisSpec


def _common_header(spec: AnalysisSpec, prob: str) -> List[str]:
    """Preamble shared by all frameworks."""
    fw = (spec.notes or {}).get("framework", {})
    philosophy = str(fw.get("philosophy", "")).strip().lower()

    lines: List[str] = []
    lines.append("You are acting as a statistical assistant. Follow the analysis specification exactly.")
    lines.append("")
    lines.append("## Objective")
    lines.append(f"- Primary objective: {spec.objective}")
    _analysis_type = str((spec.notes or {}).get("analysis_type", "regression")).strip().lower()
    _atype_labels = {
        "regression": "regression / modelling",
        "group_comparison": "group comparison (difference test)",
        "correlation": "correlation / association",
    }
    lines.append(f"- Analysis type: {_atype_labels.get(_analysis_type, _analysis_type)}")
    lines.append(f"- Outcome column: {spec.outcome}")
    lines.append(f"- Predictors available: {', '.join(spec.predictors)}")
    lines.append(f"- Probability framework: **{prob}**")
    if philosophy:
        _philosophy_labels = {
            "realist": "realist",
            "constructivist": "constructivist",
            "scientific_antirealist": "scientific antirealist",
        }
        lines.append(
            f"- Philosophical framework: **{_philosophy_labels.get(philosophy, philosophy)}**"
        )
    modeling = (spec.notes or {}).get("modeling", {})
    if modeling:
        ok = modeling.get("outcome_type")
        if ok:
            lines.append(f"- Outcome type: {ok}")
        fam = modeling.get("response_family")
        if fam:
            # Human-readable family labels for the prompt
            _family_prompt_labels = {
                "gaussian": "Gaussian (normal)",
                "student": "Student-t (robust)",
                "lognormal": "Log-normal",
                "Gamma": "Gamma (log link)",
                "skew_normal": "Skew-normal",
                "exgaussian": "Ex-Gaussian",
                "bernoulli": "Bernoulli (logistic)",
                "bernoulli_probit": "Bernoulli (probit link)",
                "poisson": "Poisson",
                "negbinomial": "Negative binomial",
                "zero_inflated_poisson": "Zero-inflated Poisson",
                "zero_inflated_negbinomial": "Zero-inflated negative binomial",
                "hurdle_poisson": "Hurdle Poisson",
                "hurdle_negbinomial": "Hurdle negative binomial",
                "cumulative": "Cumulative (proportional odds)",
                "sratio": "Stopping-ratio (ordinal)",
                "cratio": "Continuation-ratio (ordinal)",
                "acat": "Adjacent-category (ordinal)",
                "Beta": "Beta (proportions)",
                "zero_one_inflated_beta": "Zero-one-inflated Beta",
                "weibull": "Weibull (survival)",
                "cox": "Cox proportional hazards",
            }
            lines.append(f"- Response distribution: **{_family_prompt_labels.get(fam, fam)}**")
        re_info = modeling.get("random_effects", {})
        if isinstance(re_info, dict) and re_info.get("structure", "none") != "none":
            re_str = re_info.get("formula_string", "")
            if re_str:
                lines.append(f"- Random effects: `{re_str}`")
        else:
            # Backward compatibility: old-style random_intercept field
            ri = modeling.get("random_intercept")
            if ri:
                lines.append(f"- Random intercept: (1|{ri})")
    lines.append("")
    return lines


def _models_section(spec: AnalysisSpec) -> List[str]:
    lines: List[str] = []
    lines.append("## Candidate models (do not add/remove models)")
    for i, m in enumerate(spec.candidate_models, start=1):
        lines.append(f"{i}. {m}")
    lines.append("")
    return lines


def _transformation_section(spec: AnalysisSpec) -> List[str]:
    lines: List[str] = []
    lines.append("## Transformation policy")
    lines.append(f"- Log outcome: {'YES' if spec.transformations.log_outcome else 'NO'}")
    if spec.transformations.log_predictors:
        lines.append(f"- Log predictors: {', '.join(spec.transformations.log_predictors)}")
    if spec.transformations.no_transform:
        lines.append(f"- Do NOT transform: {', '.join(spec.transformations.no_transform)}")
    lines.append("")
    return lines


def _prohibitions_and_required(spec: AnalysisSpec) -> List[str]:
    lines: List[str] = []
    if spec.prohibitions:
        lines.append("## Prohibitions (do not violate)")
        for p in spec.prohibitions:
            lines.append(f"- {p}")
        lines.append("")
    if spec.required_reporting:
        lines.append("## Required reporting items (include in interpretation)")
        for r in spec.required_reporting:
            lines.append(f"- {r}")
        lines.append("")
    return lines


# ============================================================
# Frequentist prompt
# ============================================================

def _frequentist_prompt(spec: AnalysisSpec) -> List[str]:
    """Build prompt sections specific to a frequentist analysis."""
    lines: List[str] = []

    lines.append("## Validation / model comparison")
    lines.append(f"- Validation method: {spec.validation.method}")
    if spec.validation.method == "kfold_cv":
        lines.append(f"- k: {spec.validation.k}")
    lines.append(f"- seed: {spec.validation.seed}")
    lines.append(f"- metric: {spec.validation.metric}")
    lines.append(f"- information criterion: {spec.information_criterion}")
    lines.append("")

    lines.append("## Output requirements (MUST produce these files)")
    lines.append(
        "1) model_comparison.csv: one row per model; include columns: "
        "model_id, formula, aic, bic, rmse_log, rmse_raw, mae, r2 "
        "(use NA where not applicable)."
    )
    lines.append(
        "2) model_coefficients.csv for the best model: include columns: "
        "term, estimate, se, lower, upper, scale (log/raw), "
        "interval_type (CI), model_id."
    )
    lines.append(
        "3) diagnostics.json: include key checks "
        "(residual plots summary; influence/outlier notes if checked)."
    )
    lines.append(
        "4) interpretation.txt: your interpretation in plain language, "
        "constrained by the prohibitions below."
    )
    lines.append("")

    lines.append("## R implementation guidance (preferred)")
    lines.append(
        "- Use R. If models are lm/glm/lmer, use appropriate base/lme4 functions."
    )
    lines.append(
        "- Ensure all models are compared on the same analytic rows "
        "(complete cases for all variables used by any candidate model)."
    )
    lines.append("")

    return lines


# ============================================================
# Prior specification (Bayesian only)
# ============================================================

def _prior_section(spec: AnalysisSpec) -> List[str]:
    """Generate prior specification prompt text from spec.notes['priors'].

    Supports three tiers:
    - weakly_informative: instruct LLM to use brms defaults
    - guided: translate domain beliefs into prior recommendations
    - formal: pass user-specified priors verbatim
    """
    priors = (spec.notes or {}).get("priors", {})
    tier = priors.get("tier", "weakly_informative")

    lines: List[str] = []
    lines.append("## Prior specification")

    if tier == "formal":
        formal_text = priors.get("formal_text", "").strip()
        lines.append("- Strategy: **user-specified formal priors**")
        lines.append("")
        if formal_text:
            lines.append("Use the following priors exactly as specified:")
            lines.append("```r")
            lines.append(formal_text)
            lines.append("```")
        else:
            lines.append("(No formal priors were provided — use brms defaults.)")
        lines.append("")
        lines.append(
            "- For any parameters not covered above, use brms weakly "
            "informative defaults and note which parameters used defaults."
        )
        lines.append("")

    elif tier == "guided":
        lines.append("- Strategy: **domain-informed priors**")
        lines.append(
            "- The researcher has provided domain knowledge to guide prior "
            "selection. Translate these beliefs into appropriate brms priors. "
            "The priors should be weakly informative but informed by the "
            "stated expectations — do not use point-mass priors."
        )
        lines.append("")

        # Outcome expectations
        outcome_typical = priors.get("outcome_typical")
        outcome_spread = priors.get("outcome_spread")
        modeling = (spec.notes or {}).get("modeling", {})
        transform = modeling.get("outcome_transform", "none")
        _scale_names = {
            "log": "log scale",
            "sqrt": "square-root scale",
            "boxcox": "Box-Cox transformed scale",
            "none": "raw (untransformed) scale",
        }
        scale_label = _scale_names.get(transform, "modelled scale")

        if outcome_typical is not None or outcome_spread is not None:
            lines.append("### Outcome expectations")
            if outcome_typical is not None:
                lines.append(
                    f"- Typical outcome value ({scale_label}): "
                    f"approximately {outcome_typical}"
                )
            if outcome_spread is not None:
                lines.append(
                    f"- Plausible spread: ± {outcome_spread} from the "
                    f"typical value"
                )
            lines.append(
                "- Use these to set the intercept prior. A reasonable "
                "choice: Normal(typical_value, spread) or "
                "student_t(3, typical_value, spread)."
            )
            lines.append("")

        # Predictor beliefs
        beliefs = priors.get("predictor_beliefs", {})
        if beliefs:
            lines.append("### Researcher's beliefs about predictor effects")
            lines.append(
                "| Predictor | Expected direction | Expected magnitude |"
            )
            lines.append("| --- | --- | --- |")
            for pred, info in beliefs.items():
                d = info.get("direction", "uncertain")
                m = info.get("magnitude", "unknown")
                lines.append(f"| {pred} | {d} | {m} |")
            lines.append("")

            # Translation guidance
            lines.append("### Translation guidance for the analyst")
            lines.append(
                "Convert the researcher's beliefs into brms priors using "
                "these principles:"
            )
            lines.append(
                "- **Direction = uncertain**: use a symmetric prior centred "
                "at zero (e.g. Normal(0, σ))."
            )
            lines.append(
                "- **Direction = positive/negative**: centre the prior "
                "slightly in the expected direction. Do not use a "
                "one-sided prior — allow the data to override the belief."
            )
            lines.append(
                "- **Magnitude mapping** (approximate guide for regression "
                "coefficients):"
            )
            lines.append(
                "  - negligible → narrow prior, e.g. Normal(0, 0.1)"
            )
            lines.append(
                "  - small → Normal(±0.1, 0.3) or similar"
            )
            lines.append(
                "  - moderate → Normal(±0.3, 0.5) or similar"
            )
            lines.append(
                "  - large → Normal(±0.5, 1.0) or wider"
            )
            lines.append(
                "  - unknown → use the weakly informative default "
                "(e.g. Normal(0, 2.5))"
            )
            lines.append(
                "- These are on the **coefficient scale** of the model. "
                "If the outcome is log-transformed, a coefficient of 0.3 "
                "corresponds to approximately a 35% multiplicative change "
                "per unit of the predictor."
            )
            lines.append(
                "- State the chosen priors explicitly in the interpretation "
                "and explain the rationale."
            )
            lines.append("")

        # Domain notes
        domain_notes = priors.get("domain_notes", "").strip()
        if domain_notes:
            lines.append("### Additional domain context from the researcher")
            lines.append(f"> {domain_notes}")
            lines.append("")

    else:  # weakly_informative (default)
        lines.append("- Strategy: **weakly informative defaults**")
        lines.append(
            "- Use brms default weakly informative priors for all "
            "parameters (typically student_t for the intercept, flat or "
            "weakly regularising for regression coefficients)."
        )
        lines.append(
            "- State the priors used in the interpretation. If using brms "
            "defaults without modification, say so explicitly."
        )
        lines.append("")

    # Model priors (for hypothesis testing)
    model_priors = priors.get("model_priors", {})
    if model_priors:
        strategy = model_priors.get("strategy", "equal")
        lines.append("### Model prior probabilities")
        if strategy == "equal":
            n = len(spec.candidate_models) or 1
            lines.append(
                f"- Equal prior probability: 1/{n} for each candidate model."
            )
        else:
            custom_text = model_priors.get("text", "").strip()
            if custom_text:
                lines.append(
                    "- Custom prior model odds (as specified by the "
                    "researcher):"
                )
                for cline in custom_text.splitlines():
                    if cline.strip():
                        lines.append(f"  - {cline.strip()}")
            else:
                lines.append(
                    "- Custom model priors were selected but none were "
                    "specified. Use equal prior probability as a fallback."
                )
        lines.append(
            "- Report prior model odds alongside Bayes factors and "
            "posterior model probabilities."
        )
        lines.append("")

    return lines


# ============================================================
# Bayesian prompt (aim-forked)
# ============================================================

_BAYESIAN_HARD_PROHIBITIONS = [
    "Do NOT use AIC or BIC. These are frequentist information criteria and have no role in a Bayesian analysis.",
    "Do NOT use the phrase 'confidence interval'. Use 'credible interval' (CrI) for posterior intervals.",
    "Do NOT claim that a model is 'true' or 'true with high probability'. Bayesian model comparison quantifies relative predictive performance or evidence, not truth.",
    "Do NOT mix frequentist p-values with Bayesian posterior summaries in the same interpretive statement.",
]


def _bayesian_prompt(spec: AnalysisSpec) -> List[str]:
    """Build prompt sections for a Bayesian analysis, forked by aim."""
    fw = (spec.notes or {}).get("framework", {})
    aim = str(fw.get("bayesian_aim", "estimation")).strip().lower()
    if aim not in {"estimation", "predictive_comparison", "hypothesis_testing"}:
        aim = "estimation"

    lines: List[str] = []

    # --- Bayesian aim declaration ---
    _aim_labels = {
        "estimation": "Bayesian estimation (posterior summaries, credible intervals)",
        "predictive_comparison": "Bayesian predictive model comparison (PSIS-LOO / WAIC / ELPD)",
        "hypothesis_testing": "Bayesian hypothesis testing (Bayes factors)",
    }
    lines.append(f"## Bayesian analysis aim: {_aim_labels[aim]}")
    lines.append("")

    # --- Aim-specific validation / comparison ---
    if aim == "estimation":
        lines.append("## Validation / model checking")
        lines.append(
            "- Primary purpose: obtain well-calibrated posterior summaries "
            "and credible intervals for the parameters of interest."
        )
        lines.append(f"- Validation method: {spec.validation.method}")
        if spec.validation.method == "kfold_cv":
            lines.append(f"- k: {spec.validation.k}")
        lines.append(f"- seed: {spec.validation.seed}")
        lines.append(
            "- LOO/WAIC may be reported for model checking but is not the "
            "primary aim. Do not frame it as a model 'contest'."
        )
        lines.append("")

    elif aim == "predictive_comparison":
        lines.append("## Validation / model comparison")
        lines.append(
            "- Primary purpose: compare candidate models on out-of-sample "
            "predictive performance using PSIS-LOO or WAIC."
        )
        lines.append(f"- Validation method: {spec.validation.method}")
        if spec.validation.method == "kfold_cv":
            lines.append(f"- k: {spec.validation.k}")
        lines.append(f"- seed: {spec.validation.seed}")
        lines.append(f"- metric: {spec.validation.metric}")
        lines.append(f"- information criterion: {spec.information_criterion}")
        lines.append("")
        lines.append("### Direction rules (critical)")
        lines.append("- ELPD: **higher** is better (more positive = better predictive accuracy).")
        lines.append("- LOOIC / WAIC: **lower** is better (these are on a deviance scale, analogous to AIC).")
        lines.append("- When reporting ΔELPD, the reference model has Δ = 0 and worse models have negative Δ.")
        lines.append("")

    elif aim == "hypothesis_testing":
        lines.append("## Hypothesis testing via Bayes factors")
        lines.append(
            "- Primary purpose: quantify the evidential support for one model "
            "(or hypothesis) relative to another using Bayes factors."
        )
        lines.append(f"- seed: {spec.validation.seed}")
        lines.append("")
        lines.append("### Bayes factor interpretation guidance")
        lines.append("- A Bayes factor (BF10) is a likelihood ratio: how many times more likely the data are under M1 vs M0.")
        lines.append("- BF10 > 1 favours M1; BF10 < 1 favours M0.")
        lines.append("- BF10 is NOT a posterior probability. Converting to posterior model probabilities requires explicit prior model odds.")
        lines.append("- Always state the prior distributions used and acknowledge that BFs can be sensitive to the choice of priors (especially for point-null tests).")
        lines.append("- If using bridge sampling or Savage-Dickey density ratio, state the method.")
        lines.append("")
        lines.append("### Interpretation thresholds (Jeffreys / Kass & Raftery, for reference only)")
        lines.append("- BF10 1-3: anecdotal / not worth more than a bare mention")
        lines.append("- BF10 3-10: moderate / substantial")
        lines.append("- BF10 10-100: strong")
        lines.append("- BF10 > 100: decisive / very strong")
        lines.append("- These are conventions, not bright-line rules.")
        lines.append("")

    # --- Prior specification ---
    lines.extend(_prior_section(spec))

    # --- Output requirements (Bayesian) ---
    lines.append("## Output requirements (MUST produce these files)")

    if aim == "predictive_comparison":
        lines.append(
            "1) model_comparison.csv: one row per model; include columns: "
            "model_id, formula, looic, waic, elpd_loo, elpd_waic, "
            "rmse_log, rmse_raw, mae "
            "(use NA where not applicable). "
            "Do NOT include aic or bic columns."
        )
    elif aim == "hypothesis_testing":
        lines.append(
            "1) model_comparison.csv: one row per model; include columns: "
            "model_id, formula, bf10, bf01, rmse_log, rmse_raw "
            "(use NA where not applicable). "
            "Do NOT include aic or bic columns. "
            "bf10 = Bayes factor for this model vs the reference (Model 1). "
            "bf01 = 1/bf10."
        )
    else:  # estimation
        lines.append(
            "1) model_comparison.csv: one row per model; include columns: "
            "model_id, formula, looic, waic, elpd_loo, elpd_waic, "
            "rmse_log, rmse_raw, mae "
            "(use NA where not applicable). "
            "Do NOT include aic or bic columns."
        )

    lines.append(
        "2) model_coefficients.csv for the best model: include columns: "
        "term, estimate, se, lower, upper, scale (log/raw), "
        "interval_type (CrI), model_id. "
        "Label intervals as credible intervals (CrI), not confidence intervals."
    )
    if aim == "hypothesis_testing":
        lines.append(
            "3) diagnostics.json: include key checks "
            "(posterior convergence: Rhat, ESS; "
            "posterior predictive check summary). "
            "Do NOT include PSIS-LOO or Pareto-k diagnostics — these are "
            "not applicable when the aim is Bayes-factor hypothesis testing."
        )
    else:
        lines.append(
            "3) diagnostics.json: include key checks "
            "(posterior convergence: Rhat, ESS; "
            "PSIS-LOO Pareto-k summary when using LOO; "
            "posterior predictive check summary)."
        )
    lines.append(
        "4) interpretation.txt: your interpretation in plain language, "
        "constrained by the prohibitions below."
    )
    lines.append("")

    # --- Hard Bayesian prohibitions (always enforced) ---
    lines.append("## Bayesian-specific prohibitions (always enforced)")
    for p in _BAYESIAN_HARD_PROHIBITIONS:
        lines.append(f"- {p}")
    lines.append("")

    # --- R implementation guidance (Bayesian) ---
    lines.append("## R implementation guidance (preferred)")
    if aim == "hypothesis_testing":
        lines.append(
            "- Use R with brms (+ bridgesampling for Bayes factors). "
            "Do NOT use the loo package — PSIS-LOO is not appropriate "
            "when the aim is hypothesis testing via Bayes factors."
        )
    else:
        lines.append("- Use R with brms (+ loo package for PSIS-LOO) unless the model explicitly indicates INLA.")
    lines.append("- State priors explicitly. If using brms defaults, say so.")
    if aim == "hypothesis_testing":
        lines.append(
            "- For Bayes factors: consider bridgesampling::bridge_sampler() "
            "or brms::bayes_factor(). State the computational method."
        )
        lines.append(
            "- Be aware that Bayes factors can be sensitive to prior widths, "
            "especially for point-null vs diffuse-alternative tests."
        )
    lines.append(
        "- Ensure all models are compared on the same analytic rows "
        "(complete cases for all variables used by any candidate model)."
    )
    lines.append("")

    return lines


# ============================================================
# Hybrid prompt
# ============================================================

def _hybrid_prompt(spec: AnalysisSpec) -> List[str]:
    """Build prompt sections for a hybrid (mixed-paradigm) analysis."""
    lines: List[str] = []

    lines.append("## Validation / model comparison")
    lines.append(f"- Validation method: {spec.validation.method}")
    if spec.validation.method == "kfold_cv":
        lines.append(f"- k: {spec.validation.k}")
    lines.append(f"- seed: {spec.validation.seed}")
    lines.append(f"- metric: {spec.validation.metric}")
    lines.append(f"- information criterion: {spec.information_criterion}")
    lines.append("")

    lines.append("## Output requirements (MUST produce these files)")
    lines.append(
        "1) model_comparison.csv: one row per model; include columns: "
        "model_id, formula, aic, bic, looic, waic, elpd_loo, elpd_waic, "
        "rmse_log, rmse_raw, mae, r2 "
        "(use NA where not applicable)."
    )
    lines.append(
        "2) model_coefficients.csv for the best model: include columns: "
        "term, estimate, se, lower, upper, scale (log/raw), "
        "interval_type (CI/CrI), model_id."
    )
    lines.append(
        "3) diagnostics.json: include key checks "
        "(residual plots summary; PSIS-LOO Pareto-k summary when using LOO)."
    )
    lines.append(
        "4) interpretation.txt: your interpretation in plain language, "
        "constrained by the prohibitions below."
    )
    lines.append("")

    lines.append("## Hybrid-specific guidance")
    lines.append(
        "- Clearly label which quantities are frequentist (e.g. AIC, CI) "
        "and which are Bayesian (e.g. LOOIC, CrI, posterior). "
        "Do not mix interpretations in a single sentence."
    )
    lines.append("")

    lines.append("## R implementation guidance (preferred)")
    lines.append("- Use R. If models are lm/glm/lmer, use appropriate base/lme4 functions.")
    lines.append("- If Bayesian is requested, prefer brms + loo for PSIS-LOO, unless the model explicitly indicates INLA.")
    lines.append(
        "- Ensure all models are compared on the same analytic rows "
        "(complete cases for all variables used by any candidate model)."
    )
    lines.append("")

    return lines


# ============================================================
# Philosophy guidance (contextual framing for the LLM)
# ============================================================

def _philosophy_guidance(spec: AnalysisSpec) -> List[str]:
    """Generate philosophy-specific guidance that frames WHY the
    prohibitions and required-reporting items exist.

    This gives the LLM the conceptual context to produce genuinely
    thoughtful interpretations rather than mechanically satisfying
    a checklist.
    """
    fw = (spec.notes or {}).get("framework", {})
    philosophy = str(fw.get("philosophy", "")).strip().lower()

    if not philosophy or philosophy == "unknown":
        return []

    lines: List[str] = []

    if philosophy == "realist":
        lines.append("## Philosophical stance: realist")
        lines.append("")
        lines.append(
            "You are operating under a **realist** philosophy of statistics. "
            "The core commitment is that statistical models aim to describe "
            "real features of a data-generating process, even though any "
            "particular model is an approximation."
        )
        lines.append("")
        lines.append("### What this means for your interpretation")
        lines.append(
            "- **Estimands matter.** State clearly what real-world quantity "
            "the model targets (e.g. 'the expected VO₂max for a new "
            "individual with these predictors'). Do not leave the reader "
            "guessing what the numbers refer to."
        )
        lines.append(
            "- **Assumptions have ontological weight.** When you state "
            "'linearity on the log scale is assumed', you are claiming "
            "something about the world — that the true relationship is "
            "approximately linear on that scale. Acknowledge this claim "
            "and its fragility."
        )
        lines.append(
            "- **Association ≠ causation without design.** Under realism, "
            "causal claims require a causal identification strategy "
            "(randomisation, IV, DAG-justified adjustment, etc.). "
            "Observational associations should be described as such, "
            "however strong the statistical signal."
        )
        lines.append(
            "- **Model fit ≠ truth.** Good predictive performance or "
            "information-criterion rankings do not establish that a model "
            "is true — only that it is less wrong than alternatives on "
            "the available data (cf. Box, 1976; Mayo, 2018)."
        )
        lines.append("")

    elif philosophy == "constructivist":
        lines.append("## Philosophical stance: constructivist")
        lines.append("")
        lines.append(
            "You are operating under a **constructivist** philosophy of "
            "statistics (cf. Hennig, 2009). The core commitment is that "
            "statistical quantities are not context-free reflections of "
            "reality — they are shaped by measurement choices, construct "
            "definitions, and the operationalisations the researcher "
            "selected. Your interpretation should make these dependencies "
            "visible to the reader."
        )
        lines.append("")
        lines.append("### What this means for your interpretation")
        lines.append(
            "- **Name the constructs and their operationalisations.** "
            "Do not write 'body fat is associated with lower VO₂max' as "
            "though 'body fat' is a self-evident quantity. State how body "
            "fat was measured (e.g. skinfold callipers, BIA, DXA) and "
            "acknowledge that a different measurement method could yield "
            "different associations."
        )
        lines.append(
            "- **Discuss at least one alternative operationalisation.** "
            "For key predictors or the outcome, briefly note how the "
            "analysis might differ under a plausible alternative "
            "measurement (e.g. 'VO₂max measured via a field-based "
            "shuttle-run test rather than direct gas exchange would "
            "introduce additional measurement error and likely attenuate "
            "the observed associations')."
        )
        lines.append(
            "- **Do not present model outputs as context-free facts.** "
            "Phrases like 'the data show that…' or 'the model reveals…' "
            "imply a direct pipeline from reality to numbers. Prefer "
            "'under this operationalisation, the model estimates…' or "
            "'given these measurement choices, the posterior suggests…'."
        )
        lines.append(
            "- **Frame uncertainty as partly construct-dependent.** "
            "Interval estimates reflect sampling variability conditional "
            "on a fixed operationalisation; they do not capture the "
            "additional uncertainty introduced by the choice of construct "
            "definition itself."
        )
        lines.append("")

    elif philosophy == "scientific_antirealist":
        lines.append("## Philosophical stance: scientific antirealist")
        lines.append("")
        lines.append(
            "You are operating under a **scientific antirealist** "
            "(instrumentalist) philosophy of statistics (cf. van Fraassen, "
            "1980). The core commitment is that models are tools for "
            "organising experience and generating predictions — not "
            "literal descriptions of unobservable mechanisms. A model is "
            "assessed by its **empirical adequacy** (does it save the "
            "phenomena?), not by whether its parameters correspond to "
            "'true' hidden quantities."
        )
        lines.append("")
        lines.append("### What this means for your interpretation")
        lines.append(
            "- **Frame conclusions as predictive summaries.** Instead of "
            "'log-mass has a true multiplicative effect of 1.89 on VO₂', "
            "write 'the model predicts that a one-unit increase in "
            "log-mass is associated with a multiplicative factor of "
            "approximately 1.89 in VO₂'. The parameter is a useful "
            "summary, not a window onto a mechanism."
        )
        lines.append(
            "- **Do not claim parameters reveal true mechanisms.** "
            "Even if a coefficient is physiologically interpretable, "
            "resist language that implies the model has uncovered the "
            "'real' data-generating process. Multiple structurally "
            "different models can be empirically adequate for the same "
            "data (underdetermination)."
        )
        lines.append(
            "- **Report sensitivity to modelling assumptions.** Because "
            "the model is valued for its predictions rather than its "
            "structural truth, the reader needs to know how fragile "
            "those predictions are. Note which assumptions, if violated, "
            "would most affect the predictive conclusions."
        )
        lines.append(
            "- **Predictive performance is the primary warrant.** "
            "Cross-validation metrics, LOO-ELPD, or calibration plots "
            "are the most relevant evidence for an instrumentalist. "
            "Good predictive performance justifies using the model; "
            "it does not justify believing it is true."
        )
        lines.append("")

    return lines


# ============================================================
# Response distribution guidance
# ============================================================

def _distribution_guidance(spec: AnalysisSpec, prob: str) -> List[str]:
    """Generate response-distribution-specific guidance for the prompt.

    Only emitted for non-default families (i.e. anything other than
    plain Gaussian) to keep prompts concise for the common case.
    """
    modeling = (spec.notes or {}).get("modeling", {})
    fam = str(modeling.get("response_family", "gaussian")).strip().lower()

    if fam in ("gaussian", ""):
        return []

    lines: List[str] = []
    lines.append("## Response distribution guidance")

    # brms family() call for Bayesian
    _BRMS_FAMILY = {
        "student": "student()",
        "lognormal": "lognormal()",
        "gamma": 'Gamma(link = "log")',
        "skew_normal": "skew_normal()",
        "exgaussian": "exgaussian()",
        "bernoulli": "bernoulli()",
        "bernoulli_probit": 'bernoulli(link = "probit")',
        "poisson": "poisson()",
        "negbinomial": "negbinomial()",
        "zero_inflated_poisson": "zero_inflated_poisson()",
        "zero_inflated_negbinomial": "zero_inflated_negbinomial()",
        "hurdle_poisson": "hurdle_poisson()",
        "hurdle_negbinomial": "hurdle_negbinomial()",
        "cumulative": 'cumulative(link = "logit")',
        "sratio": 'sratio(link = "logit")',
        "cratio": 'cratio(link = "logit")',
        "acat": 'acat(link = "logit")',
        "beta": "Beta()",
        "zero_one_inflated_beta": "zero_one_inflated_beta()",
        "weibull": "weibull()",
        "cox": "cox()",
    }

    # Frequentist R family
    _FREQ_FAMILY = {
        "gaussian": "gaussian()",
        "gamma": 'Gamma(link = "log")',
        "bernoulli": "binomial()",
        "bernoulli_probit": 'binomial(link = "probit")',
        "poisson": "poisson()",
        "negbinomial": "MASS::glm.nb()",
        "cumulative": "MASS::polr() or ordinal::clm()",
    }

    if prob == "bayesian":
        brms_call = _BRMS_FAMILY.get(fam, fam)
        lines.append(f"- Use `family = {brms_call}` in `brm()`.")
    else:
        freq_call = _FREQ_FAMILY.get(fam)
        if freq_call:
            lines.append(f"- Use `family = {freq_call}` in `glm()` / `glmer()`.")

    # Family-specific interpretation notes
    _INTERP_NOTES: dict[str, str] = {
        "student": (
            "- The Student-t family estimates a degrees-of-freedom parameter (ν). "
            "Report ν in the interpretation — small values indicate heavy tails."
        ),
        "lognormal": (
            "- Coefficients are on the log scale. Report exp(β) as multiplicative "
            "effects. brms generates posterior predictions on the original scale."
        ),
        "gamma": (
            "- Uses a log link by default. Coefficients are on the log scale; "
            "exp(β) gives multiplicative effects on the mean."
        ),
        "skew_normal": (
            "- Report the estimated skewness parameter (α). If α ≈ 0, the "
            "distribution collapses to Gaussian, suggesting skew was unnecessary."
        ),
        "exgaussian": (
            "- Report both the Gaussian (μ, σ) and exponential (β) components. "
            "The exponential component captures the right tail typical of "
            "reaction-time distributions."
        ),
        "bernoulli": (
            "- Coefficients are log-odds. Report odds ratios: exp(β). "
            "Provide predicted probabilities for interpretability."
        ),
        "bernoulli_probit": (
            "- Coefficients represent changes in Φ⁻¹(p). Marginal effects "
            "or predicted probabilities are more interpretable than raw coefficients."
        ),
        "poisson": (
            "- Uses a log link. Coefficients are log incidence-rate ratios: "
            "exp(β) gives the rate ratio. Check for overdispersion."
        ),
        "negbinomial": (
            "- Uses a log link. Report incidence-rate ratios: exp(β). "
            "Also report the dispersion parameter (shape/size)."
        ),
        "zero_inflated_poisson": (
            "- Two components: (1) zero-inflation probability (zi), (2) Poisson "
            "count process. Report both sets of coefficients and explain which "
            "predictors affect each component."
        ),
        "zero_inflated_negbinomial": (
            "- Two components: (1) zero-inflation probability (zi), (2) negative "
            "binomial count process. Report both plus the dispersion parameter."
        ),
        "hurdle_poisson": (
            "- Two components: (1) binary hurdle (zero vs positive), (2) truncated "
            "Poisson for positive counts. All zeros come from the hurdle process."
        ),
        "hurdle_negbinomial": (
            "- Two components: (1) binary hurdle, (2) truncated negative binomial "
            "for positive counts. Report both plus the dispersion parameter."
        ),
        "cumulative": (
            "- Report threshold parameters (αₖ) and regression coefficients (β). "
            "exp(β) gives cumulative odds ratios under the proportional-odds assumption. "
            "Check the proportional-odds assumption (e.g. Brant test or visual check)."
        ),
        "beta": (
            "- Uses a logit link. Coefficients are on the log-odds scale for the mean. "
            "Report the precision parameter (φ) — higher φ means less variance."
        ),
        "zero_one_inflated_beta": (
            "- Three components: P(Y=0), P(Y=1), and a Beta distribution for (0,1). "
            "Report all three sets of parameters."
        ),
        "weibull": (
            "- Report the shape parameter. Shape > 1 means increasing hazard "
            "(risk rises over time); shape < 1 means decreasing hazard."
        ),
    }

    note = _INTERP_NOTES.get(fam)
    if note:
        lines.append(note)

    lines.append("")
    return lines


# ============================================================
# Public API
# ============================================================

def _group_comparison_prompt(spec: AnalysisSpec, prob: str) -> List[str]:
    """Build prompt section for group comparison analysis."""
    comp = (spec.notes or {}).get("comparison", {})
    design = comp.get("design", "independent")
    parametric = comp.get("parametric", True)
    direction = comp.get("test_direction", "two_sided")
    effect_size = comp.get("effect_size", "cohens_d")
    r_hint = comp.get("r_code_hint", "")

    lines: List[str] = []
    lines.append("## Group comparison analysis")
    lines.append("")

    # Design description
    if design == "independent":
        lines.append("### Design: independent groups (between-subjects)")
        lines.append(
            "Two separate groups are compared. Observations in one group "
            "are unrelated to observations in the other."
        )
    else:
        pairing_var = comp.get("pairing_var", "subject")
        lines.append("### Design: paired / dependent (within-subjects)")
        lines.append(
            f"The same units (paired by `{pairing_var}`) are measured under "
            f"two conditions. Use paired methods throughout."
        )
    lines.append("")

    # Test specification
    if parametric:
        test_name = "Welch's t-test" if design == "independent" else "paired t-test"
    else:
        test_name = "Mann-Whitney U test" if design == "independent" else "Wilcoxon signed-rank test"
    lines.append(f"### Test: {test_name}")
    lines.append(f"- Direction: {direction.replace('_', '-')}")
    if r_hint:
        lines.append(f"- R code: `{r_hint}`")
    lines.append("")

    # Effect size
    _es_labels = {
        "cohens_d": "Cohen's d",
        "hedges_g": "Hedges' g (bias-corrected)",
        "glasss_delta": "Glass's Δ (control-group SD)",
        "rank_biserial": "rank-biserial correlation",
    }
    lines.append(f"### Effect size: {_es_labels.get(effect_size, effect_size)}")
    lines.append(
        "- Always report the effect size with its confidence/credible interval."
    )
    lines.append(
        "- Do not rely solely on p-values or Bayes factors to judge the "
        "practical importance of the difference."
    )
    lines.append("")

    # Bayesian specifics
    if prob == "bayesian":
        bayes_method = comp.get("bayes_method", "bayes_factor")
        lines.append("### Bayesian analysis")
        if bayes_method == "bayes_factor":
            lines.append(
                "- Use `BayesFactor::ttestBF()` with the default Cauchy prior "
                "(r = √2/2) on the standardised effect size."
            )
            lines.append(
                "- Report BF₁₀ and interpret using Jeffreys' (1961) thresholds: "
                "1–3 anecdotal, 3–10 moderate, 10–30 strong, > 30 very strong."
            )
            lines.append(
                "- State the prior distribution used and note sensitivity to "
                "the prior scale (r parameter)."
            )
        elif bayes_method == "rope_estimation":
            rope_w = comp.get("rope_width", 0.1)
            lines.append(
                f"- Define a ROPE of [{-rope_w}, {rope_w}] in standardised "
                f"effect-size units."
            )
            lines.append(
                "- Report the percentage of the posterior inside the ROPE, "
                "below the ROPE, and above the ROPE."
            )
            lines.append(
                "- If > 95% of the posterior falls inside the ROPE, conclude "
                "practical equivalence (Kruschke, 2018)."
            )
        elif bayes_method == "brms_model":
            lines.append(
                "- Fit the comparison as a brms model and report the full "
                "posterior distribution for the group difference."
            )
            lines.append(
                "- Report the posterior mean/median, 95% credible interval, "
                "and probability of direction (pd)."
            )
        lines.append("")

    # Output requirements
    lines.append("## Output requirements (MUST produce these files)")
    lines.append(
        "1) test_results.csv: one row per test; include columns: "
        "test_name, statistic, df, "
        + ("bf10, bf01, " if prob == "bayesian" else "p_value, ")
        + f"effect_size_type, effect_size, es_lower, es_upper, "
        f"n_group1, n_group2."
    )
    lines.append(
        "2) descriptive_stats.csv: one row per group; include columns: "
        "group, n, mean, sd, median, min, max."
    )
    lines.append(
        "3) diagnostics.json: include key assumption checks "
        "(normality test per group: Shapiro-Wilk W and p; "
        "equality of variance: Levene/Brown-Forsythe F and p; "
        "outlier notes if any)."
    )
    lines.append(
        "4) interpretation.txt: your interpretation in plain language, "
        "constrained by the prohibitions below. "
        "Include: sample sizes, descriptive stats, test result, "
        f"{'Bayes factor or posterior summary' if prob == 'bayesian' else 'exact p-value'}, "
        f"effect size ({_es_labels.get(effect_size, effect_size)}) with interval, "
        "and assumption-check results."
    )
    lines.append("")

    # Reporting checklist
    lines.append("### Reporting checklist (all items must appear in interpretation.txt)")
    lines.append("1. State the sample size per group.")
    lines.append("2. Report descriptive statistics (mean, SD) per group.")
    lines.append("3. Report the test statistic and its degrees of freedom.")
    if prob == "bayesian":
        lines.append("4. Report the Bayes factor or posterior summary (not p-values).")
    else:
        lines.append("4. Report the exact p-value (not 'p < 0.05').")
    lines.append(f"5. Report {_es_labels.get(effect_size, effect_size)} with its 95% interval.")
    lines.append("6. Check and report assumption violations (normality, equal variance).")
    if not parametric:
        lines.append("7. Note that the non-parametric test does not assume normality.")
    lines.append("")

    return lines


def _correlation_prompt(spec: AnalysisSpec, prob: str) -> List[str]:
    """Build prompt section for correlation analysis."""
    corr = (spec.notes or {}).get("correlation", {})
    method = corr.get("method", "pearson")
    variables = corr.get("variables", [])
    partial = corr.get("partial", False)
    partial_vars = corr.get("partial_vars", [])
    r_hint = corr.get("r_code_hint", "")

    lines: List[str] = []
    lines.append("## Correlation analysis")
    lines.append("")

    # Method
    _method_names = {
        "pearson": "Pearson product-moment correlation (r)",
        "spearman": "Spearman rank correlation (ρ)",
        "kendall": "Kendall rank correlation (τ)",
    }
    lines.append(f"### Method: {_method_names.get(method, method)}")

    if method == "pearson":
        lines.append(
            "- Measures linear association. Sensitive to outliers. "
            "Inference assumes bivariate normality."
        )
    elif method == "spearman":
        lines.append(
            "- Measures monotonic association using ranks. Robust to "
            "outliers and non-normality."
        )
    else:
        lines.append(
            "- Measures monotonic association using concordant/discordant "
            "pairs. More robust than Spearman for small samples."
        )

    if r_hint:
        lines.append(f"- R code: `{r_hint}`")
    lines.append("")

    # Partial correlation
    if partial and partial_vars:
        lines.append(f"### Partial correlation (controlling for: {', '.join(partial_vars)})")
        lines.append(
            "- The partial correlation removes the linear effect of the "
            "control variables from both the outcome and the predictor "
            "before computing the correlation."
        )
        lines.append(f"- R: `ppcor::pcor.test(df${spec.outcome}, df$VAR, df[,c({','.join(repr(v) for v in partial_vars)})])`")
        lines.append("")

    # Variables
    lines.append(f"### Variables to correlate with `{spec.outcome}`:")
    for v in variables:
        lines.append(f"- `{v}`")
    lines.append("")

    # Bayesian
    if prob == "bayesian":
        bayes_method = corr.get("bayes_method", "posterior_estimation")
        lines.append("### Bayesian analysis")
        if bayes_method == "bayes_factor":
            lines.append(
                "- Use `BayesFactor::correlationBF()` to quantify evidence "
                "for ρ ≠ 0 vs ρ = 0."
            )
            lines.append(
                "- Report BF₁₀ with Jeffreys' (1961) interpretation thresholds."
            )
        else:
            lines.append(
                "- Report the full posterior distribution for ρ, including "
                "the posterior mean/median and 95% credible interval."
            )
        lines.append("")

    # Output requirements
    lines.append("## Output requirements (MUST produce these files)")
    _var_list = ", ".join(f"`{v}`" for v in variables) if variables else "`<predictor>`"
    lines.append(
        "1) correlation_results.csv: one row per variable pair; include columns: "
        "var1, var2, method, coefficient, "
        + ("bf10, " if prob == "bayesian" else "p_value, ")
        + "ci_lower, ci_upper, "
        + ("interval_type (CrI), " if prob == "bayesian" else "interval_type (CI), ")
        + "r_squared, n_pairs"
        + (", partial_vars" if partial else "")
        + "."
    )
    lines.append(
        "2) diagnostics.json: include key checks "
        "(scatterplot summary per pair; outlier notes if any; "
        "normality assessment if Pearson)."
    )
    lines.append(
        "3) interpretation.txt: your interpretation in plain language, "
        "constrained by the prohibitions below. "
        "Include: N, correlation coefficient, "
        f"{'Bayes factor or credible interval' if prob == 'bayesian' else '95% CI and exact p-value'}, "
        "R² for Pearson r, and an explicit statement that correlation "
        "does not imply causation."
    )
    lines.append("")

    # Reporting checklist
    lines.append("### Reporting checklist (all items must appear in interpretation.txt)")
    lines.append("1. Report N (the number of complete pairs).")
    lines.append(f"2. Report the correlation coefficient ({method} r/ρ/τ).")
    if prob == "bayesian":
        lines.append("3. Report the Bayes factor or posterior credible interval.")
    else:
        lines.append("3. Report the exact p-value and 95% confidence interval.")
    lines.append("4. Report R² (proportion of shared variance) for Pearson r.")
    lines.append("5. Include a scatterplot if possible.")
    lines.append(
        "6. Do NOT claim causation from a correlation. State the direction "
        "and strength of the association only."
    )
    if partial:
        lines.append(
            "7. Clearly state which variables were controlled for and "
            "why they were chosen as covariates."
        )
    lines.append("")

    return lines


def julius_prompt_from_spec(spec: AnalysisSpec) -> str:
    """Build a complete prompt for an LLM statistical assistant.

    The prompt is framework-aware: frequentist, Bayesian (with aim fork),
    or hybrid.  Bayesian mode enforces strict prohibitions against
    frequentist contamination (AIC/BIC, CI language).

    Supports three analysis types:
    - regression (default): full modelling workflow
    - group_comparison: t-test / Wilcoxon / Bayesian difference test
    - correlation: Pearson / Spearman / Kendall / partial
    """
    fw = (spec.notes or {}).get("framework", {})
    prob = str(fw.get("probability", "frequentist")).strip().lower()
    analysis_type = str((spec.notes or {}).get("analysis_type", "regression")).strip().lower()

    parts: List[str] = []

    # 1. Common header (always)
    parts.extend(_common_header(spec, prob))

    if analysis_type == "group_comparison":
        # Group comparison flow
        parts.extend(_group_comparison_prompt(spec, prob))

        # Philosophy guidance + prohibitions still apply
        parts.extend(_philosophy_guidance(spec))
        parts.extend(_prohibitions_and_required(spec))

    elif analysis_type == "correlation":
        # Correlation flow
        parts.extend(_correlation_prompt(spec, prob))

        # Philosophy guidance + prohibitions still apply
        parts.extend(_philosophy_guidance(spec))
        parts.extend(_prohibitions_and_required(spec))

    else:
        # Regression / modelling flow (default)
        parts.extend(_models_section(spec))
        parts.extend(_transformation_section(spec))
        parts.extend(_distribution_guidance(spec, prob))

        if prob == "bayesian":
            parts.extend(_bayesian_prompt(spec))
        elif prob == "hybrid":
            parts.extend(_hybrid_prompt(spec))
        else:
            parts.extend(_frequentist_prompt(spec))

        parts.extend(_philosophy_guidance(spec))
        parts.extend(_prohibitions_and_required(spec))

    return "\n".join(parts)
