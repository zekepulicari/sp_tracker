from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Any
import os
import httpx
from cachetools import TTLCache
from config import INATURALIST_API, TAXON_ID, DEFAULT_ZOOM_THRESHOLD


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


# Mount resources directory (icons, images) — before frontend catch-all
resources_path = os.path.join(os.path.dirname(__file__), "..", "resources")
if os.path.exists(resources_path):
    app.mount("/resources", StaticFiles(directory=resources_path), name="resources")

# Mount frontend directory if it exists — must come LAST so API routes take priority
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

