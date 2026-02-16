# statsrag verification report — run `GTP_5.2`

## Spec summary
- Objective: prediction
- Outcome: `vo2_l_min`
- Outcome transformation: log (natural logarithm)
- Candidate models in spec: 3
- Validation: kfold_cv (metric: rmse_log, seed: 20260203)
- Information criterion (as chosen in spec): AIC
- Probability framework: frequentist

### Model definitions
| Model | Formula |
| --- | --- |
| Model 1 | `log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2` |
| Model 2 | `log(vo2_l_min) ~ LnFFFkg + bodyfat + Sex + Age2` |
| Model 3 | `log(vo2_l_min) ~ LnFFFkg + Sex + Age2` |

## Artefact checks
- model_comparison.csv present: YES
- model_coefficients.csv present: YES
- diagnostics.json present: YES
- interpretation.txt present: YES

## Ground truth summary (auto-generated)
Computed directly from **model_comparison.csv** (not from the LLM).

| Criterion | Best model | Formula | Value |
| --- | --- | --- | --- |
| AIC | Model 1 | `log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2` | -2079 |
| BIC | Model 1 | `log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2` | -2048 |
| RMSE_LOG | Model 1 | `log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2` | 0.1858 |
| RMSE_RAW | Model 1 | `log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2` | 0.4924 |
| MAE | Model 1 | `log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2` | 0.375 |
| R2 | Model 1 | `log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2` | 0.7324 |

## Major issues detected
### Frequentist-specific
- **PROBLEM:** Confidence interval misinterpretation: a 95% CI is not a 95% probability statement about the parameter.

## Transformation notes
*Informational advisories — not errors.*

- **Log-transform rationale:** A log transformation of the outcome is often appropriate when the outcome is strictly positive and the residual variance scales with the mean (multiplicative errors). For body-size/performance data this is common because biological scaling relationships are typically allometric (power-law), and log-linearisation converts them to additive models suitable for OLS or mixed-effects regression.
- **Back-transformation caution:** Coefficients fitted on the log scale describe proportional (multiplicative) rather than absolute changes. Exponentiating a log-scale coefficient gives a ratio (e.g. exp(b) ≈ 1.05 means a ≈5 % increase per unit change in X). However, back-transforming predictions requires care: exp(E[log Y]) ≠ E[Y] due to Jensen's inequality. If absolute-scale predictions are needed, apply a smearing estimate (Duan, 1983) or half-variance correction (exp(μ + σ²/2)) to avoid systematic under-prediction. Report whether results are presented on the log scale or the original scale, and which correction (if any) was used.
- **Alternative transformations:** While the current spec uses a standard log (λ = 0 in the Box-Cox family), other transformations may be worth considering. A Box-Cox profile-likelihood search over λ can identify whether a different power transformation better stabilises variance and normalises residuals. However, Box-Cox does not guarantee that assumptions are met — it seeks to improve them — and the chosen λ should be checked empirically via residual diagnostics.

## Claim-by-claim evidence (local RAG)
This section retrieves evidence for each claim separately.

## Claim 1: Predictive target (estimand)

### Retrieved chunks
- score=0.411 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=111
- score=0.346 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=115
- score=0.221 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=142
- score=0.205 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=93

## Claim 2: The predictive target is vo2_l_min for a new individual with observed predictors…

### Retrieved chunks
- score=0.278 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=111
- score=0.236 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=115
- score=0.174 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=615
- score=0.168 source=Domain_specific_modelling/Nevill_holder_(1995)_Scaling_normalizing_and_per_ratio_standards__an_allometric_modeling_approach.pdf chunk=8

## Claim 3: Model comparison and validation

### Retrieved chunks
- score=0.334 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=7
- score=0.276 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=506
- score=0.267 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=379
- score=0.266 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=514

## Claim 4: All candidate models were fitted on the same analytic rows (complete cases acros…

### Retrieved chunks
- score=0.295 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=324
- score=0.277 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=304
- score=0.235 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=338
- score=0.227 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=103

## Claim 5: 10-fold cross-validation (k = 10, seed = 20260203) was used to estimate out-of-s…

### Retrieved chunks
- score=0.436 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=506
- score=0.376 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=120
- score=0.366 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=507
- score=0.362 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=336

## Claim 6: Primary metric: RMSE on the log scale (rmse_log). Best model by rmse_log was Mod…

### Retrieved chunks
- score=0.246 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=659
- score=0.228 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=141
- score=0.214 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=369
- score=0.207 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=225

## Claim 7: Model 1 rmse_log = 0.185810, rmse_raw = 0.492365, MAE_raw = 0.374957, R²_log = 0…

