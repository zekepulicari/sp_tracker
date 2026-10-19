# Species Tracker

A focused wildlife visit planner: discover seasonal animals in a drawn area, examine environmental evidence for one species, and compare supported upcoming days. Marine and terrestrial settings are explicit.

Results describe **historical recording frequency and relative modeled favorability**, never calibrated encounter probabilities. More observations can reflect observer effort, accessibility, or detectability rather than more animals.

## Run locally

Use Python **3.12**. From the project root on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

On macOS/Linux, use `.venv/bin/python` instead. Open http://127.0.0.1:8000/.

No credentials are required for core discovery and analysis. For optional AI summaries, copy `.env.example` to `.env` and set `GEMINI_KEY` locally. The root `.env` loads on startup; process environment variables override it. Restart after changing configuration. Never commit `.env`.

The **API Keys** tab lets each visitor apply a personal Gemini key and rerun their last species analysis immediately. The key overrides the server default only for their submitted requests. It stays in page memory (cleared by refresh/closing the tab), travels in the `X-Gemini-Key` header to the backend, and is passed explicitly to the Google SDK. It is not written to browser storage, task results, model caches, or `.env`. Use HTTPS outside localhost; do not log request headers in your hosting proxy. Removing a personal key restores the server default for future requests; queued jobs keep their original key. Google validates key permissions/quota during summary generation; failure preserves statistical results. iNaturalist and Open-Meteo need no user keys in this release.

## Run with Docker

```sh
docker compose up --build -d
docker compose down
```

Docker Desktop/Engine must be running. A recent Docker Compose supports optional `env_file`. Images build without `.env`; credentials are injected at runtime and excluded from the build context. The image runs as an unprivileged user with one Uvicorn worker. Compose binds localhost by default. Public hosting should use HTTPS through a reverse proxy with a request/body-size limit.

## Three workflows

1. **Animals nearby:** draw 3–100 vertices, click the first point or press Enter to close, choose a date and animal group, then find up to ten species. Escape cancels drawing without deleting the last completed area. Use Clear area to remove it.
2. **Species outlook:** select a resolved animal from autocomplete, explicitly choose Terrestrial or Marine, then choose a point/date and examine evidence. Coordinates are also available for keyboard users. Historical Profile shows monthly sightings; Key Factors displays Random Forest importance.
3. **When should I go?:** after an environmental logistic analysis with a usable model, compare up to seven supported days using that same model. Ranking is withheld if independent validation does not beat the seasonal baseline or conditions fall outside the training range.

The browser remembers the last selected species and environmental setting. An active job resumes after refresh in the same browser tab. Server restarts remove in-memory jobs; the UI explains how to restart the request.

## Evidence contracts

- Sightings: iNaturalist research-grade, georeferenced, non-captive observations over the preceding ten years ending yesterday. Discovery fetches complete bounding-box records and applies exact server-side polygon filtering, including edges. Above `DISCOVERY_CAP` (default 5,000), it requests a smaller area instead of ranking an incomplete dataset.
- Ranking: sightings, then distinct observation dates, then taxon ID. Subspecies consolidate under species. Unresolved higher taxa are excluded. The selected **month**, not the particular day, determines historical ranking. Weather is separate context at a point inside the polygon.
- Local analysis: a geodesic circle starts at 5 km and expands to at most 50 km. The latest up-to-200 sightings are used by default (100–500 permitted). Capped samples and unusable records are disclosed. Seeded background samples remain within the same study circle; they are not confirmed absences.
- Terrestrial: daily mean air temperature/wind, daily total precipitation, cyclic month sine/cosine. Marine: daily mean SST/wind/waves/currents plus cyclic seasonality. Historical and forecast values share the same hourly-to-daily UTC aggregation; all 24 hours are required. No air-temperature SST proxy or forecast imputation is used. Logistic regression retains complete historical records only. Random Forest uses training-only proximity imputation for eligible partial historical records (details below).
- Coverage: historical marine SST/current requests start January 2022; archived weather has a five-day guard for publication lag. Forecast requests use a conservative window and require complete returned values. Unsupported dates show historical profiles without synthetic weather. Data resolution and coastal cells can limit interpretation.
- Validation: 0.1-degree latitude/longitude cells are held together (physical width varies with latitude); a separate chronological holdout evaluates later dates where viable. Both compare with a cyclic seasonality-only model on identical splits. All results remain presence/background classifiers, even when holdout diagnostics are good. Environmental predictors must vary, values must be finite, and enough records from both classes must exist.
- AI: the supported Google Gen AI SDK summarizes structured evidence, with a request timeout and deterministic fallback. Exact locations and source records are not sent to the AI. The evidence and warnings remain authoritative.

## Random Forest proximity imputation

Key Factors defaults to proximity-based historical imputation. Records missing more than half their environmental predictors, invalid coordinates/dates, or known unsupported dates are excluded; marine records need at least one observed marine variable. Each training predictor needs 15 original observed donors, two distinct values, and no more than 50% missingness. The existing 40-record/15-per-class minimum still applies after exclusions.

