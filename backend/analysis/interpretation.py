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

    # Extract Model
    model_data = results.get("model", {})
    model_method = "Unknown"
    important_vars = {}

    if "accuracy" in model_data:
        model_method = "GLM / Logistic Regression"
    elif "oob_score" in model_data:
        model_method = "Random Forest"
        if "feature_importance" in model_data:
            sorted_feats = sorted(model_data["feature_importance"].items(), key=lambda item: item[1], reverse=True)[:3]
            important_vars = {k: round(v, 3) for k, v in sorted_feats}
    elif "explained_variance_ratio" in model_data:
        model_method = "CCA"

    # Determine algorithm context for tailoring the prompt
    algorithm_method = results.get("encounter_prediction", {}).get("algorithm_method", "")
    is_rustic = algorithm_method == "rustic"

    if is_rustic:
        analysis_context = (
            "IMPORTANT: This analysis used the 'Rustic (Historical Base Rate)' algorithm. "
            "This algorithm does NOT use any environmental variables (temperature, wind, SST, etc.). "
            "It is a seasonality-only model that predicts encounter probability based solely on the "
            "month of year extracted from historical sighting dates. "
            "Do NOT mention environmental conditions, weather, or ocean variables — they were not part of this calculation."
        )
        focus_instructions = (
            "1. Explain that this is a baseline seasonality model based on historical sighting frequency by month.\n"
            "2. Clarify that no weather or environmental data was involved.\n"
            "3. State the forecast probability and what it means in practical terms."
        )
    else:
        analysis_context = (
            "This analysis used environmental variables (temperature, wind speed, sea surface temperature, "
            "wave height, ocean currents, precipitation) to model species presence."
        )
        focus_instructions = (
            "1. Which environmental factors seem to drive the species' presence.\n"
            "2. The final forecast probability for the target date (if provided)."
        )

    prediction_info = ""
    if "encounter_prediction" in results:
        pred = results["encounter_prediction"]
        prediction_info = f"""
# Target Encounter Forecast
* Algorithm Used: {pred.get("algorithm_method")}
* Mode: {pred.get("mode")}
* Target Date: {pred.get("target_date")}
* Forecasted Probability: {pred.get("probability_pct"):.1f}%

CRITICAL INSTRUCTION: You MUST explicitly state and interpret this {pred.get("probability_pct"):.1f}% forecast probability in your response. Explain if this represents a high or low chance of an encounter on the target date.
"""

    correlations_section = "" if is_rustic else f"\n# Significant Correlations (Spearman)\n{json.dumps(sig_corr, indent=2)}\n"
    important_vars_section = "" if is_rustic else f"\n* Most Important Variables: {json.dumps(important_vars)}"

    prompt = f"""
You are an expert ecological data scientist. Your task is to interpret the following statistical analysis results for the species: "{species}".

{analysis_context}
{prediction_info}
# Analysis Summary (Historical Training Data)
* Sample Size (total records): {stats.get("total_records")}
* Presence Count: {stats.get("presence_count")}
* Absence Count: {stats.get("absence_count")}
{correlations_section}
# Predictive Model
* Method: {model_method}
* Training Accuracy: {model_data.get("accuracy")}{important_vars_section}

Write a friendly, simple natural language summary of what these results actually mean.
Target audience: Biologists and nature photographers who understand basic ecology but aren't statisticians.
Keep it concise, strictly 2-3 short paragraphs.
Focus on:
{focus_instructions}
Do NOT use markdown headers (##), just standard paragraphs. Use bold text for variable names.
    """

    try:
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as exc:
        logger.error(f"Failed to generate AI interpretation: {exc}")
        return f"Could not generate AI interpretation at this time. ({str(exc)})"