### Retrieved chunks
- score=0.314 source=Prediction_modelling_workflow/TRIPODAI-Supplement.pdf chunk=20
- score=0.308 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=46
- score=0.308 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=236
- score=0.300 source=Prediction_modelling_workflow/TRIPODAI-Supplement.pdf chunk=27

## Claim 8: AIC = -2079.403, BIC = -2048.021 (lower is better, for these fitted models on th…

### Retrieved chunks
- score=0.285 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=375
- score=0.260 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=333
- score=0.202 source=Interpretation_guardrails/Shmueli__(2010)__To_Explain_or_to_Predict__doi10.1214__10-sts330.pdf chunk=37
- score=0.197 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=373

## Claim 9: Best model (frequentist OLS on log outcome)

### Retrieved chunks
- score=0.205 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=369
- score=0.190 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=364
- score=0.186 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=506
- score=0.156 source=Modelling_practice_and_diagnostics/Snijders__Berkhof_(2007)_Diagnostic Checks for Multilevel Models.pdf chunk=22

## Claim 10: Model 1 formula: log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2.

### Retrieved chunks
- score=0.285 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=236
- score=0.232 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=54
- score=0.231 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=351
- score=0.194 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=362

## Claim 11: Interpretation of coefficients is on a multiplicative (percentage) scale for vo2…

### Retrieved chunks
- score=0.138 source=Prediction_modelling_workflow/TRIPODAI-Supplement.pdf chunk=4
- score=0.121 source=Prediction_modelling_workflow/TRIPODAI-Supplement.pdf chunk=5
- score=0.113 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=18
- score=0.111 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=356

## Claim 12: Effect sizes (with 95% confidence intervals; no causal interpretation implied)

### Retrieved chunks
- score=0.276 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=10
- score=0.265 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=24
- score=0.228 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=23
- score=0.187 source=Interpretation_guardrails/Shmueli__(2010)__To_Explain_or_to_Predict__doi10.1214__10-sts330.pdf chunk=3

## Claim 13: Lnmasskg: multiplicative factor per +1 unit = 1.8896 (95% CI 1.8131 to 1.9693), …

### Retrieved chunks
- score=0.246 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=449
- score=0.222 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=563
- score=0.176 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=562
- score=0.174 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=185

## Claim 14: bodyfat: multiplicative factor per +1 unit = 0.9877 (95% CI 0.9868 to 0.9886), e…

### Retrieved chunks
- score=0.283 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=449
- score=0.278 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=563
- score=0.219 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=562
- score=0.193 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=228

## Claim 15: Age2: multiplicative factor per +1 unit = 0.9999 (95% CI 0.9999 to 0.9999), equi…

### Retrieved chunks
- score=0.248 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=188
- score=0.201 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=187
- score=0.179 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=128
- score=0.147 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=449

## Claim 16: C(Sex)[T.Male]: multiplicative factor relative to the reference Sex category = 1…

### Retrieved chunks
- score=0.294 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=236
- score=0.270 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=54
- score=0.239 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=397
- score=0.223 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=362

## Claim 17: What a 95% confidence interval means (repeated sampling interpretation)

### Retrieved chunks
- score=0.278 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=25
- score=0.259 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=107
- score=0.252 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=23
- score=0.223 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=140

## Claim 18: If the same sampling and modelling procedure were repeated many times on new sam…

### Retrieved chunks
- score=0.206 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=24
- score=0.205 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=25
- score=0.198 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=109
- score=0.198 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=582

## Claim 19: It is not a 95% probability statement about the parameter for this single fitted…

### Retrieved chunks
- score=0.191 source=Interpretation_guardrails/Wasserstein_et_al__(2016)__The_ASA_Statement_on_p-Values_Context_Process_and_Purpose__doi10.1080_00031305.2016.1154108.pdf chunk=2
- score=0.169 source=Interpretation_guardrails/Wasserstein_et_al__(2016)__The_ASA_Statement_on_p-Values_Context_Process_and_Purpose__doi10.1080_00031305.2016.1154108.pdf chunk=4
- score=0.168 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=605
- score=0.167 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=390

## Claim 20: Model assumptions and limitations

### Retrieved chunks
- score=0.259 source=Prediction_modelling_workflow/TRIPODAI-Supplement.pdf chunk=23
- score=0.241 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=737
- score=0.215 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=7
- score=0.196 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=4

## Claim 21: Linearity on the log scale: the expected log(vo2_l_min) is a linear function of …

### Retrieved chunks
- score=0.275 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=373
- score=0.244 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=607
- score=0.243 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=265
- score=0.237 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=609

## Claim 22: Independent errors and correct specification: residuals are assumed independent …

