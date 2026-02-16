from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class Transformations(BaseModel):
    log_outcome: bool = False
    log_predictors: List[str] = Field(default_factory=list)
    no_transform: List[str] = Field(default_factory=list)

class Validation(BaseModel):
    method: str = "kfold_cv"  # kfold_cv | bootstrap | psis_loo | none
    k: Optional[int] = 10
    seed: int = 20260203
    metric: str = "rmse_log"  # frequentist defaults; bayesian may use elpd_loo etc.

class AnalysisSpec(BaseModel):
    name: str = "analysis"
    objective: str = "prediction"  # prediction | explanation | both
    outcome: str
    predictors: List[str]
    candidate_models: List[str]  # R formulas (lm/glm/lmer/brms etc) as strings
    transformations: Transformations = Transformations()
    validation: Validation = Validation()
    information_criterion: str = "AIC"  # AIC/BIC/LOO/WAIC/none
    prohibitions: List[str] = Field(default_factory=list)
    required_reporting: List[str] = Field(default_factory=list)
    notes: Dict[str, Any] = Field(default_factory=dict)
