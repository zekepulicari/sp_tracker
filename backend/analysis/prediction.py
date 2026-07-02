import logging
from datetime import datetime
from typing import Dict, Any, Callable, List
import httpx
import pandas as pd
import asyncio
import math
import numpy as np

from analysis.data_ingestion import fetch_obis_occurrences, generate_pseudo_absences, fetch_historical_weather, fetch_marine_conditions
from analysis.probability_model import fit_glm, fit_random_forest, fit_cca
from analysis.interpretation import generate_interpretation

logger = logging.getLogger(__name__)

async def fetch_open_meteo_forecast(lat: float, lng: float, target_date: str) -> dict:
    """
    Fetch weather and marine forecast data for a specific location and date in the near future.
    
    This function utilizes the Open-Meteo API to retrieve daily maximums and averages 
    for environmental variables (e.g., temperature, wind, wave height) up to 14 days in advance.
    
    Args:
        lat (float): Latitude of the target location.
        lng (float): Longitude of the target location.
        target_date (str): The date to fetch the forecast for, formatted as "YYYY-MM-DD".
        
    Returns:
        dict: A dictionary containing the environmental conditions mapped to model features
              (air_temp, wind_speed, precipitation, sst, wave_height, ocean_current).
    """
    weather_url = "https://api.open-meteo.com/v1/forecast"
    marine_url = "https://marine-api.open-meteo.com/v1/marine"

    # Define query parameters for the general weather API
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": target_date,
        "end_date": target_date,
        "daily": "temperature_2m_mean,wind_speed_10m_max,precipitation_sum",
        "timezone": "GMT"
    }
    
    # Define query parameters for the specialized marine API
    marine_params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": target_date,
        "end_date": target_date,
        "daily": "wave_height_max,ocean_current_velocity_max",
        "timezone": "GMT"
    }
    
    # Initialize the default return payload with null values
    env_data = {
        "air_temp": None,
        "wind_speed": None,
        "precipitation": None,
        "sst": None,  
        "wave_height": None,
        "ocean_current": None
    }

    async with httpx.AsyncClient() as client:
        try:
            # Fetch general weather conditions
            w_resp = await client.get(weather_url, params=params)
            w_resp.raise_for_status()
            w_data = w_resp.json()
            if "daily" in w_data:
                env_data["air_temp"] = w_data["daily"]["temperature_2m_mean"][0]
                env_data["wind_speed"] = w_data["daily"]["wind_speed_10m_max"][0]
                env_data["precipitation"] = w_data["daily"]["precipitation_sum"][0]
                
            # Fetch marine conditions
            m_resp = await client.get(marine_url, params=marine_params)
            m_resp.raise_for_status()
            m_data = m_resp.json()
            if "daily" in m_data:
                env_data["wave_height"] = m_data["daily"].get("wave_height_max", [None])[0]
                env_data["ocean_current"] = m_data["daily"].get("ocean_current_velocity_max", [None])[0]
                
                # As a fallback proxy, we assume sea surface temperature roughly maps to near-surface air temp
                env_data["sst"] = env_data["air_temp"] 
        except Exception as e:
            logger.warning(f"Error fetching forecast: {e}")
            
    return env_data

