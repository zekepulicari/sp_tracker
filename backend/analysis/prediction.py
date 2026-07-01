import logging
from datetime import datetime
from typing import Dict, Any, Callable, List
import httpx
import pandas as pd
import asyncio
import math

from analysis.data_ingestion import fetch_obis_occurrences, generate_pseudo_absences, fetch_historical_weather, fetch_marine_conditions
from analysis.probability_model import fit_glm, fit_random_forest, fit_cca
from analysis.interpretation import generate_interpretation

logger = logging.getLogger(__name__)

async def fetch_open_meteo_forecast(lat: float, lng: float, target_date: str) -> dict:
    """Fetch weather/marine forecast for a target date (<= 14 days)."""
    weather_url = "https://api.open-meteo.com/v1/forecast"
    marine_url = "https://marine-api.open-meteo.com/v1/marine"

    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": target_date,
        "end_date": target_date,
        "daily": "temperature_2m_mean,wind_speed_10m_max,precipitation_sum",
        "timezone": "GMT"
    }
    
    marine_params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": target_date,
        "end_date": target_date,
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
            w_resp = await client.get(weather_url, params=params)
            w_resp.raise_for_status()
            w_data = w_resp.json()
            if "daily" in w_data:
                env_data["air_temp"] = w_data["daily"]["temperature_2m_mean"][0]
                env_data["wind_speed"] = w_data["daily"]["wind_speed_10m_max"][0]
                env_data["precipitation"] = w_data["daily"]["precipitation_sum"][0]
                
            m_resp = await client.get(marine_url, params=marine_params)
            m_resp.raise_for_status()
            m_data = m_resp.json()
            if "daily" in m_data:
                env_data["wave_height"] = m_data["daily"].get("wave_height_max", [None])[0]
                env_data["ocean_current"] = m_data["daily"].get("ocean_current_velocity_max", [None])[0]
                env_data["sst"] = env_data["air_temp"] 
        except Exception as e:
            logger.warning(f"Error fetching forecast: {e}")
            
    return env_data

async def fetch_open_meteo_historical_average(lat: float, lng: float, target_date: str) -> dict:
    """Fetch historical average for a given location and month (simulated by fetching last year's same month)."""
    past_date_obj = datetime.strptime(target_date, "%Y-%m-%d")
    try:
        past_date = past_date_obj.replace(year=past_date_obj.year - 1).strftime("%Y-%m-%d")
    except ValueError:
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
            w_resp = await client.get(weather_url, params=params)
            w_resp.raise_for_status()
            w_data = w_resp.json()
            if "daily" in w_data:
                env_data["air_temp"] = w_data["daily"]["temperature_2m_mean"][0]
                env_data["wind_speed"] = w_data["daily"]["wind_speed_10m_max"][0]
                env_data["precipitation"] = w_data["daily"]["precipitation_sum"][0]
                
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
    try:
        def update_progress(msg: str):
            analysis_tasks[task_id]["progress"] = msg
            logger.info("[%s] %s", task_id[:8], msg)

        analysis_tasks[task_id]["status"] = "running"
        
        # 1. Dynamic radius expansion to find at least 50 occurrences, capped at 50km
        max_radius_km = 50.0
        occurrences = []
        
        while radius_km <= max_radius_km:
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
            
            if len(occurrences) >= 50:
                break
                
            if radius_km >= max_radius_km:
                break
                
            update_progress(f"Found {len(occurrences)} records. Expanding radius...")
            radius_km += 5.0
            
            # Avoid exceeding the absolute max in the next iteration
            if radius_km > max_radius_km:
                radius_km = max_radius_km
                
        if len(occurrences) < 10:
            raise ValueError(f"Only {len(occurrences)} historical occurrences found near this location for {species} even at {max_radius_km}km. Model requires more data.")

        update_progress("Generating local pseudo-absences...")
        dataset_points = []
        for rec in occurrences:
            dataset_points.append({**rec, "presence": 1})
            
        absences = generate_pseudo_absences(occurrences, len(occurrences))
        for rec in absences:
            dataset_points.append({**rec, "presence": 0})
        
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
        
        df = pd.DataFrame(dataset_points)
        df.dropna(subset=["sst", "wind_speed"], inplace=True)
        
        if df.empty or df["presence"].sum() < 5 or (df["presence"] == 0).sum() < 5:
            raise ValueError("Insufficient environmental data for local training.")
            
        update_progress("Fitting local predictive model (GLM)...")
        model_result = fit_glm(df)
        
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
            
        update_progress("Predicting encounter probability...")
        import numpy as np
        for col in ["air_temp", "wind_speed", "precipitation", "sst", "wave_height", "ocean_current"]:
            if env_conditions.get(col) is None:
                if col in df.columns:
                    mean_val = df[col].mean()
                    env_conditions[col] = 0.0 if np.isnan(mean_val) else float(mean_val)
                else:
                    env_conditions[col] = 0.0
            elif isinstance(env_conditions[col], float) and np.isnan(env_conditions[col]):
                env_conditions[col] = 0.0
        coeffs = model_result.get("coefficients", {})
        intercept = coeffs.get("intercept", 0.0)
        logit = intercept
        for var, val in env_conditions.items():
            if var in coeffs:
                logit += coeffs[var] * val
                
        prob = 1.0 / (1.0 + np.exp(-logit))
        
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
        
        interpretation_text = generate_interpretation(species, results_data)
        results_data["interpretation"] = interpretation_text

        analysis_tasks[task_id]["status"] = "complete"
        analysis_tasks[task_id]["results"] = results_data
    except Exception as exc:
        logger.exception("Prediction failed for task %s", task_id)
        analysis_tasks[task_id]["status"] = "error"
        analysis_tasks[task_id]["error"] = str(exc)
