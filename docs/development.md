# Development and API reference

For installation, workflows, and statistical explanations, start with the [README](../README.md). This page records implementation and operational details for contributors.

## Architecture

The Leaflet interface submits work to FastAPI. Two background workers run queued analyses; blocking model fitting and AI calls are offloaded from the event loop. iNaturalist provides sightings and taxonomy; Open-Meteo provides hourly weather/marine variables; scikit-learn fits and evaluates the classifiers. Optional Gemini explanations summarize structured evidence without controlling the analysis.

Training and prediction share feature names, units, and daily UTC aggregation. Records carry source IDs and dates; seeded backgrounds stay inside the same geodesic circle. Random Forest caches include the fitted training imputer, while request credentials and target dates stay outside cached model artifacts.

## API

- `POST /api/analysis/run`: resolved `species`, positive `taxon_id`, `environment` (`terrestrial`/`marine`), `target_lat`, `target_lng`, ISO `target_date`; optional `method` (`glm`/`rf`/`rustic`), `operation` (`single_day`/`compare_days`), `limit` (100–500), and `radius_km` (5–50).
- `POST /api/discovery/run`: validated GeoJSON `polygon`, ISO `target_date`, optional `animal_group` (default `all`). No holes, self-intersections, antimeridian crossing, or more than 100 vertices.
- Species requests may include an optional `X-Gemini-Key` header for a request-scoped AI summary override. Invalid formats are rejected before queueing without reflecting the key.
- Both return `task_id`. Poll `GET /api/analysis/status/{task_id}`; fetch `GET /api/analysis/results/{task_id}` on completion.
- Job states: queued, running, complete, failed, expired. Incomplete results return 202, expired results 410, missing jobs 404, and busy queues 429. Two jobs run concurrently, eight can wait, results remain for 24 hours; a one-hour expiry tombstone permits recovery messaging. Retained task count is bounded.
- `GET /api/observations` returns a disclosed 100-record map sample. `POST /api/observations/within` returns exact polygon-filtered records from a disclosed 200-record sample for the requested species.
- Interactive API schemas: `/docs`. Same-origin by default; additional CORS origins must be explicitly set in `ALLOWED_ORIGINS`.

The shared gateway bounds upstream concurrency, enforces per-service rolling request and daily budgets, uses timeouts, and retries transient network/server failures at most twice. Quota errors stop the request. Completed discovery evidence is cached for 24 hours; trained local models for one hour.

## Configuration

Root `.env` loading happens on startup. Existing process environment variables take precedence. Restart the Python server, or recreate the Docker container, after changing startup configuration.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_KEY` | Empty | Optional server-default Gemini credential. |
| `GEMINI_MODEL` | See `.env.example` | Model used for optional explanations. |
| `ALLOWED_ORIGINS` | Empty | Explicit comma-separated additional CORS origins; same-origin access is the default. |
| `DISCOVERY_CAP` | `5000` | Maximum complete bounding-box observation query for discovery. |
| `UPSTREAM_DAILY_BUDGET` | `6000` | Shared daily request allowance per upstream service. |
| `DEFAULT_ZOOM_THRESHOLD` | `6` | Value exposed in app configuration; the current frontend switches map layers at zoom 6. |

Personal API keys are sent only in `X-Gemini-Key` on species-analysis submission and passed explicitly to the Google SDK. They override the server default for that job only, stay out of task results/model caches, and are released with the queued runner. Removing a key in the UI affects future submissions. HTTPS is required outside localhost for the personal-key UI; production proxies must not log credential headers.

## Tests and deployment checks

From the repository root after installing the pinned Python dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check frontend/app.js
node --check frontend/analysis.js
node --check frontend/tools.js
node --check frontend/state.js
node --check frontend/settings.js
docker compose config --quiet
docker build -t species-tracker:check .
```

Node.js 20+ is only needed for frontend checks. No npm dependencies or frontend build step are required. `npm test` and `npm run check` are equivalent convenience scripts when npm is available. The retained GitLab CI configuration repeats backend tests, frontend syntax checks, and Docker build/startup verification; its Docker job requires a runner supporting privileged Docker-in-Docker. It does not run automatically on GitHub. See [dated validation evidence](validation.md) for what has actually been exercised.

Backend tests mock external services; ordinary CI does not consume live ecological API or Gemini quotas. Keep exactly three focused test files: `test_api.py` for request validation, task completion, and per-job credential isolation; `test_analysis.py` for environmental model contracts, missing forecasts, and polygon discovery ranking; and `test_imputation.py` for observed-donor weighting, repeatability, held-out query isolation, and donor eligibility. Frontend verification is limited to syntax checks; interactive behavior needs manual browser verification. The Docker startup check covers the health endpoint.

The Docker image uses Python 3.12, a non-root user, and one Uvicorn process. Keep one application process for this in-memory task queue; adding multiple processes requires a shared task store. The Compose service binds localhost. Public deployments need HTTPS and a reverse proxy with an appropriate request/body-size limit. Images exclude `.env`; credentials are supplied at runtime.

## Project layout

- `backend/analysis/`: feature definitions, WGS84 geometry, ingestion, classifiers, prediction, discovery, and optional summaries.
- `backend/main.py`, `jobs.py`, `upstream.py`: validation/routing, bounded jobs, and upstream budgets.
- `frontend/`: plain JavaScript modules, Leaflet map/tools, accessible controls, and safe result rendering.
- `backend/tests/`: the three maintained API, analysis, and imputation test files.

