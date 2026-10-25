# Analysis requirements and validation diagnostics · 2026-10-25

**32 backend cases passed across exactly three maintained test files.** All seven frontend modules passed Node.js syntax checks; Python compilation and Git whitespace checks passed. The existing Starlette TestClient deprecation warning remains. Model/cache version is 2.2.1. Dependencies, container configuration, analytical thresholds, sampling, and imputation policies are unchanged; Docker was not rerun.

Regression coverage includes the public requirements contract, insufficient retained counts, incomplete predictors, concentrated sightings, unsuccessful grouped splitting, too few dates, successful holdouts, baseline failures, and preservation of chronological metrics when spatial validation is unavailable. Failed Random Forest donor eligibility preserves known aligned counts while marking final retention unevaluated. AI summaries containing unsupported statistical-inference claims fall back to deterministic explanations.

Desktop browser checks used an explicitly synthetic localhost fixture with actual model training and controlled result scenarios. They verified the fresh Historical Profile default, menu order, method explanations, shared requirement values, evidence checklists, model-unavailable states, each unavailable holdout, successful validation, and baseline failures. The chronological example displays AUC 0.508 versus baseline 0.529 and balanced accuracy 0.463 versus 0.479 while explaining why spatial validation could not run. These are controlled rendering checks, not estimates of ecological model performance. Verdicts use the existing recorded precision; the interface displays three decimals.

Refreshing during a running Environmental Outlook restored its method, explanation, request, and result. A temporary Node lifecycle diagnostic also passed all method transitions in both environments, immediate chart replacement, immutable request snapshots, comparison eligibility, failure recovery, obsolete polling errors, and task restoration. Neither temporary harness is a maintained test file. At 390 px mobile width, evidence and metric tables remained inside the panel without horizontal page overflow. The user's untracked screenshots were left untouched.

---

# Observation overlay order · 2026-10-24

Loaded iNaturalist grid tiles were hidden by Esri World Imagery: the base-layer control assigned the satellite layer z-index 2 while sightings used 1 in the same tile pane. Observations now use a dedicated, non-interactive Leaflet pane at z-index 350, above base maps and below tools, vector markers, and popups. Every species grid uses that pane, and frontend asset versions were updated.

Browser verification passed without refreshing between interactions: Otaria and Orcinus grid sightings remained visible when switching between Light map and Satellite, including species selection before and after changing the base map. Zooming into Otaria showed the capped 100-point sample; an observation popup opened above the satellite map. Point selection, polygon drawing/clearing, and zooming back to grid tiles also passed. DOM inspection confirmed a single grid pane with z-index 350 and pointer events disabled.

All six frontend modules passed Node.js syntax checks; git diff --check passed. The same three maintained test files remain unchanged. Backend tests and Docker were not rerun for this presentation-only change; queries, caches, statistical rules, credentials, and attribution were not changed. The user's untracked screenshots were left untouched.

---

# Consecutive analysis results · 2026-10-24

**21 backend cases passed across exactly three maintained test files.** All six frontend modules passed Node.js syntax checks. The existing Starlette TestClient deprecation warning remains. No endpoints, dependencies, or statistical policies changed; Docker was not rerun.

The reported Environmental Outlook requests had completed with insufficient environmental evidence: 0 usable sightings and 31 usable backgrounds. Their historical fallback was difficult to distinguish from the preceding Historical Profile. The original completed result was checked with the new renderer and now shows an explicit unavailable heading, usable counts, the 135 exclusions, and a supporting-history label.

Regression checks cover all six ordered transitions among Historical Profile, Environmental Outlook, and Key Factors in both environments, cached model isolation, seven-day comparison, missing forecasts, and insufficient-evidence fallbacks. Browser checks used a temporary, explicitly synthetic localhost fixture to verify immediate result replacement, all method transitions, unavailable headings/reasons, failure recovery, comparison eligibility after input edits, submitted-setting snapshots, refresh restoration, personal-key reruns with a non-secret dummy key, and discovery-to-species identity transfer.

A temporary Node diagnostic additionally forced an obsolete polling error to arrive during a newer run: it did not overwrite that run, clear its saved task, or release its busy state. The same diagnostic checked submission failures, immutable snapshots, and refresh restoration. Neither temporary harness is part of the maintained test suite. Screenshots in the user's untracked `screenshots/` directory were left untouched.

---

# Faster map observations · 2026-10-24

The maintained suite still has exactly **three test files**. **19 backend cases passed** after the map change; all six frontend modules passed Node.js syntax checks. The existing Starlette TestClient deprecation warning remains. Docker was not rerun; no dependencies or container settings changed.

Map browsing now selects only needed iNaturalist v2 fields. Photo details are requested on popup open and preserve the contributor attribution and license. The map and photo caches are bounded, expire after one hour, and share identical in-flight requests. Complete cached extents can satisfy contained views; capped samples cannot. A 10-second server deadline includes gateway waiting and retries; the browser stops waiting after 12 seconds and offers Retry.

Measured the same orca query around Punta Norte (`taxon_id=41521`, north `-42.02`, east `-63.68`, south `-42.14`, west `-63.86`):

| Request | Before | After |
| --- | ---: | ---: |
| JSON payload, 45 records | 17,453,447 bytes | 10,215 bytes |
| First request | 6.52 s | 1.82 s |
| Identical cached repeat | 3.50 s | 0.032 s |

These are local snapshots with live upstream data, not performance guarantees. The payload reduction is over 99.9%; source availability still affects the first uncached request. Live photo verification returned an attributed CC BY-NC photograph; no photographs were copied into the repository.

Browser verification covered Punta Norte dots, immediate loading feedback, retained points while zooming, exact empty-result wording, independent tool instructions, map Retry, popup Retry, species invalidation, and a 390 px mobile viewport. A temporary localhost-only synthetic server supplied delayed, empty, and failed responses; it is not part of the release. Its request counters confirmed zero photo requests before opening a popup, and one map request across a subsequent contained zoom. Popup automatic panning no longer triggers a point refresh that closes the popup. Responsive feedback stays above the map's attribution control.

---

# Test scope reduction · 2026-10-19

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
