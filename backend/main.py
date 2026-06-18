from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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


# Mount frontend directory if it exists
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