async def fetch_open_meteo_historical_average(lat: float, lng: float, target_date: str) -> dict:
    """
    Fetch historical average data to act as a proxy when the target date exceeds the 14-day forecast window.
    
    Since standard weather APIs cannot forecast beyond 14 days, this function retrieves 
    historical data from exactly one year prior to simulate expected seasonal conditions.
    
    Args:
        lat (float): Latitude of the target location.
        lng (float): Longitude of the target location.
        target_date (str): The future date to simulate (e.g. >14 days from now).
        
    Returns:
        dict: A dictionary containing the simulated environmental conditions.
    """
    past_date_obj = datetime.strptime(target_date, "%Y-%m-%d")
    try:
        # Subtract exactly one year to retrieve historical seasonality data
        past_date = past_date_obj.replace(year=past_date_obj.year - 1).strftime("%Y-%m-%d")
    except ValueError:
        # Handle leap year edge cases (e.g., Feb 29)
        past_date = past_date_obj.replace(year=past_date_obj.year - 1, day=28).strftime("%Y-%m-%d")
        
    weather_url = "https://archive-api.open-meteo.com/v1/archive"
    marine_url = "https://marine-api.open-meteo.com/v1/marine"

    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": past_date,
        "end_date": past_date,
        "daily": "temperature_2m_mean,wind_speed_10m_max,precipitation_sum",
        "timezone": "GMT"
    }
    
    marine_params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": past_date,
        "end_date": past_date,
        "daily": "wave_height_max,ocean_current_velocity_max",
        "timezone": "GMT"
    }
    
    env_data = {
        "air_temp": None,
        "wind_speed": None,
        "precipitation": None,
        "sst": None,
        "wave_height": None,
        "ocean_current": None
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # Fetch historical general weather conditions
            w_resp = await client.get(weather_url, params=params)
            w_resp.raise_for_status()
            w_data = w_resp.json()
            if "daily" in w_data:
                env_data["air_temp"] = w_data["daily"]["temperature_2m_mean"][0]
                env_data["wind_speed"] = w_data["daily"]["wind_speed_10m_max"][0]
                env_data["precipitation"] = w_data["daily"]["precipitation_sum"][0]
                
            # Fetch historical marine conditions
            m_resp = await client.get(marine_url, params=marine_params)
            m_resp.raise_for_status()
            m_data = m_resp.json()
            if "daily" in m_data:
                env_data["wave_height"] = m_data["daily"].get("wave_height_max", [None])[0]
                env_data["ocean_current"] = m_data["daily"].get("ocean_current_velocity_max", [None])[0]
                env_data["sst"] = env_data["air_temp"] 
        except Exception as e:
            logger.warning(f"Error fetching historical proxy: {e}")
            
    return env_data

async def run_prediction_pipeline(task_id: str, species: str, lat: float, lng: float, target_date: str, radius_km: float, limit: int, analysis_tasks: dict):
    """
    Orchestrate the end-to-end local prediction pipeline for a specific geographic coordinate and date.
    
    This function:
    1. Dynamically expands a bounding box around the target location until it finds enough historical sightings.
    2. Generates pseudo-absence data to train the model against.
    3. Fetches historical environmental data (SST, wind speed, etc.) for all sightings and absences.
    4. Trains a local Generalized Linear Model (GLM) specifically tuned for this region.
    5. Retrieves the forecasted environmental conditions for the target date.
    6. Uses the trained GLM to calculate the probability of encountering the species.
    7. Leverages Gemini AI to interpret the results in natural language.
    
    Args:
        task_id (str): Unique UUID to track the background job's progress.
        species (str): Scientific name of the target species.
        lat (float): Target latitude.
        lng (float): Target longitude.
        target_date (str): The date to predict the encounter for.
        radius_km (float): The starting radius in kilometers to search for historical data.
        limit (int): The maximum number of occurrence records to retrieve.
        analysis_tasks (dict): The shared state dictionary used to broadcast status to the frontend.
    """
    try:
        def update_progress(msg: str):
            """Helper to push status updates to the shared tracking dictionary."""
            analysis_tasks[task_id]["progress"] = msg
            logger.info("[%s] %s", task_id[:8], msg)

        analysis_tasks[task_id]["status"] = "running"
        
        # ---------------------------------------------------------------------
        # STEP 1: Spatial Filtering & Dynamic Bounding Box Expansion
        # ---------------------------------------------------------------------
        # We need a minimum amount of data to train a reliable local model.
        # We start at the given radius (e.g., 5km) and expand outwards until we hit 50 occurrences,
        # capping the search at 50km to ensure the model remains highly localized to the region.
        max_radius_km = 50.0
        occurrences = []
        
        while radius_km <= max_radius_km:
            # Convert kilometers to approximate latitude and longitude degrees
            lat_diff = radius_km / 111.0
            lng_diff = radius_km / (111.0 * math.cos(math.radians(lat)))
            
            bbox = {
                "min_lat": lat - lat_diff,
                "max_lat": lat + lat_diff,
                "min_lng": lng - lng_diff,
                "max_lng": lng + lng_diff
            }
            
            update_progress(f"Fetching local historical occurrences ({radius_km}km radius)...")
            occurrences = await fetch_obis_occurrences(species=species, limit=limit, bbox=bbox)
            
            # If we found at least 50 records, we have enough data to stop expanding.
            if len(occurrences) >= 50:
                break
                
            # Stop expanding if we've reached the maximum logical bounds for a "local" search.
            if radius_km >= max_radius_km:
                break
                
            update_progress(f"Found {len(occurrences)} records. Expanding radius...")
            radius_km += 5.0
            
            # Avoid exceeding the absolute max in the final iteration
            if radius_km > max_radius_km:
                radius_km = max_radius_km
                
        # If even at the 50km cap we couldn't find 10 historical records, the model cannot reliably train.
        if len(occurrences) < 10:
            raise ValueError(f"Only {len(occurrences)} historical occurrences found near this location for {species} even at {max_radius_km}km. Model requires more data.")

        # ---------------------------------------------------------------------
        # STEP 2: Pseudo-Absence Generation
        # ---------------------------------------------------------------------
        # Predictive models require both "Presence" (1) and "Absence" (0) data to learn what
        # environmental conditions the species avoids.
        update_progress("Generating local pseudo-absences...")
        dataset_points = []
        
        # Tag all actual sightings as Presence (1)
        for rec in occurrences:
            dataset_points.append({**rec, "presence": 1})
            
        # Generate random geographical points nearby and tag them as Absence (0)
        absences = generate_pseudo_absences(occurrences, len(occurrences))
        for rec in absences:
            dataset_points.append({**rec, "presence": 0})
        
        # ---------------------------------------------------------------------
        # STEP 3: Environmental Data Alignment (Training Data)
        # ---------------------------------------------------------------------
        # For every presence and absence point, we must fetch what the weather/ocean was like
        # at that exact location on that exact historical date.
        update_progress("Fetching environmental history for training...")
        
        async with httpx.AsyncClient() as client:
            for i, point in enumerate(dataset_points):
                if i % 50 == 0 and i > 0:
                    update_progress(f"Processing environmental data: {i}/{len(dataset_points)} points...")
                    
                weather = await fetch_historical_weather(
                    point["lat"], point["lng"], point["date"], client=client
                )
                marine = await fetch_marine_conditions(
                    point["lat"], point["lng"], point["date"], client=client
                )
                
                point["sst"] = marine.get("sea_surface_temperature")
                point["wind_speed"] = weather.get("wind_speed_10m")
                point["air_temp"] = weather.get("temperature_2m")
                point["precipitation"] = weather.get("precipitation")
                point["wave_height"] = marine.get("wave_height")
                point["ocean_current"] = marine.get("ocean_current_velocity")
        
        # Convert to a DataFrame for statistical modeling
        df = pd.DataFrame(dataset_points)
        
        # Drop rows missing critical baseline data (Sea Surface Temp and Wind Speed)
        df.dropna(subset=["sst", "wind_speed"], inplace=True)
        
        # Ensure we still have a minimally viable dataset after dropping empty rows
        if df.empty or df["presence"].sum() < 5 or (df["presence"] == 0).sum() < 5:
            raise ValueError("Insufficient environmental data for local training.")
            
        # ---------------------------------------------------------------------
        # STEP 4: Local Model Training
        # ---------------------------------------------------------------------
        update_progress("Fitting local predictive model (GLM)...")
        model_result = fit_glm(df)
        
        # ---------------------------------------------------------------------
        # STEP 5: Environmental Forecasting (Inference Data)
        # ---------------------------------------------------------------------
        # Determine if the target date is close enough for a real forecast, or if we need a historical proxy
        target = datetime.strptime(target_date, "%Y-%m-%d")
        days_diff = (target - datetime.now()).days
        
        if days_diff <= 14:
            update_progress(f"Fetching weather forecast for {target_date}...")
            env_conditions = await fetch_open_meteo_forecast(lat, lng, target_date)
            mode = "Forecast (<= 14 days)"
        else:
            update_progress(f"Fetching historical average for {target_date}...")
            env_conditions = await fetch_open_meteo_historical_average(lat, lng, target_date)
            mode = "Historical Proxy (> 14 days)"
            
        # ---------------------------------------------------------------------
        # STEP 6: Encounter Probability Calculation
        # ---------------------------------------------------------------------
        update_progress("Predicting encounter probability...")
        
        # Clean and sanitize environmental conditions for model input and JSON serialization
        # We must replace NaN values with None (null in JSON) to prevent HTTP 500 errors.
        # If a variable is entirely missing, it will safely be ignored in the logit calculation.
        for col in ["air_temp", "wind_speed", "precipitation", "sst", "wave_height", "ocean_current"]:
            # If the value is completely missing from the Open-Meteo API response:
            if env_conditions.get(col) is None:
                if col in df.columns:
                    # Attempt to fall back to the historical dataset mean for that variable
                    mean_val = df[col].mean()
                    # If the entire training column was NaN, fallback to None. Otherwise, use the mean.
                    env_conditions[col] = None if np.isnan(mean_val) else float(mean_val)
                else:
                    env_conditions[col] = None
            # If the API returned a value, but the value is NaN:
            elif isinstance(env_conditions[col], float) and np.isnan(env_conditions[col]):
                env_conditions[col] = None
                
        # Extract model coefficients (weights assigned to each environmental variable)
        coeffs = model_result.get("coefficients", {})
        intercept = coeffs.get("intercept", 0.0)
        logit = intercept
        
        # Compute the log-odds (logit) by summing the weighted environmental conditions
        for var, val in env_conditions.items():
            if var in coeffs and val is not None:
                logit += coeffs[var] * val
                
        # Convert the log-odds into a probability percentage (0.0 to 1.0) using the sigmoid function
        prob = 1.0 / (1.0 + np.exp(-logit))
        
        # ---------------------------------------------------------------------
        # STEP 7: AI Interpretation and Finalization
        # ---------------------------------------------------------------------
        update_progress("Generating AI Interpretation...")
        results_data = {
            "encounter_prediction": {
                "probability_pct": prob * 100,
                "mode": mode,
                "target_date": target_date,
                "target_lat": lat,
                "target_lng": lng,
                "radius_km_used": radius_km,
                "conditions_used": env_conditions
            },
            "model": model_result,
            "dataset_stats": {
                "total_records": len(df),
                "presence_count": int(df["presence"].sum()),
                "absence_count": int((df["presence"] == 0).sum())
            }
        }
        
        # Pass the statistical results to Gemini to generate a human-readable summary
        interpretation_text = generate_interpretation(species, results_data)
        results_data["interpretation"] = interpretation_text

        # Mark task as complete and push results to the frontend
        analysis_tasks[task_id]["status"] = "complete"
        analysis_tasks[task_id]["results"] = results_data
        
    except Exception as exc:
        logger.exception("Prediction failed for task %s", task_id)
        analysis_tasks[task_id]["status"] = "error"
        analysis_tasks[task_id]["error"] = str(exc)
