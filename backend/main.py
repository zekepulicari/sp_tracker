"""Validated APIs and a single-worker, bounded task service."""
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal
import math
import re
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from cachetools import TTLCache
from config import ROOT, DEFAULT_ZOOM_THRESHOLD, TAXON_ID, ALLOWED_ORIGINS, MODEL_VERSION
from jobs import Jobs, BusyError
from analysis.geo import validate_polygon, inside
from analysis.data_ingestion import INAT, parse_observation
from analysis.prediction import run_analysis as analyze
from analysis.discovery import run_discovery, GROUPS
from upstream import gateway, UpstreamError

@asynccontextmanager
async def lifespan(app):
    app.state.jobs = Jobs()
    await app.state.jobs.start()
    yield
    await app.state.jobs.stop()
    await gateway.close()

app = FastAPI(title='Species Tracker', version=MODEL_VERSION, lifespan=lifespan)
if ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-Gemini-Key'])
cache = TTLCache(maxsize=256, ttl=3600)

class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class GeoJSONPolygon(InputModel):
    type: Literal['Polygon']
    coordinates: list[list[list[float]]]

    @field_validator('coordinates')
    @classmethod
    def valid_geometry(cls, value):
        validate_polygon(value)
        return value

class PolygonRequest(InputModel):
    polygon: GeoJSONPolygon
    taxon_id: int = Field(default=TAXON_ID, gt=0)

class AnalysisRequest(InputModel):
    species: str = Field(min_length=1, max_length=200)
    taxon_id: int = Field(gt=0)
    environment: Literal['terrestrial', 'marine']
    operation: Literal['single_day', 'compare_days'] = 'single_day'
    method: Literal['glm', 'rf', 'rustic'] = 'glm'
    limit: int = Field(default=200, ge=100, le=500)
    target_lat: float = Field(ge=-90, le=90)
    target_lng: float = Field(ge=-180, le=180)
    target_date: date
    radius_km: float = Field(default=5, ge=5, le=50)

    @model_validator(mode='after')
    def compatible_operation(self):
        if self.operation == 'compare_days' and self.method != 'glm':
            raise ValueError('Day comparison uses the environmental logistic model.')
        return self

class DiscoveryRequest(InputModel):
    polygon: GeoJSONPolygon
    target_date: date
    animal_group: Literal['all', 'birds', 'mammals', 'reptiles', 'amphibians', 'fish', 'insects', 'arachnids', 'mollusks'] = 'all'

async def cached_get(path, params):
    key = (path, tuple(sorted(params.items())))
    if key not in cache:
        try:
            cache[key] = await gateway.get(f'{INAT}/{path}', params)
        except UpstreamError as exc:
            raise HTTPException(503, detail=str(exc)) from None
    return cache[key]

@app.get('/api/health')
def health_check():
    return {'status': 'ok'}

@app.get('/api/config')
def configuration():
    return {'DEFAULT_ZOOM_THRESHOLD': DEFAULT_ZOOM_THRESHOLD, 'model_version': MODEL_VERSION,
            'animal_groups': list(GROUPS), 'sample_default': 200, 'sample_max': 500}

@app.get('/api/species/search')
async def species_search(q: str = Query(min_length=0, max_length=200)):
    if len(q.strip()) < 3:
        return {'results': []}
    data = await cached_get('taxa/autocomplete', {'q': q.strip(), 'is_active': 'true'})
    return {'results': [r for r in data.get('results', []) if r.get('rank') in ('species', 'subspecies')
                        and 1 in r.get('ancestor_ids', [])][:8]}

@app.get('/api/observations')
async def observations(taxon_id: int = Query(default=TAXON_ID, gt=0),
                       nelat: float | None = Query(default=None, ge=-90, le=90),
                       nelng: float | None = Query(default=None, ge=-180, le=180),
                       swlat: float | None = Query(default=None, ge=-90, le=90),
                       swlng: float | None = Query(default=None, ge=-180, le=180)):
    bounds = [nelat, nelng, swlat, swlng]
    if any(v is not None for v in bounds) and not all(v is not None and math.isfinite(v) for v in bounds):
        raise HTTPException(422, detail='Supply all four finite bounding coordinates.')
    params = {'taxon_id': taxon_id, 'per_page': 100, 'geo': 'true', 'captive': 'false'}
    if nelat is not None:
        if nelat <= swlat or nelng <= swlng:
            raise HTTPException(422, detail='Provide a non-crossing map extent.')
        params.update(nelat=nelat, nelng=nelng, swlat=swlat, swlng=swlng)
    data = await cached_get('observations', params)
    return {**data, 'sample_cap': 100, 'complete': data.get('total_results', 0) <= 100}

@app.post('/api/observations/within')
async def observations_within(body: PolygonRequest):
    polygon = validate_polygon(body.polygon.coordinates)
    minx, miny, maxx, maxy = polygon.bounds
    data = await cached_get('observations', {'taxon_id': body.taxon_id, 'per_page': 200,
        'geo': 'true', 'captive': 'false', 'nelat': maxy, 'nelng': maxx, 'swlat': miny, 'swlng': minx})
    rows = []
    for obs in data.get('results', []):
        record = parse_observation(obs)
        if record and inside(polygon, record['lat'], record['lng']):
            rows.append(obs)
    return {'results': rows, 'sample_cap': 200, 'complete': data.get('total_results', 0) <= 200}

def submit(request, runner):
    try:
        return {'task_id': request.app.state.jobs.submit(runner)}
    except BusyError as exc:
        raise HTTPException(429, detail=str(exc), headers={'Retry-After': '10'}) from None

@app.post('/api/analysis/run')
async def start_analysis(body: AnalysisRequest, request: Request):
    # Read manually so validation errors never echo a credential back to the caller.
    api_key = request.headers.get('X-Gemini-Key')
    if api_key is not None and not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', api_key):
        raise HTTPException(422, detail='Invalid Gemini key format. Check the API Keys tab.')
    return submit(request, lambda progress: analyze(body, progress, api_key))

@app.post('/api/discovery/run')
async def start_discovery(body: DiscoveryRequest, request: Request):
    return submit(request, lambda progress: run_discovery(body, progress))

def get_task(request, task_id):
    task = request.app.state.jobs.get(task_id)
    if task is None:
        raise HTTPException(404, detail='Task unavailable. The server may have restarted; run the analysis again.')
    return task

@app.get('/api/analysis/status/{task_id}')
def status(task_id: str, request: Request):
    task = get_task(request, task_id)
    return {'task_id': task_id, **{k: task[k] for k in ('status', 'progress', 'error')}}

@app.get('/api/analysis/results/{task_id}')
def results(task_id: str, request: Request):
    task = get_task(request, task_id)
    if task['status'] == 'expired':
        raise HTTPException(410, detail='This task has expired. Run it again.')
    if task['status'] in ('queued', 'running'):
        raise HTTPException(202, detail='Analysis is not complete yet.')
    if task['status'] == 'failed':
        raise HTTPException(422, detail=task['error'])
    return task['results']

app.mount('/resources', StaticFiles(directory=ROOT / 'resources'), name='resources')
app.mount('/', StaticFiles(directory=ROOT / 'frontend', html=True), name='frontend')