### Retrieved chunks
- score=0.146 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=151
- score=0.144 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=705
- score=0.125 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=348
- score=0.123 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=425

## Claim 23: Approximate normality and constant variance of residuals on the log scale are as…

### Retrieved chunks
- score=0.212 source=Modelling_practice_and_diagnostics/Snijders__Berkhof_(2007)_Diagnostic Checks for Multilevel Models.pdf chunk=29
- score=0.163 source=Modelling_practice_and_diagnostics/Harrell_(2015)_Regression_Modeling_Strategies_ With_Applications_to_Linear _Models.pdf chunk=396
- score=0.151 source=Modelling_practice_and_diagnostics/Snijders__Berkhof_(2007)_Diagnostic Checks for Multilevel Models.pdf chunk=30
- score=0.145 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=151

## Claim 24: Predictive performance is estimated via 10-fold CV within this dataset; performa…

### Retrieved chunks
- score=0.286 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=332
- score=0.231 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=349
- score=0.212 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=333
- score=0.186 source=Prediction_modelling_workflow/James_Witten_Hastie_Tibshirani_(2021)_An_Introduction_to_Statistical_Learning__with_Applications_in_R.pdf chunk=335

## Claim 25: Associations described above should not be interpreted as causal effects because…

### Retrieved chunks
- score=0.262 source=Interpretation_guardrails/Shmueli__(2010)__To_Explain_or_to_Predict__doi10.1214__10-sts330.pdf chunk=3
- score=0.247 source=Interpretation_guardrails/Shmueli__(2010)__To_Explain_or_to_Predict__doi10.1214__10-sts330.pdf chunk=28
- score=0.210 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=197
- score=0.193 source=Interpretation_guardrails/Shmueli__(2010)__To_Explain_or_to_Predict__doi10.1214__10-sts330.pdf chunk=5

## Model comparison snapshot (all rows)

| model_id | formula | aic | bic | rmse_log | rmse_raw | mae | r2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2 | -2079.40283033757 | -2048.020856813253 | 0.185809704333829 | 0.4923647580027326 | 0.3749574784884342 | 0.7323900041923233 |
| 3 | log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + ageattesty | -2027.4040069646244 | -1996.022033440308 | 0.1870259012883779 | 0.4976729165481144 | 0.3788033007146367 | 0.7288753157047811 |
| 2 | log(vo2_l_min) ~ LnFFFkg + Sex + Age2 | -1988.626438005841 | -1963.520859186388 | 0.1879273832359887 | 0.5007880884093561 | 0.3817606969869271 | 0.7262553250436787 |

## Coefficients snapshot (first 20 rows)

| term | estimate | se | lower | upper | scale | interval_type | model_id |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Intercept | -1.4073450646328622 | 0.0807561283297755 | -1.5656729915183156 | -1.2490171377474089 | log | CI | 1 |
| C(Sex)[T.Male] | 0.2348359234320501 | 0.0101730556156839 | 0.2148909503503256 | 0.2547808965137746 | log | CI | 1 |
| Lnmasskg | 0.6363622330036033 | 0.0210785348502186 | 0.5950363201144956 | 0.677688145892711 | log | CI | 1 |
| bodyfat | -0.0123617134601101 | 0.0004530904144977 | -0.0132500282852855 | -0.0114733986349347 | log | CI | 1 |
| Age2 | -9.83824605564839e-05 | 2.1212180360565576e-06 | -0.000102541253964 | -9.422366714888764e-05 | log | CI | 1 |
| Intercept | 0.2447923289966692 | 0.0807561283297755 | 0.2089473460530344 | 0.2867865300399841 | raw | CI | 1 |
| C(Sex)[T.Male] | 1.2647012438687977 | 0.0101730556156839 | 1.2397266978323962 | 1.2901789072058227 | raw | CI | 1 |
| Lnmasskg | 1.8895944569471077 | 0.0210785348502186 | 1.8130967956475064 | 1.9693196856873196 | raw | CI | 1 |
| bodyfat | 0.9877143786540268 | 0.0004530904144977 | 0.9868373669173642 | 0.9885921697993456 | raw | CI | 1 |
| Age2 | 0.9999016223788392 | 2.1212180360565576e-06 | 0.9998974640032106 | 0.9999057807717614 | raw | CI | 1 |

