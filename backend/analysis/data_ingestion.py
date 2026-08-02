"""
data_ingestion.py — Fetch & align species occurrence + environmental data.

Data sources:
  - OBIS API (species occurrences)
  - Open-Meteo Archive API (historical weather: temperature, wind)
  - Open-Meteo Marine API (SST, wave height, ocean currents)

The module fetches occurrence records, generates pseudo-absence background
points, retrieves environmental conditions for every point from Open-Meteo,
and returns a single aligned Pandas DataFrame ready for statistical analysis.
"""

import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

import httpx
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OBIS_API_BASE = "https://api.obis.org/v3/occurrence"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"

# Maximum divergence (°C) between OBIS SST and Open-Meteo SST before warning
SST_DIVERGENCE_THRESHOLD = 2.0

# Timeout for individual API requests (seconds)
API_TIMEOUT = 30.0

# Maximum concurrent Open-Meteo requests (stay well under 600/min limit)
MAX_CONCURRENT_REQUESTS = 10


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class RateLimitError(Exception):
    """Raised when an API returns HTTP 429 (Too Many Requests)."""
    pass


# ---------------------------------------------------------------------------
# OBIS: Species Occurrence Fetching
# ---------------------------------------------------------------------------
async def fetch_obis_occurrences(
    species: str,
    limit: int = 500,
    bbox: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch historical species occurrence records from the OBIS API.

    :param species: Scientific name, e.g. "Orcinus orca".
    :param limit: Maximum number of records to retrieve.
    :param bbox: Optional bounding box dict {min_lng, min_lat, max_lng, max_lat}.
    :returns: List of dicts with keys: lat, lng, date, obis_sst, obis_sss.
    """
    records: List[Dict[str, Any]] = []
    page_size = min(limit, 1000)  # OBIS max page size is 1000
    offset = 0

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        while len(records) < limit:
            params: Dict[str, Any] = {
                "scientificname": species,
                "size": page_size,
                "offset": offset,
            }
            if bbox:
                params["geometry"] = (
                    f"POLYGON(({bbox['min_lng']} {bbox['min_lat']},"
                    f"{bbox['max_lng']} {bbox['min_lat']},"
                    f"{bbox['max_lng']} {bbox['max_lat']},"
                    f"{bbox['min_lng']} {bbox['max_lat']},"
                    f"{bbox['min_lng']} {bbox['min_lat']}))"
                )

            try:
                resp = await client.get(OBIS_API_BASE, params=params)
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.error("OBIS API error: %s", exc)
                break

            results = data.get("results", [])
            if not results:
                break

            for rec in results:
                lat = rec.get("decimalLatitude")
                lng = rec.get("decimalLongitude")
                event_date = rec.get("eventDate")

                if lat is None or lng is None or event_date is None:
                    continue

                try:
                    dt = datetime.fromisoformat(
                        event_date.replace("Z", "+00:00").split("T")[0]
                    )
                except ValueError:
                    continue

                records.append({
                    "lat": float(lat),
                    "lng": float(lng),
                    "date": dt.strftime("%Y-%m-%d"),
                    "month": dt.month,
                    "obis_sst": rec.get("sst"),
                    "obis_sss": rec.get("sss"),
                })

                if len(records) >= limit:
                    break

            offset += page_size
            if offset >= data.get("total", 0):
                break

    logger.info("Fetched %d OBIS records for '%s'", len(records), species)
    return records


# ---------------------------------------------------------------------------
# iNaturalist: Species Occurrence Fetching
# ---------------------------------------------------------------------------
async def fetch_inaturalist_occurrences(
    species: str,
    taxon_id: Optional[int] = None,
    limit: int = 500,
    bbox: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch historical species occurrence records from the iNaturalist API.

    :param species: Scientific name, e.g. "Columba livia".
    :param limit: Maximum number of records to retrieve.
    :param bbox: Optional bounding box dict {min_lng, min_lat, max_lng, max_lat}.
    :returns: List of dicts with keys: lat, lng, date, month.
    """
    records: List[Dict[str, Any]] = []
    page_size = min(limit, 200)  # iNaturalist API maxes out efficiently around 200 per page for observations
    page = 1

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        # Resolve taxon_id if not provided
        if not taxon_id:
            try:
                resp = await client.get(f"https://api.inaturalist.org/v1/taxa/autocomplete?q={species}")
                data = resp.json()
                if data.get("results") and len(data["results"]) > 0:
                    taxon_id = data["results"][0]["id"]
            except Exception as e:
                logger.warning("Failed to resolve taxon_id for %s: %s", species, e)

        while len(records) < limit:
            params: Dict[str, Any] = {
                "per_page": page_size,
                "page": page,
                "quality_grade": "research",  # Ensure high quality data
                "has[]": "geo" # Must have coordinates
            }
            if taxon_id:
                params["taxon_id"] = taxon_id
            else:
                params["taxon_name"] = species
            if bbox:
                params["nelat"] = bbox['max_lat']
                params["nelng"] = bbox['max_lng']
                params["swlat"] = bbox['min_lat']
                params["swlng"] = bbox['min_lng']

            try:
                resp = await client.get("https://api.inaturalist.org/v1/observations", params=params)
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.error("iNaturalist API error: %s", exc)
                break

            results = data.get("results", [])
            if not results:
                break

            for rec in results:
                location = rec.get("location")
                if not location:
                    continue
                    
                lat_str, lng_str = location.split(",")
                lat = float(lat_str)
                lng = float(lng_str)
                
                observed_on = rec.get("observed_on")
                if not observed_on:
                    continue

                try:
                    dt = datetime.fromisoformat(observed_on)
                except ValueError:
                    continue

                records.append({
                    "lat": lat,
                    "lng": lng,
                    "date": dt.strftime("%Y-%m-%d"),
                    "month": dt.month,
                })

                if len(records) >= limit:
                    break

            page += 1
            if len(results) < page_size:
                # We've reached the end of the available results
                break

    logger.info("Fetched %d iNaturalist records for '%s'", len(records), species)
    return records


# ---------------------------------------------------------------------------
# Open-Meteo: Historical Weather
# ---------------------------------------------------------------------------
async def fetch_historical_weather(
    lat: float,
    lng: float,
    date: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Optional[float]]:
    """
    Fetch historical weather from Open-Meteo Archive API for a single day.

    :param lat: Latitude.
    :param lng: Longitude.
    :param date: Date string "YYYY-MM-DD".
    :param client: Optional reusable httpx client.
    :returns: Dict with temperature_2m, wind_speed_10m, wind_direction_10m.
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": date,
        "end_date": date,
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
    }

    result = {
        "temperature_2m": None,
        "wind_speed_10m": None,
        "wind_direction_10m": None,
    }

    try:
        should_close = client is None
        client = client or httpx.AsyncClient(timeout=API_TIMEOUT)
        try:
            resp = await client.get(OPEN_METEO_ARCHIVE, params=params)

            if resp.status_code == 429:
                raise RateLimitError(
                    "Open-Meteo Weather API quota exceeded (HTTP 429). "
                    "Free tier allows 10,000 requests/day and 600/min. "
                    "Please try again later or reduce the sample size."
                )

            resp.raise_for_status()
            data = resp.json()

            hourly = data.get("hourly", {})
            for key in result:
                values = hourly.get(key, [])
                valid = [v for v in values if v is not None]
                result[key] = float(np.mean(valid)) if valid else None
        finally:
            if should_close:
                await client.aclose()

    except RateLimitError:
        raise  # Let rate limit errors propagate immediately
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Open-Meteo weather error for (%s, %s, %s): %s",
                       lat, lng, date, exc)

    return result


# ---------------------------------------------------------------------------
# Open-Meteo: Marine Conditions
# ---------------------------------------------------------------------------
async def fetch_marine_conditions(
    lat: float,
    lng: float,
    date: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Optional[float]]:
    """
    Fetch marine conditions from Open-Meteo Marine API for a single day.

    :param lat: Latitude.
    :param lng: Longitude.
    :param date: Date string "YYYY-MM-DD".
    :param client: Optional reusable httpx client.
    :returns: Dict with sea_surface_temperature, wave_height,
              ocean_current_velocity.
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": date,
        "end_date": date,
        "hourly": "sea_surface_temperature,wave_height,ocean_current_velocity",
    }

    result = {
        "sea_surface_temperature": None,
        "wave_height": None,
        "ocean_current_velocity": None,
    }

    try:
        should_close = client is None
        client = client or httpx.AsyncClient(timeout=API_TIMEOUT)
        try:
            resp = await client.get(OPEN_METEO_MARINE, params=params)

            if resp.status_code == 429:
                raise RateLimitError(
                    "Open-Meteo Marine API quota exceeded (HTTP 429). "
                    "Free tier allows 10,000 requests/day and 600/min. "
                    "Please try again later or reduce the sample size."
                )

            resp.raise_for_status()
            data = resp.json()

            hourly = data.get("hourly", {})
            for key in result:
                values = hourly.get(key, [])
                valid = [v for v in values if v is not None]
                result[key] = float(np.mean(valid)) if valid else None
        finally:
            if should_close:
                await client.aclose()

    except RateLimitError:
        raise  # Let rate limit errors propagate immediately
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Open-Meteo marine error for (%s, %s, %s): %s",
                       lat, lng, date, exc)

    return result


