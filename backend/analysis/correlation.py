"""
correlation.py — Exploratory correlation analysis & multicollinearity checks.
"""

import logging
from typing import Dict, Any, List

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

PREDICTOR_COLS = [
    "sst", "wind_speed", "wind_direction",
    "wave_height", "ocean_current_velocity", "month",
]

VIF_THRESHOLD = 5.0


def _get_available_predictors(df: pd.DataFrame) -> List[str]:
    return [col for col in PREDICTOR_COLS if col in df.columns
            and df[col].notna().sum() > 2]


def compute_correlations(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute Pearson and Spearman correlation matrices between species
    presence and all environmental predictor variables.
    """
    predictors = _get_available_predictors(df)

    if not predictors:
        raise ValueError("No valid predictor columns found in DataFrame")

    analysis_cols = ["presence"] + predictors
    analysis_df = df[analysis_cols].dropna()

    if len(analysis_df) < 5:
        raise ValueError(
            f"Insufficient data for correlation: only {len(analysis_df)} rows"
        )

    result = {}

    for method_name in ("pearson", "spearman"):
        corr_matrix = analysis_df.corr(method=method_name)
        matrix_dict = {}
        for col in corr_matrix.columns:
            matrix_dict[col] = {
                row: round(corr_matrix.loc[row, col], 4)
                for row in corr_matrix.index
            }

        with_presence = {}
        for pred in predictors:
            x = analysis_df["presence"].values
            y = analysis_df[pred].values

            if method_name == "pearson":
                corr, p_val = stats.pearsonr(x, y)
            else:
                corr, p_val = stats.spearmanr(x, y)

            with_presence[pred] = {
                "correlation": round(float(corr), 4),
                "p_value": round(float(p_val), 6),
                "significant": bool(p_val < 0.05),
            }

        result[method_name] = {
            "matrix": matrix_dict,
            "with_presence": with_presence,
        }

    logger.info("Computed correlations for %d predictors", len(predictors))
    return result


def compute_vif(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute Variance Inflation Factor (VIF) for each environmental predictor.
    VIF > 5 indicates problematic multicollinearity.
    """
    predictors = _get_available_predictors(df)

    if len(predictors) < 2:
        return {
            "scores": [],
            "has_collinearity": False,
            "message": "Need at least 2 predictors for VIF analysis",
        }

    analysis_df = df[predictors].dropna()

    if len(analysis_df) < len(predictors) + 1:
        return {
            "scores": [],
            "has_collinearity": False,
            "message": "Insufficient data rows for VIF computation",
        }

    scores = []
    has_collinearity = False

    for col in predictors:
        others = [p for p in predictors if p != col]
        y = analysis_df[col].values
        X = analysis_df[others].values
        X_with_const = np.column_stack([np.ones(len(X)), X])

        try:
            coeffs, _, _, _ = np.linalg.lstsq(X_with_const, y, rcond=None)
            y_pred = X_with_const @ coeffs
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)

            if ss_tot == 0:
                vif = 1.0
            else:
                r_squared = min(1 - (ss_res / ss_tot), 0.9999)
                vif = 1.0 / (1.0 - r_squared)
        except np.linalg.LinAlgError:
            vif = float("inf")

        warning = None
        if vif > VIF_THRESHOLD:
            has_collinearity = True
            severity = "severe" if vif > 10 else "moderate"
            warning = f"{col}: VIF={vif:.1f} — {severity} collinearity detected"

        scores.append({
            "variable": col,
            "vif": round(float(vif), 2),
            "warning": warning,
        })

    logger.info("VIF computed: collinearity=%s", has_collinearity)
    return {
        "scores": scores,
        "has_collinearity": has_collinearity,
    }