Missing cells are initialized with training medians, then updated for five iterations using 200-tree, depth-8 forests with minimum leaf size 3 and seed 42. Proximity is the fraction of shared terminal leaves. Each estimate is a proximity-weighted mean of originally observed values of that predictor, never previous estimates. Unresolved records are removed and training imputation restarts without them as donors (at most five restarts); failure to stabilize returns insufficient evidence. Median initialization is not a fallback result. Processing is capped at 1,000 records, accumulating one tree at a time rather than a three-dimensional proximity tensor.

Spatial and chronological splits happen before donor/median/forest fitting. Held-out records transform independently using only original training donors and a fixed fitted training forest. The seasonal baseline uses exactly the same retained records. Final model metadata includes imputation parameters, donor counts, observed/estimated cell counts, complete/imputed record counts, exclusions, and original per-record masks and estimates. Evidence and importance bars identify estimated inputs. AI receives aggregate imputation diagnostics without source IDs or record values. Cached artifacts omit target dates and credentials; model version 2.2.0 separates these results from earlier models.

This retains partial evidence without claiming better accuracy or eliminating missingness bias. Logistic regression and unavailable forecasts keep their previous policies. Run the reproducible masked-data experiment with `.venv/Scripts/python.exe scripts/imputation_benchmark.py`; it compares held-out reconstruction MAE against training-median filling on explicitly synthetic data.

## API

- `POST /api/analysis/run`: resolved `species`, positive `taxon_id`, `environment` (`terrestrial`/`marine`), `target_lat`, `target_lng`, ISO `target_date`; optional `method` (`glm`/`rf`/`rustic`), `operation` (`single_day`/`compare_days`), `limit` (100–500), and `radius_km` (5–50).
- `POST /api/discovery/run`: validated GeoJSON `polygon`, ISO `target_date`, optional `animal_group` (default `all`). No holes, self-intersections, antimeridian crossing, or more than 100 vertices.
- Species requests may include an optional `X-Gemini-Key` header for a request-scoped AI summary override. Invalid formats are rejected before queueing without reflecting the key.
- Both return `task_id`. Poll `GET /api/analysis/status/{task_id}`; fetch `GET /api/analysis/results/{task_id}` on completion.
- Job states: queued, running, complete, failed, expired. Incomplete results return 202, expired results 410, missing jobs 404, and busy queues 429. Two jobs run concurrently, eight can wait, results remain for 24 hours; a one-hour expiry tombstone permits recovery messaging. Retained task count is bounded.
- `GET /api/observations` returns a disclosed 100-record map sample. `POST /api/observations/within` returns exact polygon-filtered records from a disclosed 200-record sample for the requested species.
- Interactive API schemas: `/docs`. Same-origin by default; additional CORS origins must be explicitly set in `ALLOWED_ORIGINS`.

The shared gateway bounds upstream concurrency, enforces per-service rolling request and daily budgets, uses timeouts, and retries transient network/server failures at most twice. Quota errors stop the request. Completed discovery evidence is cached for 24 hours; trained local models for one hour.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/*.test.mjs
npm run check
docker compose config --quiet
docker build -t species-tracker:check .
```

Node.js 20+ is needed only for frontend tests; no npm dependencies or frontend build step are required. GitLab CI runs backend/frontend checks and a Docker build/startup check. The Docker job requires a runner supporting privileged Docker-in-Docker.

See [portfolio cases](docs/portfolio-cases.md) for marine and terrestrial walkthroughs and reproducible source evidence. The backend tests mock external APIs; live cases are separate and never run in ordinary CI. Tests cover geometry, full-query discovery, source feature contracts, model validation, queue limits, refresh recovery, selected identity, and safe rendering. Keep tests tied to these behavioral contracts; avoid assertions about retired UI labels or one-off release artifacts. The Docker CI startup check covers the health endpoint, so the backend suite does not duplicate that smoke check.

## Project layout

- `backend/analysis/`: feature definitions, WGS84 geometry, ingestion, classifiers, prediction, discovery, and optional summaries.
- `backend/main.py`, `jobs.py`, `upstream.py`: validation/routing, bounded jobs, and upstream budgets.
- `frontend/`: plain JavaScript modules, Leaflet map/tools, accessible controls, and safe result rendering.
- `backend/tests/`, `tests/`: analytical/API and frontend workflow regression tests.

The old CCA approximation, habitat-envelope score, OBIS pipeline, and unrelated future-platform scaffolding have been retired. This release intentionally stays focused on wildlife visit planning.

## Sources and credits

[iNaturalist API](https://api.inaturalist.org/v1/docs/), [Open-Meteo Weather](https://open-meteo.com/en/docs), [Open-Meteo Marine](https://open-meteo.com/en/docs/marine-weather-api). Observation images remain remote and retain contributor attribution and licenses. Basemaps: OpenStreetMap contributors and Esri World Imagery. Track icon by Made by Made through Flaticon. The in-app Resources page lists all runtime libraries and their documentation.
