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
