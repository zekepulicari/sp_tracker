"""
probability_model.py — Species Distribution Modeling (SDM).

Implements three modeling approaches:
  1. GLM (Logistic) — statsmodels Generalized Linear Model
  2. Random Forest  — scikit-learn ensemble classifier
  3. CCA            — Canonical Correspondence Analysis
"""

import logging
from typing import Dict, Any, Optional, List

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
import statsmodels.api as sm

logger = logging.getLogger(__name__)

PREDICTOR_COLS = [
    "sst", "wind_speed", "wind_direction",
    "wave_height", "ocean_current_velocity", "month",
]


def _get_available_predictors(df: pd.DataFrame) -> List[str]:
    return [col for col in PREDICTOR_COLS if col in df.columns
            and df[col].notna().sum() > 2]


def _prepare_data(df: pd.DataFrame, test_size: float = 0.2):
    predictors = _get_available_predictors(df)
    if not predictors:
        raise ValueError("No valid predictor columns available")

    clean_df = df[["presence"] + predictors].dropna()
    if len(clean_df) < 10:
        raise ValueError(f"Insufficient data for modeling: {len(clean_df)} rows")

    X = clean_df[predictors].values
    y = clean_df["presence"].values.astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y
    )
    return X_train, X_test, y_train, y_test, predictors


def fit_glm(df: pd.DataFrame) -> Dict[str, Any]:
    """Fit a Logistic GLM for encounter probability estimation."""
    X_train, X_test, y_train, y_test, predictors = _prepare_data(df)

    X_train_const = sm.add_constant(X_train)
    X_test_const = sm.add_constant(X_test)

    try:
        model = sm.GLM(y_train, X_train_const, family=sm.families.Binomial())
        result = model.fit()
    except Exception as exc:
        logger.error("GLM fitting failed: %s", exc)
        raise ValueError(f"GLM fitting failed: {exc}")

    y_pred_prob = result.predict(X_test_const)
    y_pred = (y_pred_prob >= 0.5).astype(int)

    accuracy = accuracy_score(y_test, y_pred)
    try:
        auc = roc_auc_score(y_test, y_pred_prob)
    except ValueError:
        auc = None

    param_names = ["intercept"] + predictors
    coefficients = {param_names[i]: round(float(result.params[i]), 4)
                    for i in range(len(param_names))}
    p_values = {param_names[i]: round(float(result.pvalues[i]), 6)
                for i in range(len(param_names))}

    mean_probability = round(float(np.mean(y_pred_prob)), 4)

    logger.info("GLM fitted: accuracy=%.3f", accuracy)
    return {
        "model_type": "GLM (Logistic)",
        "coefficients": coefficients,
        "p_values": p_values,
        "accuracy": round(float(accuracy), 4),
        "auc": round(float(auc), 4) if auc is not None else None,
        "mean_encounter_probability": mean_probability,
        "n_train": len(y_train),
        "n_test": len(y_test),
        "aic": round(float(result.aic), 2),
    }


def fit_random_forest(df: pd.DataFrame) -> Dict[str, Any]:
    """Fit a Random Forest classifier for Species Distribution Modeling."""
    X_train, X_test, y_train, y_test, predictors = _prepare_data(df)

    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42,
        oob_score=True,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)

    y_pred = rf.predict(X_test)
    y_pred_prob = rf.predict_proba(X_test)[:, 1]

    accuracy = accuracy_score(y_test, y_pred)
    try:
        auc = roc_auc_score(y_test, y_pred_prob)
    except ValueError:
        auc = None

    importance = {predictors[i]: round(float(rf.feature_importances_[i]), 4)
                  for i in range(len(predictors))}
    importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

    mean_probability = round(float(np.mean(y_pred_prob)), 4)

    logger.info("Random Forest fitted: accuracy=%.3f", accuracy)
    return {
        "model_type": "Random Forest",
        "variable_importance": importance,
        "accuracy": round(float(accuracy), 4),
        "auc": round(float(auc), 4) if auc is not None else None,
        "oob_score": round(float(rf.oob_score_), 4),
        "mean_encounter_probability": mean_probability,
        "n_train": len(y_train),
        "n_test": len(y_test),
        "n_estimators": rf.n_estimators,
    }


def fit_cca(df: pd.DataFrame) -> Dict[str, Any]:
    """Perform Canonical Correspondence Analysis (CCA)."""
    predictors = _get_available_predictors(df)
    clean_df = df[["presence"] + predictors].dropna()

    if len(clean_df) < 10:
        raise ValueError(f"Insufficient data for CCA: {len(clean_df)} rows")

    Y = clean_df[["presence"]].values.astype(float)
    X = clean_df[predictors].values.astype(float)

    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_std[X_std == 0] = 1
    X_standardized = (X - X_mean) / X_std

    Y_mean = Y.mean(axis=0)
    Y_centered = Y - Y_mean

    try:
        X_with_const = np.column_stack([np.ones(len(X_standardized)), X_standardized])
        beta = np.linalg.lstsq(X_with_const, Y_centered, rcond=None)[0]
        Y_hat = X_with_const @ beta

        eigenvalue = float(np.sum(Y_hat ** 2))
        total_inertia = float(np.sum(Y_centered ** 2))
        explained_variance = (
            round(eigenvalue / total_inertia * 100, 2) if total_inertia > 0 else 0
        )

        variable_scores = {
            predictors[i]: round(float(beta[i + 1, 0]), 4)
            for i in range(len(predictors))
        }

    except np.linalg.LinAlgError as exc:
        raise ValueError(f"CCA computation failed: {exc}")

    logger.info("CCA completed: explained_variance=%.1f%%", explained_variance)
    return {
        "model_type": "CCA (Canonical Correspondence Analysis)",
        "eigenvalue": round(eigenvalue, 4),
        "total_inertia": round(total_inertia, 4),
        "explained_variance_pct": explained_variance,
        "variable_scores": variable_scores,
        "n_samples": len(clean_df),
        "n_predictors": len(predictors),
    }


def predict_probability(
    model_results: Dict[str, Any],
    conditions: Dict[str, float],
) -> Optional[float]:
    """Given model results and current conditions, estimate encounter probability."""
    model_type = model_results.get("model_type", "")

    if "GLM" in model_type:
        coefficients = model_results.get("coefficients", {})
        if not coefficients:
            return None

        linear = coefficients.get("intercept", 0)
        for var, coeff in coefficients.items():
            if var == "intercept":
                continue
            if var in conditions:
                linear += coeff * conditions[var]

        probability = 1.0 / (1.0 + np.exp(-linear))
        return round(float(probability), 4)

    return model_results.get("mean_encounter_probability")
