# Development and API reference

For installation, workflows, and statistical explanations, start with the [README](../README.md). This page records implementation and operational details for contributors.

## Architecture

The Leaflet interface submits work to FastAPI. Two background workers run queued analyses; blocking model fitting and AI calls are offloaded from the event loop. iNaturalist provides sightings and taxonomy; Open-Meteo provides hourly weather/marine variables; scikit-learn fits and evaluates the classifiers. Optional Gemini explanations summarize structured evidence without controlling the analysis.

Training and prediction share feature names, units, and daily UTC aggregation. Records carry source IDs and dates; seeded backgrounds stay inside the same geodesic circle. Random Forest caches include the fitted training imputer, while request credentials and target dates stay outside cached model artifacts.

## Analysis result state

The frontend snapshots each submitted request, including its resolved species identity. Previous results are replaced by a named progress panel, and completed or unavailable results retain that submitted context even if the form changes while work is running. Existing API response shapes and statistical eligibility rules are unchanged.

Historical evidence returned instead of an environmental model is explicitly labeled as supporting evidence. Known usable sighting/background counts and grouped exclusion reasons are visible; unavailable counts are labeled as unavailable rather than invented. A seven-day comparison without ranks is explicitly unavailable while keeping its conditions and supporting evidence.

One generation token and abort controller belong to each run. Submission, status, result, and error handlers check that token before changing the UI or session task; terminal states clear polling timers and release busy controls. Refresh restores the original request snapshot and resumes polling. Personal-key reruns reuse the last submitted species request, with the current key passed separately in headers.

The day-comparison action stays visible in species controls and requires a resolved species and an applied study location; it is disabled during work or when edited coordinates have not been applied. It submits a fresh current-input snapshot with `method=glm`, `operation=compare_days`, and today's target date, switching the visible method/date accordingly. No previous analysis is required. Cache keys still enforce matching species, extent, sample size, setting, and method, so it cannot reuse an unrelated previous model. It compares the upcoming forecast week; the visit date controls single-day analysis rather than moving that week. Missing evidence and unavailable rankings remain explicit result states.

## Requirements and diagnostics

`analysis/requirements.py` defines the unchanged model, split, spatial-cell, chronological-date, and RF donor requirements. `GET /api/config` exposes them as `analysis_requirements`; the method guide and Documentation thresholds render from this configuration. Historical Profile is first and selected on fresh visits; restored tasks retain their requested method. No eligibility endpoint or pre-check workflow is added.

Results add `evidence.eligibility`, containing the requirement snapshot, processing stage, aligned/final usable counts, occupied and sighting-containing cells, and distinct dates. Uncalculated counts remain null. RF alignment counts remain known when final imputation retention is unknown. Existing evidence and metric fields remain compatible. On a failed fit, measured diagnostics survive on the exception and are copied into the result; any already-computed holdout diagnostics remain in `evidence.validation`.

`model.validation.diagnostics` records actual grouping/date coverage and candidate split counts; `unavailable_reasons` now covers insufficient cells/dates, invalid class/sample splits, and failed split fits. Existing evaluated holdout metrics and baseline criteria are unchanged. The frontend renders separate cards before the optional AI explanation, retaining the raw technical JSON. Missing diagnostics in older results are labeled as unrecorded rather than fabricated. Model/cache version 2.2.1 distinguishes these metadata additions.

Validation verdicts are deterministic. The AI evidence distinguishes unavailable holdouts from evaluated baseline failures, and the prompt forbids significance inference. AI text containing significance-inference language is conservatively rejected in favor of the deterministic summary; rejection does not imply a credential error.

Yellow outcome notices distinguish a stopped fit from limited independent validation or missing forecasts. Main importance/condition results precede the checklist and validation cards. Random Forest validation warnings explicitly preserve descriptive importance; failed holdouts never suppress its bars. Both environmental models are labeled advanced in the menu. A decorative local SVG marks Evidence explanation, whose source badge distinguishes AI from deterministic text.

## API

- `POST /api/analysis/run`: resolved `species`, positive `taxon_id`, `environment` (`terrestrial`/`marine`), `target_lat`, `target_lng`, ISO `target_date`; optional `method` (`glm`/`rf`/`rustic`), `operation` (`single_day`/`compare_days`), `limit` (100–500), and `radius_km` (5–50).
- `POST /api/discovery/run`: validated GeoJSON `polygon`, ISO `target_date`, optional `animal_group` (default `all`). No holes, self-intersections, antimeridian crossing, or more than 100 vertices.

- Species requests may include an optional `X-Gemini-Key` header for a request-scoped AI summary override. Invalid formats are rejected before queueing without reflecting the key.
- Both return `task_id`. Poll `GET /api/analysis/status/{task_id}`; fetch `GET /api/analysis/results/{task_id}` on completion.
- Job states: queued, running, complete, failed, expired. Incomplete results return 202, expired results 410, missing jobs 404, and busy queues 429. Two jobs run concurrently, eight can wait, results remain for 24 hours; a one-hour expiry tombstone permits recovery messaging. Retained task count is bounded.
- `GET /api/observations` returns a disclosed 100-record map sample with only coordinates, numeric observation ID, date, species name, observer, location, `total_results`, `sample_cap`, and `complete`. Map browsing uses iNaturalist v2 field selection; analysis and discovery keep their existing source requests.
- `GET /api/observations/{id}` accepts a positive numeric ID and returns `{id, photos}` with at most the first available photo URL, contributor attribution, and license. The browser calls this only when opening a popup.
- `POST /api/observations/within` returns exact polygon-filtered records from a disclosed 200-record sample for the requested species.
- Interactive API schemas: `/docs`. Same-origin by default; additional CORS origins must be explicitly set in `ALLOWED_ORIGINS`.

Discovery interprets `target_date` as the center of a seven-day seasonal window (±3 inclusive). Its seven month/day pairs are matched across the existing ten-year evidence period ending yesterday; this is not a recent-observations query. Separate month/day queries prevent cross-products at month/year boundaries and share the configured total record cap. Exact server filtering rechecks calendar dates and historical bounds. Cache keys include the window version and all seven calendar dates; failed/incomplete segments are never cached. Results add `seasonal_window` with full selected-year endpoints, the seven calendar dates, offsets, and version `centered-7-v1`. The legacy `month` field remains for compatibility but does not control ranking. February 29 matches only real historical leap dates; other years are not padded or shifted. Dates too close to the Python date limits are rejected before queueing. The frontend previews the inclusive range, restores it with saved tasks, and labels older monthly results explicitly. Selected-day weather remains separate from the ranking.

Map responses and photo metadata are cached for one hour in a bounded 256-entry cache. Identical in-flight requests share upstream work. A complete cached extent can cover a contained viewport; capped samples cannot. The frontend keeps up to 20 map extents and 100 popup responses for one hour. Map calls have a 10-second total server deadline, including waiting and retries, returning 504 on timeout; upstream failures return 503. The frontend enforces a 12-second request timeout and offers Retry. Neither failure is cached. Browser movement cancels obsolete requests; generation checks reject late responses. Popup auto-pans do not reload the map. Loading feedback is separate from map-tool instructions.

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
node --check frontend/observations.js
node --check frontend/diagnostics.js
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

