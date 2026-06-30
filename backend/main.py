from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Any, Optional
import os
import uuid
import asyncio
import logging
import httpx
from cachetools import TTLCache
from config import INATURALIST_API, TAXON_ID, DEFAULT_ZOOM_THRESHOLD

# Analysis module imports
from analysis.data_ingestion import build_aligned_dataset
from analysis.correlation import compute_correlations, compute_vif
from analysis.probability_model import fit_glm, fit_random_forest, fit_cca
from analysis.prediction import run_prediction_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Species Tracker Backend")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

# Create a cache: max 100 items, TTL 3600 seconds
cache = TTLCache(maxsize=100, ttl=3600)

@app.get("/api/observations")
async def get_observations(nelat: float = None, nelng: float = None, swlat: float = None, swlng: float = None):
    # Base URL for iNaturalist observations
    url = f"https://api.inaturalist.org/v1/observations?taxon_id={TAXON_ID}&per_page=100"
    
    # If bounding box is provided
    if nelat and nelng and swlat and swlng:
        url += f"&nelat={nelat}&nelng={nelng}&swlat={swlat}&swlng={swlng}"
        
    # Check cache
    if url in cache:
        return cache[url]
        
    async with httpx.AsyncClient() as client:
        headers = {}
        if INATURALIST_API:
            headers["Authorization"] = f"Bearer {INATURALIST_API}"
            
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Save to cache
        cache[url] = data
        return data

@app.get("/api/config")
def get_config():
    return {
        "DEFAULT_ZOOM_THRESHOLD": DEFAULT_ZOOM_THRESHOLD
    }


# ---------------------------------------------------------------------------
# Pydantic model for polygon spatial query
# ---------------------------------------------------------------------------

class GeoJSONPolygon(BaseModel):
    type: str
    coordinates: List[Any]


class PolygonRequest(BaseModel):
    polygon: GeoJSONPolygon


def _bbox_from_polygon(coordinates: List[Any]) -> dict:
    """
    Derive the bounding box from a GeoJSON Polygon coordinate ring.
    Returns dict with keys: swlng, swlat, nelng, nelat.

    :param coordinates: Outer ring list of [lng, lat] pairs.
    :returns: Bounding box dict {swlng, swlat, nelng, nelat}.
    """
    ring = coordinates[0]  # Outer ring only
    lngs = [pt[0] for pt in ring]
    lats = [pt[1] for pt in ring]
    return {
        "swlng": min(lngs),
        "swlat": min(lats),
        "nelng": max(lngs),
        "nelat": max(lats),
    }