## Diagnostics summary (as provided)
```json
{
  "data": {
    "rows_total_in_file": 3930,
    "rows_used_complete_cases_all_models": 3930,
    "rows_dropped_nonpositive_outcome_for_log": 0,
    "rows_dropped_missing_any_model_variable": 0,
    "outcome_transformation": "log(vo2_l_min)"
  },
  "best_model": {
    "model_id": 1,
    "formula": "log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2",
    "assumed_error_structure": "Gaussian errors on log-scale outcome (OLS on log(vo2_l_min))"
  },
  "residual_checks_summary": {
    "normality_jarque_bera": {
      "statistic": 243.23798974465396,
      "p_value": 1.5189435439869967e-53,
      "note": "Low p-values suggest residuals deviate from normality; with large n, small departures can be detected."
    },
    "heteroskedasticity_breusch_pagan": {
      "lm_statistic": 29.739475815214757,
      "lm_p_value": 5.529993664094714e-06,
      "f_statistic": 7.482028562637834,
      "f_p_value": 5.319805459925588e-06,
      "note": "Low p-values suggest non-constant variance on the log scale."
    },
    "abs_residual_fitted_correlation": {
      "corr": -0.02116860475225359,
      "note": "Positive correlation between |residual| and fitted values can indicate heteroskedasticity."
    }
  },
  "influence_outliers": {
    "checked": true,
    "cooks_distance_threshold_4_over_n": 0.0010178117048346056,
    "n_above_threshold": 210,
    "max_cooks_distance": 0.0144866673009542,
    "note": "Cook's distance is a heuristic for influential observations; investigate points above threshold."
  }
}
```

## RAG retrieval (top matches, whole document)
- score=0.192 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=25
- score=0.187 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=24
- score=0.182 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=449
- score=0.176 source=Prediction_modelling_workflow/Kuhn_Johnson_Kjell_(2018)_Applied_Predictive_Modeling.pdf chunk=563
- score=0.174 source=Interpretation_guardrails/Greenland__Poole__Senn__Goodman__Rothman__Altman_(2016)_Statistical_tests_P values,_confidence_intervals,_and_power_a guide to misinterpretations_doi10.1007__s10654-016-0149-3.pdf chunk=23
- score=0.170 source=Prediction_modelling_workflow/Steyerberg -(2019)_Clinical Prediction Models_ A Practical Approach to Development, Validation, and Updating.pdf chunk=185

## Full LLM interpretation (as uploaded)
```
Predictive target (estimand)
- The predictive target is vo2_l_min for a new individual with observed predictors, using a linear model for log(vo2_l_min).

Model comparison and validation
- All candidate models were fitted on the same analytic rows (complete cases across vo2_l_min and all predictors used by any candidate model): n = 3930.
- 10-fold cross-validation (k = 10, seed = 20260203) was used to estimate out-of-sample predictive error.
- Primary metric: RMSE on the log scale (rmse_log). Best model by rmse_log was Model 1.
  • Model 1 rmse_log = 0.185810, rmse_raw = 0.492365, MAE_raw = 0.374957, R²_log = 0.732390.
  • AIC = -2079.403, BIC = -2048.021 (lower is better, for these fitted models on the same data).

Best model (frequentist OLS on log outcome)
- Model 1 formula: log(vo2_l_min) ~ Lnmasskg + bodyfat + Sex + Age2.
- Interpretation of coefficients is on a multiplicative (percentage) scale for vo2_l_min because the outcome is logged.

Effect sizes (with 95% confidence intervals; no causal interpretation implied)
- Lnmasskg: multiplicative factor per +1 unit = 1.8896 (95% CI 1.8131 to 1.9693), equivalent to 88.96% change (CI 81.31% to 96.93%).
- bodyfat: multiplicative factor per +1 unit = 0.9877 (95% CI 0.9868 to 0.9886), equivalent to -1.23% change (CI -1.32% to -1.14%).
- Age2: multiplicative factor per +1 unit = 0.9999 (95% CI 0.9999 to 0.9999), equivalent to -0.01% change (CI -0.01% to -0.01%).
- C(Sex)[T.Male]: multiplicative factor relative to the reference Sex category = 1.2647 (95% CI 1.2397 to 1.2902).

What a 95% confidence interval means (repeated sampling interpretation)
- If the same sampling and modelling procedure were repeated many times on new samples from the same data-generating process, then 95% of the intervals constructed in this way would contain the true parameter value. It is not a 95% probability statement about the parameter for this single fitted model.

Model assumptions and limitations
- Linearity on the log scale: the expected log(vo2_l_min) is a linear function of the included predictors.
- Independent errors and correct specification: residuals are assumed independent with mean zero; omitted variables and measurement error can reduce predictive performance and distort coefficient interpretations.
- Approximate normality and constant variance of residuals on the log scale are assumed for standard errors and confidence intervals; diagnostics in diagnostics.json summarise checks.
- Predictive performance is estimated via 10-fold CV within this dataset; performance may differ in external populations or under dataset shift.
- Associations described above should not be interpreted as causal effects because no causal identification strategy has been specified.
```
