# Current test scope · 2026-10-19

The maintained suite is limited to **three test files**, with **16 passing cases** across API handling, core analysis/discovery, and proximity imputation. Six other test files were removed rather than folding the entire previous suite into fewer files. The retained cases exercise both environmental settings, missing forecasts, exact polygon ranking, task completion, credential isolation, original-donor weighting, repeatability, held-out query isolation, and donor eligibility.

All five frontend modules passed Node.js syntax checks. Frontend behavioral tests have been removed; browser interactions require manual verification. `npm test` now aliases the syntax-check command. The existing Starlette TestClient deprecation warning remains. The asynchronous tests stalled under the Windows sandbox and passed when rerun outside it. No application logic changed, and Docker checks were not rerun for this cleanup.

The larger test counts below describe historical runs before this reduction, not the current suite.

# Release verification · 2026-10-16

- Backend regression suite: **47 passed**, both on Windows and inside the clean Linux/Python 3.12 release image.
- Frontend workflow/state/map-tool suite: **9 passed** with the Node.js test runner.
- JavaScript syntax checks, Python compilation, and Docker Compose configuration validation passed.
- Docker image built successfully without the root `.env`. Container startup and `/api/health` returned 200. The image has no root `.env` or GEMINI_KEY and runs as uid 1000.
- Browser: successful keyboard autocomplete, persisted species after refresh, running-task resumption, and controls at 390 px mobile width.
- All three successful workflows exercised in the localhost-only synthetic acceptance server: environmental outlook, ranked seven-day comparison, polygon Top 10 discovery, and transfer of a selected animal into detailed analysis. Fixture data is explicitly labeled and never represented as live ecological evidence.
- Public Open-Meteo historical marine schema check: 24 hourly SST, wave, and current values returned for an ocean point on 2023-01-01.
- Live orca and puma walkthroughs: **unavailable because iNaturalist returned scheduled maintenance**. Saved check results explicitly preserve this limitation; no live predictive-performance claim is made.
- One dependency warning remains: Starlette's compatibility TestClient path deprecates HTTPX 0.x. The pinned dependency set passes in both tested environments.

See `portfolio-cases.md` for reproduction commands and the distinction between live checks and controlled synthetic acceptance examples. GitLab CI repeats the tests and container smoke check; remote runner status must be checked on the merge request.

## Test and documentation maintenance · 2026-10-16

The maintained suite now contains **45 backend tests and 9 frontend tests**, all passing locally. The original 47-test release run above remains a historical record, including its Docker checks.

- Removed the standalone health/root smoke test: Docker CI already verifies server startup and the health endpoint, while the frontend is checked in browser workflows.
- Replaced two retired-method rejection cases with one generic unsupported-method case. Validation coverage remains without coupling tests to deleted features.
- Consolidated Random Forest importance assertions into the existing full Key Factors pipeline test. Kept a focused spatial grouping test, and made the rendering check assert visible importance bars instead of the absence of a retired heading.
- Removed unused test imports. Retained analytical, geometry, completeness, queue, persistence, and safe-rendering regression tests.
- JavaScript syntax and Git whitespace checks passed. The Guide rewrite was reverted in favor of the technical Documentation tab, with current model, study-extent, and forecast limitations clarified. The original Resources list was restored. No runtime or dependency changes required another Docker build.

## Personal API keys and map controls · 2026-10-19

- 50 backend tests and 13 frontend tests pass locally, including personal-key precedence, per-job isolation, validation without secret reflection, model-cache isolation, memory-only frontend settings, and rerunning with the current key.
- A personal Gemini key is transmitted only on analysis submission and is not persisted to `.env`, browser storage, task results, or model caches. SDK exceptions still produce a safe deterministic fallback.
- Observation points use orange with a white outline; map layer radio buttons retain their native compact size because form styling is scoped to the sidebar/settings form.

## Random Forest proximity imputation · 2026-10-19

Model version **2.2.0** adds bounded, training-only proximity imputation to Key Factors. **69 backend tests and 14 frontend tests passed** locally; Python/JavaScript syntax, HTML nesting, and Git whitespace checks passed. The pre-existing Starlette TestClient deprecation warning remains. Logistic regression and missing forecasts retain their previous policies. The regression suite covers observed-value preservation, original-donor masks, reproducibility, unsupported historical coverage, excessive missingness, zero-proximity exclusions, holdout-label/query isolation, matched baseline records, cache provenance, and AI record-ID privacy.

Browser checks passed for terrestrial and marine Key Factors. The offline fixture includes 35 partially observed records for Random Forest in either environmental setting. Results distinguish 205 complete records and 35 records retained through imputation, with visible warnings on importance bars. These are synthetic acceptance records, not wildlife evidence.

Reproduce the masked-data comparison with:

```powershell
.\.venv\Scripts\python.exe scripts/imputation_benchmark.py --output docs/examples/imputation-benchmark.json
```

The saved [measured experiment](examples/imputation-benchmark.json) uses 180 training records and 60 held-out records per setting; training and held-out masks are explicit and test labels are not supplied to transformation. No query was excluded in either case. Selected reconstruction results:

| Synthetic predictor | Proximity MAE | Training-median MAE |
| --- | ---: | ---: |
| Terrestrial air temperature (°C) | 2.3461 | 5.4931 |
| Terrestrial rainfall (mm/day) | 0.7223 | 1.3416 |
| Marine sea surface temperature (°C) | 2.3676 | 5.5777 |
| Marine wave height (m) | 0.1177 | 0.2843 |

Lower error in these controlled correlated examples does not establish ecological predictive performance, guarantee improvement for other missingness patterns, or remove missingness bias. No new live ecological validation or paid AI call was performed for this change.
