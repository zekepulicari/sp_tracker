import logging
import math
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
import httpx
import asyncio

from analysis.data_ingestion import fetch_inaturalist_occurrences, fetch_historical_weather, fetch_marine_conditions
from analysis.prediction import fetch_open_meteo_forecast, fetch_open_meteo_historical_average
from analysis.interpretation import generate_interpretation

logger = logging.getLogger(__name__)

ENV_VARIABLES = ["sst", "wind_speed", "wave_height", "ocean_current"]

def compute_polygon_centroid(polygon_ring: List[List[float]]) -> Tuple[float, float]:
    """
    Compute geographic centroid (lat, lng) from GeoJSON ring of [lng, lat] coordinates.
    """
    if not polygon_ring:
        raise ValueError("Polygon ring is empty")
    
    pts = polygon_ring[:-1] if len(polygon_ring) > 3 and polygon_ring[0] == polygon_ring[-1] else polygon_ring
    
    avg_lng = sum(p[0] for p in pts) / len(pts)
    avg_lat = sum(p[1] for p in pts) / len(pts)
    return avg_lat, avg_lng

def is_point_in_polygon(lat: float, lng: float, polygon_ring: List[List[float]]) -> bool:
    """Ray-casting algorithm to test if (lat, lng) is inside GeoJSON [lng, lat] polygon."""
    n = len(polygon_ring)
    inside = False
    p1x, p1y = polygon_ring[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon_ring[i % n]
        if lat > min(p1y, p2y):
            if lat <= max(p1y, p2y):
                if lng <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (lat - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or lng <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def compute_niche_envelope(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Extract statistical percentile envelope (min, p10, median, p90, max) for environmental parameters.
    """
    envelope = {}
    for var in ENV_VARIABLES:
        vals = [float(r[var]) for r in records if r.get(var) is not None and not math.isnan(float(r[var]))]
        if not vals:
            continue
        vals_arr = np.array(vals)
        envelope[var] = {
            "min": round(float(np.min(vals_arr)), 2),
            "p10": round(float(np.percentile(vals_arr, 10)), 2),
            "median": round(float(np.median(vals_arr)), 2),
            "p90": round(float(np.percentile(vals_arr, 90)), 2),
            "max": round(float(np.max(vals_arr)), 2),
        }
    return envelope

def evaluate_niche_viability(
    envelope: Dict[str, Dict[str, float]], 
    forecast: Dict[str, Optional[float]]
) -> Dict[str, Any]:
    """
    Compare forecasted environmental parameters against species envelope bounds.
    """
    param_scores = []
    limiting_factors = []
    parameter_breakdown = {}

    for var, env in envelope.items():
        val = forecast.get(var)
        if val is None or math.isnan(val):
            continue

        val = float(val)
        min_v = env["min"]
        p10_v = env["p10"]
        med_v = env["median"]
        p90_v = env["p90"]
        max_v = env["max"]

        score = 100.0
        status = "Optimal"

        if p10_v <= val <= p90_v:
            score = 100.0
            status = "Optimal"
        elif min_v <= val < p10_v:
            span = p10_v - min_v if p10_v != min_v else 1.0
            score = 60.0 + 40.0 * ((val - min_v) / span)
            status = "Tolerable (Low)"
        elif p90_v < val <= max_v:
            span = max_v - p90_v if max_v != p90_v else 1.0
            score = 60.0 + 40.0 * ((max_v - val) / span)
            status = "Tolerable (High)"
        elif val < min_v:
            excess = min_v - val
            span = abs(min_v) if min_v != 0 else 1.0
            score = max(5.0, 60.0 - (excess / span) * 50.0)
            status = "Critical (Below Min)"
            limiting_factors.append({
                "variable": var,
                "reason": f"Value {val} is below historical minimum {min_v}",
                "severity": "High"
            })
        else:
            excess = val - max_v
            span = abs(max_v) if max_v != 0 else 1.0
            score = max(5.0, 60.0 - (excess / span) * 50.0)
            status = "Critical (Above Max)"
            limiting_factors.append({
                "variable": var,
                "reason": f"Value {val} exceeds historical maximum {max_v}",
                "severity": "High"
            })

        param_scores.append(score)
        parameter_breakdown[var] = {
            "forecast_value": val,
            "envelope": env,
            "score": round(score, 1),
            "status": status
        }

    overall_score = float(np.mean(param_scores)) if param_scores else 50.0

    if overall_score >= 80.0 and len(limiting_factors) == 0:
        overall_status = "Optimal"
    elif overall_score >= 60.0 and len(limiting_factors) <= 1:
        overall_status = "Favorable"
    elif overall_score >= 40.0:
        overall_status = "Suboptimal"
    else:
        overall_status = "Unsuitable"

    return {
        "viability_score": round(overall_score, 1),
        "status": overall_status,
        "limiting_factors": limiting_factors,
        "parameter_breakdown": parameter_breakdown
    }

async def run_niche_envelope_pipeline(
    task_id: str,
    species: str,
    taxon_id: Optional[int],
    polygon_ring: List[List[float]],
    target_date: str,
    limit: int,
    analysis_tasks: dict
):
    """
    Run end-to-end Ecological Niche Envelope analysis for an Area of Interest polygon.
    """
    try:
        def update_progress(msg: str):
            analysis_tasks[task_id]["progress"] = msg
            logger.info("[%s] %s", task_id[:8], msg)

        analysis_tasks[task_id]["status"] = "running"
        update_progress("Deriving area centroid & bounding box...")

        centroid_lat, centroid_lng = compute_polygon_centroid(polygon_ring)
        lngs = [p[0] for p in polygon_ring]
        lats = [p[1] for p in polygon_ring]
        bbox = {
            "min_lat": min(lats),
            "max_lat": max(lats),
            "min_lng": min(lngs),
            "max_lng": max(lngs),
        }

        update_progress("Retrieving occurrences inside area...")
        occurrences = await fetch_inaturalist_occurrences(
            species=species, taxon_id=taxon_id, limit=limit, bbox=bbox
        )

        filtered_occ = [
            o for o in occurrences if is_point_in_polygon(o["lat"], o["lng"], polygon_ring)
        ]
        if not filtered_occ:
            filtered_occ = occurrences

        if len(filtered_occ) < 3:
            raise ValueError(f"Insufficient occurrence records ({len(filtered_occ)}) in selected area for {species}.")

        update_progress(f"Found {len(filtered_occ)} sightings. Sampling environmental conditions...")
        
        sample_size = min(15, len(filtered_occ))
        step = max(1, len(filtered_occ) // sample_size)
        sample_occ = filtered_occ[::step][:sample_size]

        records = []
        async with httpx.AsyncClient() as client:
            tasks = []
            for pt in sample_occ:
                async def _fetch(p):
                    w = await fetch_historical_weather(p["lat"], p["lng"], p["date"], client=client)
                    m = await fetch_marine_conditions(p["lat"], p["lng"], p["date"], client=client)
                    return {
                        "sst": m.get("sea_surface_temperature"),
                        "wind_speed": w.get("wind_speed_10m"),
                        "wave_height": m.get("wave_height"),
                        "ocean_current": m.get("ocean_current_velocity")
                    }
                tasks.append(_fetch(pt))
            records = await asyncio.gather(*tasks)

        update_progress("Computing ecological niche envelope...")
        envelope = compute_niche_envelope(records)

        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        days_diff = (target_dt - datetime.now()).days

        update_progress(f"Fetching forecast for {target_date} at centroid...")
        if days_diff <= 14:
            forecast = await fetch_open_meteo_forecast(centroid_lat, centroid_lng, target_date)
        else:
            forecast = await fetch_open_meteo_historical_average(centroid_lat, centroid_lng, target_date)

        update_progress("Evaluating habitat viability against niche envelope...")
        viability = evaluate_niche_viability(envelope, forecast)

        update_progress("Generating AI ecological interpretation...")
        results_data = {
            "analysis_type": "niche_envelope",
            "centroid": {"lat": centroid_lat, "lng": centroid_lng},
            "total_observations_in_area": len(filtered_occ),
            "target_date": target_date,
            "forecast_conditions": forecast,
            "envelope": envelope,
            "viability": viability,
        }

        interpretation_text = generate_interpretation(species, results_data)
        results_data["interpretation"] = interpretation_text

        update_progress("Analysis complete!")
        analysis_tasks[task_id]["status"] = "complete"
        analysis_tasks[task_id]["results"] = results_data

    except Exception as exc:
        logger.exception("Niche envelope analysis failed for task %s", task_id)
        analysis_tasks[task_id]["status"] = "error"
        analysis_tasks[task_id]["error"] = str(exc)