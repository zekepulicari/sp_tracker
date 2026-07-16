"""
interpretation.py — AI module for interpreting statistical outputs.
"""

import logging
import json
import google.generativeai as genai
from config import GEMINI_KEY

logger = logging.getLogger(__name__)

# Configure the Gemini API client
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
else:
    logger.warning("GEMINI_KEY not found in environment. AI interpretation will be disabled.")


def generate_interpretation(species: str, results: dict) -> str:
    """
    Generate a natural language interpretation of the analysis results
    using the Gemini 3.1 Flash-Lite model.
    """
    if not GEMINI_KEY:
        return "AI interpretation is currently disabled (API key missing)."

    # Extract dataset stats
    stats = results.get("dataset_stats", {})
    
    # Extract significant correlations
    correlations = results.get("correlations", {}).get("spearman", {}).get("with_presence", {})
    sig_corr = {
        var: data for var, data in correlations.items() if data.get("significant")
    }

    # Extract VIF
    vif_data = results.get("vif", {})
    collinearity = vif_data.get("has_collinearity", False)
    
    # Extract Model
    model_data = results.get("model", {})
    model_method = "Unknown"
    metrics = {}
    important_vars = {}
    
    if "accuracy" in model_data:
        model_method = "GLM / Logistic Regression"
        metrics = {"Accuracy": model_data.get("accuracy")}
    elif "oob_score" in model_data:
        model_method = "Random Forest"
        metrics = {"OOB Score (Accuracy)": model_data.get("oob_score")}
        if "feature_importance" in model_data:
            # Get top 3 features
            sorted_feats = sorted(model_data["feature_importance"].items(), key=lambda item: item[1], reverse=True)[:3]
            important_vars = {k: round(v, 3) for k, v in sorted_feats}
    elif "explained_variance_ratio" in model_data:
        model_method = "CCA"
        metrics = {"Explained Variance (CCA1)": model_data.get("explained_variance_ratio", {}).get("CCA1")}
    
    prediction_info = ""
    if "encounter_prediction" in results:
        pred = results["encounter_prediction"]
        prediction_info = f"""
# Target Encounter Forecast
* Target Date: {pred.get("target_date")}
* Forecasted Probability: {pred.get("probability_pct"):.1f}%

CRITICAL INSTRUCTION: You MUST explicitly state and interpret this {pred.get("probability_pct"):.1f}% forecast probability in your response. Explain if this represents a high or low chance of an encounter on the target date.
"""

    prompt = f"""
You are an expert ecological data scientist. Your task is to interpret the following statistical analysis results for the species: "{species}".
The analysis predicts the presence vs absence of this species based on environmental variables.
{prediction_info}
# Analysis Summary (Historical Training Data)
* Sample Size (total records): {stats.get("total_records")}
* Presence Count: {stats.get("presence_count")}
* Absence Count: {stats.get("absence_count")}

# Significant Correlations (Spearman)
{json.dumps(sig_corr, indent=2)}

# Predictive Model
* Method: {model_method}
* Training Accuracy: {model_data.get("accuracy")}
* Most Important Variables: {json.dumps(important_vars)}

Write a friendly, simple natural language summary of what these results actually mean. 
Target audience: Biologists and nature photographers who understand basic ecology but aren't statisticians.
Keep it concise, strictly 2-3 short paragraphs.
Focus on:
1. Which environmental factors seem to drive the species' presence.
2. The final forecast probability for the target date (if provided).
Do NOT use markdown headers (##), just standard paragraphs. Use bold text for variable names.
    """

    try:
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as exc:
        logger.error(f"Failed to generate AI interpretation: {exc}")
        return f"Could not generate AI interpretation at this time. ({str(exc)})"