# ---------------------------------------------------------------------------
# SST Validation
# ---------------------------------------------------------------------------
def validate_sst(
    open_meteo_sst: Optional[float],
    obis_sst: Optional[float],
) -> Dict[str, Any]:
    """
    Compare Open-Meteo SST with OBIS pre-computed SST for quality assurance.

    :returns: Dict with ok (bool), divergence (float|None), warning (str|None).
    """
    if open_meteo_sst is None or obis_sst is None:
        return {"ok": True, "divergence": None, "warning": None}

    divergence = abs(open_meteo_sst - obis_sst)
    if divergence > SST_DIVERGENCE_THRESHOLD:
        return {
            "ok": False,
            "divergence": round(divergence, 2),
            "warning": (
                f"SST divergence: Open-Meteo={open_meteo_sst:.1f}°C vs "
                f"OBIS={obis_sst:.1f}°C (Δ={divergence:.1f}°C)"
            ),
        }
    return {"ok": True, "divergence": round(divergence, 2), "warning": None}


# ---------------------------------------------------------------------------
# Pseudo-Absence Generation
# ---------------------------------------------------------------------------
def generate_pseudo_absences(
    occurrences: List[Dict[str, Any]],
    n_absences: int,
) -> List[Dict[str, Any]]:
    """
    Generate pseudo-absence (background) points for SDM training.

    Points are placed randomly within the geographic and temporal extent
    of the real occurrence data, with a buffer.

    :param occurrences: List of occurrence dicts with lat, lng, date.
    :param n_absences: Number of pseudo-absence points to generate.
    :returns: List of dicts with lat, lng, date, month (presence=0).
    """
    if not occurrences:
        return []

    lats = [r["lat"] for r in occurrences]
    lngs = [r["lng"] for r in occurrences]
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in occurrences]

    lat_range = max(lats) - min(lats)
    lng_range = max(lngs) - min(lngs)
    buffer_lat = max(lat_range * 0.1, 1.0)
    buffer_lng = max(lng_range * 0.1, 1.0)

    lat_min = max(min(lats) - buffer_lat, -90)
    lat_max = min(max(lats) + buffer_lat, 90)
    lng_min = max(min(lngs) - buffer_lng, -180)
    lng_max = min(max(lngs) + buffer_lng, 180)

    date_min = min(dates)
    date_max = max(dates)
    date_span = (date_max - date_min).days
    if date_span < 30:
        date_span = 365

    absences = []
    for _ in range(n_absences):
        rand_lat = random.uniform(lat_min, lat_max)
        rand_lng = random.uniform(lng_min, lng_max)
        rand_date = date_min + timedelta(days=random.randint(0, date_span))

        absences.append({
            "lat": round(rand_lat, 4),
            "lng": round(rand_lng, 4),
            "date": rand_date.strftime("%Y-%m-%d"),
            "month": rand_date.month,
        })

    logger.info("Generated %d pseudo-absence points", len(absences))
    return absences


