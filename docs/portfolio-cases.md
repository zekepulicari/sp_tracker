# Portfolio walkthroughs and verification evidence

These cases demonstrate the two environmental pipelines and their limitations. They are not evidence of calibrated wildlife encounter probabilities.

## Live marine case

- Species: **Orcinus orca**, iNaturalist taxon **41521**.
- Study point: **48.5, -123.1**, San Juan / southern Salish Sea region.
- Setting: **Marine**. Sample cap: **100**. Radius starts at **5 km** and can expand to **50 km**.
- Choose the current date, run Environmental outlook, and inspect usable sightings, exclusions, the feature contract, and both holdout comparisons. Use When should I go if a model is available; a withheld ranking is a valid outcome.

## Live terrestrial case

- Species: **Puma concolor**, iNaturalist taxon **42007**.
- Study point: **37.4, -122.2**, San Francisco Peninsula region.
- Setting: **Terrestrial**. Sample cap: **100**. Same radius policy.
- Examine Environmental outlook and Historical profile. Verify that no sea temperature, waves, or currents are required. Check whether validation improves over the seasonal baseline rather than assuming it does.

## Reproduce and save actual evidence

From the root, using the installed Python 3.12 environment:

```powershell
.\.venv\Scripts\python.exe scripts/portfolio_cases.py --live
```

This uses public data and makes **no AI requests**. It saves results, source identifiers, exclusions, source timestamps, and model diagnostics in `docs/examples/`. Expect up to roughly 600 environmental requests across the two cases. Results change as sources change; exact reproducibility of live data requires retaining the captured records and data-service versions. Source records and model seeds are retained, but these JSON files are result snapshots, not full training datasets.

**Live check on 2026-10-16:** iNaturalist returned its scheduled-maintenance page. Both saved live check files explicitly record the service unavailability and contain no validation scores. Real ecological predictive performance remains unverified. Independently, a public Open-Meteo check returned 24 historical hourly values for each of SST, waves, and currents at an ocean location on 2023-01-01.

Do not present the maintenance snapshots or synthetic examples as successful real-world forecasts. Rerun the live command when iNaturalist is available.

## Reproducible synthetic acceptance examples

```powershell
.\.venv\Scripts\python.exe scripts/portfolio_cases.py --fixtures
```

This is fully offline. It generates 240 controlled records per environmental setting with seed 42 and records actual model diagnostics in `synthetic-marine.json` and `synthetic-terrestrial.json`. The label signal is intentionally strong so the test can exercise spatial and chronological validation. These are **artificial acceptance fixtures**, not field observations, ecological validation, or performance estimates for orcas or pumas.

For a repeatable browser acceptance check when external services are unavailable:

```powershell
.\.venv\Scripts\python.exe scripts/browser_fixture_server.py --ack-synthetic
```

Open **http://127.0.0.1:8002/fixture**. The page displays a prominent synthetic-data banner. This localhost-only test server is excluded from the production image and has no AI/network calls. Search `Fixture`, select its resolved identity, choose a point and date, examine an outlook, then compare days. Switch to Animals nearby and draw around the fixture coordinates near **0.4, 0.4** to test Top 10 selection and transfer into detailed analysis.

## What to demonstrate to a reviewer

1. A boundary point counts; an outside point does not.
2. Missing data produces a limitation instead of fabricated weather or an encounter percentage.
3. Key Factors shows importance independently from forecasting.
4. A day comparison trains once and requires both holdouts to beat the same seasonal baseline.
5. Refresh preserves species identity and resumes a running job.
6. Mobile and keyboard controls remain available.
7. The image starts as a non-root user, builds without `.env`, and receives secrets only at runtime.