@app.post("/api/observations/within")
async def get_observations_within(body: PolygonRequest):
    """
    Return iNaturalist observations within the bounding box of the given GeoJSON polygon.
    The client should apply Turf.js point-in-polygon for exact filtering.

    :param body: PolygonRequest containing a GeoJSON Polygon geometry.
    :returns: iNaturalist API response dict with 'results' list.
    """
    try:
        bbox = _bbox_from_polygon(body.polygon.coordinates)
    except (IndexError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid polygon coordinates: {e}")

    url = (
        f"https://api.inaturalist.org/v1/observations"
        f"?taxon_id={TAXON_ID}&per_page=200"
        f"&nelat={bbox['nelat']}&nelng={bbox['nelng']}"
        f"&swlat={bbox['swlat']}&swlng={bbox['swlng']}"
    )

    if url in cache:
        return cache[url]

    async with httpx.AsyncClient() as client:
        headers = {}
        if INATURALIST_API:
            headers["Authorization"] = f"Bearer {INATURALIST_API}"

        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    cache[url] = data
    return data


# ---------------------------------------------------------------------------
# Analysis Module — Async task management
# ---------------------------------------------------------------------------

# In-memory store for analysis tasks (task_id -> status/results)
analysis_tasks = {}


class AnalysisRequest(BaseModel):
    species: str = "Orcinus orca"
    method: str = "glm"  # "glm", "rf", or "cca"
    limit: int = 500
    target_lat: Optional[float] = None
    target_lng: Optional[float] = None
    target_date: Optional[str] = None
    radius_km: Optional[float] = 50.0


async def _run_analysis_pipeline(task_id: str, species: str, method: str, limit: int):
    """
    Background coroutine that runs the full analysis pipeline and stores
    results in the analysis_tasks dict.
    """
    try:
        def update_progress(msg: str):
            analysis_tasks[task_id]["progress"] = msg
            logger.info("[%s] %s", task_id[:8], msg)

        analysis_tasks[task_id]["status"] = "running"

        # Step 1: Build aligned dataset
        dataset = await build_aligned_dataset(
            species=species,
            limit=limit,
            progress_callback=update_progress,
        )

        df = dataset["dataframe"]
        sst_warnings = dataset["sst_warnings"]
        stats = dataset["stats"]

        # Step 2: Compute correlations
        update_progress("Computing Pearson & Spearman correlations...")
        correlations = compute_correlations(df)

        # Step 3: Compute VIF
        update_progress("Checking multicollinearity (VIF)...")
        vif = compute_vif(df)

        # Step 4: Fit the selected model
        model_result = {}
        if method == "glm":
            update_progress("Fitting Logistic GLM...")
            model_result = fit_glm(df)
        elif method == "rf":
            update_progress("Training Random Forest (200 trees)...")
            model_result = fit_random_forest(df)
        elif method == "cca":
            update_progress("Running Canonical Correspondence Analysis...")
            model_result = fit_cca(df)
        else:
            raise ValueError(f"Unknown method: {method}")

        update_progress("Analysis complete!")

        analysis_tasks[task_id]["status"] = "complete"
        analysis_tasks[task_id]["results"] = {
            "dataset_stats": stats,
            "correlations": correlations,
            "vif": vif,
            "model": model_result,
            "sst_warnings": sst_warnings[:10],  # Cap at 10 warnings
        }

    except Exception as exc:
        logger.exception("Analysis failed for task %s", task_id)
        analysis_tasks[task_id]["status"] = "error"
        analysis_tasks[task_id]["error"] = str(exc)


@app.post("/api/analysis/run")
async def run_analysis(request: AnalysisRequest):
    """
    Start an ecological analysis as a background task.

    :param request: AnalysisRequest with species, method, and limit.
    :returns: Dict with task_id to poll for status/results.
    """
    task_id = str(uuid.uuid4())

    analysis_tasks[task_id] = {
        "status": "queued",
        "progress": "Initializing...",
        "species": request.species,
        "method": request.method,
        "limit": request.limit,
        "results": None,
        "error": None,
    }

    # Launch the pipeline as an asyncio task
    if request.target_lat is not None and request.target_lng is not None and request.target_date:
        asyncio.create_task(
            run_prediction_pipeline(task_id, request.species, request.target_lat, request.target_lng, request.target_date, request.radius_km, request.limit, analysis_tasks)
        )
    else:
        asyncio.create_task(
            _run_analysis_pipeline(task_id, request.species, request.method, request.limit)
        )

    return {"task_id": task_id}


@app.get("/api/analysis/status/{task_id}")
def get_analysis_status(task_id: str):
    """
    Check the status and progress of a running analysis task.
    """
    task = analysis_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "error": task.get("error"),
    }


@app.get("/api/analysis/results/{task_id}")
def get_analysis_results(task_id: str):
    """
    Retrieve the full results of a completed analysis task.
    """
    task = analysis_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["status"] == "running":
        raise HTTPException(status_code=202, detail="Analysis still running")

    if task["status"] == "error":
        raise HTTPException(status_code=500, detail=task.get("error", "Unknown error"))

    return task["results"]


# ---------------------------------------------------------------------------
# Static file mounts — must come LAST
# ---------------------------------------------------------------------------

# Mount resources directory (icons, images) — before frontend catch-all
resources_path = os.path.join(os.path.dirname(__file__), "..", "resources")
if os.path.exists(resources_path):
    app.mount("/resources", StaticFiles(directory=resources_path), name="resources")

# Mount frontend directory if it exists — must come LAST so API routes take priority
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