# ---------------------------------------------------------------------------
# Master Pipeline: Build Aligned Dataset
# ---------------------------------------------------------------------------
async def build_aligned_dataset(
    species: str,
    taxon_id: Optional[int] = None,
    limit: int = 500,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    End-to-end pipeline: fetch occurrences, generate pseudo-absences,
    retrieve environmental data for all points, and return an aligned
    DataFrame plus validation metadata.

    :param species: Scientific name.
    :param limit: Number of OBIS records to fetch.
    :param progress_callback: Optional callable(message: str) for progress.
    :returns: Dict with 'dataframe' (pd.DataFrame), 'sst_warnings' (list),
              'stats' (dict).
    """
    def _progress(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)

    _progress(f"Fetching up to {limit} OBIS records for '{species}'...")
    occurrences = await fetch_obis_occurrences(species, limit=limit)

    if not occurrences:
        raise ValueError(f"No OBIS records found for '{species}'")

    _progress(f"Retrieved {len(occurrences)} occurrence records")

    n_absences = len(occurrences)
    _progress(f"Generating {n_absences} pseudo-absence points...")
    absences = generate_pseudo_absences(occurrences, n_absences)

    all_points = []
    for rec in occurrences:
        all_points.append({**rec, "presence": 1})
    for rec in absences:
        all_points.append({**rec, "presence": 0, "obis_sst": None, "obis_sss": None})

    _progress("Fetching environmental data from Open-Meteo...")
    sst_warnings = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    completed_count = 0
    total_points = len(all_points)

    async def _fetch_env_for_point(point, idx, client):
        """Fetch weather + marine data for a single point, guarded by semaphore."""
        nonlocal completed_count
        async with semaphore:
            weather = await fetch_historical_weather(
                point["lat"], point["lng"], point["date"], client=client
            )
            marine = await fetch_marine_conditions(
                point["lat"], point["lng"], point["date"], client=client
            )

        point["sst"] = marine.get("sea_surface_temperature")
        point["wind_speed"] = weather.get("wind_speed_10m")
        point["wind_direction"] = weather.get("wind_direction_10m")
        point["wave_height"] = marine.get("wave_height")
        point["ocean_current_velocity"] = marine.get("ocean_current_velocity")

        if point["presence"] == 1:
            validation = validate_sst(point["sst"], point.get("obis_sst"))
            point["sst_validation_ok"] = validation["ok"]
            if validation["warning"]:
                sst_warnings.append(validation["warning"])
        else:
            point["sst_validation_ok"] = True

        completed_count += 1
        if completed_count % 50 == 0:
            _progress(
                f"Processing environmental data: {completed_count}/{total_points} points..."
            )

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        tasks = [
            _fetch_env_for_point(point, i, client)
            for i, point in enumerate(all_points)
        ]
        await asyncio.gather(*tasks)

    _progress("Building aligned DataFrame...")

    df = pd.DataFrame(all_points)

    analysis_columns = [
        "presence", "lat", "lng", "month", "sst", "wind_speed",
        "wind_direction", "wave_height", "ocean_current_velocity",
        "sst_validation_ok",
    ]
    available_cols = [c for c in analysis_columns if c in df.columns]
    df = df[available_cols]

    env_cols = ["sst", "wind_speed", "wind_direction", "wave_height",
                "ocean_current_velocity"]
    available_env = [c for c in env_cols if c in df.columns]
    rows_before = len(df)
    df = df.dropna(subset=available_env)
    rows_dropped = rows_before - len(df)

    if rows_dropped > 0:
        _progress(f"Dropped {rows_dropped} rows with missing environmental data")

    _progress(f"Dataset ready: {len(df)} rows, {len(df.columns)} columns")

    stats = {
        "total_records": len(df),
        "presence_count": int(df["presence"].sum()),
        "absence_count": int((df["presence"] == 0).sum()),
        "rows_dropped": rows_dropped,
        "sst_warnings_count": len(sst_warnings),
    }

    return {
        "dataframe": df,
        "sst_warnings": sst_warnings,
        "stats": stats,
    }
