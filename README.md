### Instructions

## Prerequisites

- **Python 3.9+**
- **pip** and **venv**
- **Docker** and **Docker Compose** (optional, for containerized execution)

---

## Getting Started & Installation

### Option 1: Running Locally (Virtual Environment)

1. **Create and Activate a Python Virtual Environment**:
   ```bash
   cd sp_tracker
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install Required Dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```
   > **Note**: Updating `requirements.txt` does not auto-install dependencies. Always run the `pip install` command after pulling updates to avoid `ModuleNotFoundError`.

3. **Run the Application**:
   ```bash
   cd backend
   uvicorn main:app --reload
   ```

### Option 2: Running with Docker (Recommended)

The included `Dockerfile` and `docker-compose.yml` eliminate dependency issues by packaging the backend into an isolated container.

1. **Build and Start the Container**:
   ```bash
   docker compose up -d --build
   ```
   > **Note**: Add `--build --no-cache` if you recently updated `requirements.txt`.

2. **Stop the Container**:
   ```bash
   docker compose down
   ```

---

To use the Species Tracker application, follow these steps:

1. **Launch the Application**: Run the FastAPI server in the `backend` directory using `uvicorn main:app --reload` (or `python3 -m uvicorn main:app --reload`).
2. **Open the Webpage**: Navigate your browser to `http://localhost:8000/`.
3. **Search for any Species**:
   - Use the **Target Species** search input in the Ecological Analysis Panel to search iNaturalist's database. 
   - A dropdown with species scientific names, common names, and thumbnails will appear. Select a species to automatically update the map and analysis target.
4. **Explore the Map**:
   - Drag the map to explore global regions.
   - You will see a grid layer indicating the density of the selected species' observations.
5. **Zoom for Details**:
   - Zoom in past the designated threshold (default: > 6) to transition from the grid layer to individual observation markers.
6. **View Sighting Info**:
   - Click on any specific marker to view details about that observation, including the date, photo, observer username, and location name.
7. **Ecological Analysis Panel**:
   - Select a sample size and statistical model (GLM, Random Forest, or CCA).
   - Click **Run Analysis** to fetch historical OBIS occurrences, align them with Open-Meteo environmental data, and run a Species Distribution Model.
   - Results include an **AI Interpretation Module** (using Gemini 3.1 Flash-Lite) which explains the statistical outputs in plain language, Pearson/Spearman correlation tables, VIF multicollinearity check, model coefficients, variable importance, and encounter probability.

---

### Ecological Analysis Module

The analysis module implements a full Species Distribution Modeling (SDM) pipeline:

**Data Sources (all free, no API key required except Gemini):**
- **OBIS API** (`api.obis.org/v3`) — Historical marine species occurrence records
- **Open-Meteo Historical** (`archive-api.open-meteo.com`) — Hourly temperature, wind speed/direction (back to 1940)
- **Open-Meteo Marine** (`marine-api.open-meteo.com`) — Sea surface temperature, wave height, ocean current velocity
- **Gemini API** (`gemini-3.1-flash-lite`) — Natural language analysis explanation (requires `GEMINI_KEY` in `.env`)

**Pipeline:**
1. Fetch occurrence records from OBIS
2. Generate pseudo-absence (background) points for valid SDM training
3. Fetch Open-Meteo environmental data for all points (presence + pseudo-absence)
4. Validate SST: cross-check Open-Meteo SST vs OBIS pre-computed SST (warn if Δ > 2°C)
5. Compute Pearson & Spearman correlation matrices with p-values
6. Check Variance Inflation Factor (VIF) for multicollinearity
7. Fit selected model (GLM / Random Forest / CCA) with 80/20 train/test split
8. Generate a natural language **AI interpretation** summarizing the results
9. Return encounter probability, AI interpretation, and model metrics

**Backend modules:** `backend/analysis/data_ingestion.py`, `correlation.py`, `probability_model.py`, `interpretation.py`

---

### Project Information

**External APIs & Data Sources Reference**
The application relies on the following data sources:
- **iNaturalist API**: [Documentation](https://api.inaturalist.org/v2/docs/#/Observations/get_observations)
- **OBIS (Ocean Biodiversity Information System) API**: [Documentation](https://api.obis.org/v3/)
- **Open-Meteo API**: [Documentation](https://open-meteo.com/en/docs)

**Color Palette**
The visual design uses the following color palette:
- `#DAD7CD` (Light Background)
- `#A3B18A` (Light Accent)
- `#588157` (Primary Accent / Markers)
- `#3A5A40` (Dark Accent)
- `#344E41` (Dark Background / Text)

**Icons**
- Area selector: <a href="https://www.flaticon.com/free-icons/polygonal" title="polygonal icons">Polygonal icons created by Voysla - Flaticon</a>
- Ruler: <a href="https://www.flaticon.com/free-icons/ruler" title="ruler icons">Ruler icons created by Freepik - Flaticon</a>
- Animal Tracks Icon:<a href="https://www.flaticon.com/free-icons/dog" title="dog icons">Dog icons created by Made by Made - Flaticon</a>
- Purpose target icon: <a href="https://www.flaticon.com/free-icons/objectives" title="objectives icons">Objectives icons created by sonnycandra - Flaticon</a> 
- Open book icon: <a href="https://www.flaticon.com/free-icons/book" title="book icons">Book icons created by Roundicons Premium - Flaticon</a> 
- Box resources icon: <a href="https://www.flaticon.com/free-icons/box" title="box icons">Box icons created by Pixel perfect - Flaticon</a>
- 

## Weaknesses & Limitations (Predictive Model)

While the encounter prediction model provides a powerful, data-driven approach to anticipating species presence, it is important to understand its statistical and ecological limitations:

1. **Spatial Scale & Dynamic Movement:** A prediction for a specific point relies on querying historical data within an expanded radius (e.g., 50km) to ensure enough sample size. This means the model is learning the environmental niche of a *broad area*, while applying it to a *specific point forecast*. Micro-climates and localized currents within that radius are lost.
2. **Pseudo-Absence Bias:** Because OBIS and iNaturalist only record *presence* (where someone saw an animal), our models must generate random "pseudo-absences" to perform logistic regression. This can sometimes result in the model learning the difference between "places people go" and "places people don't go" (observer bias), rather than true ecological preference.
3. **Forecast Dependency:** Short-term predictions (<= 14 days) are entirely dependent on the accuracy of the Open-Meteo weather forecast. Rapid, unforecasted weather changes will invalidate the probability calculation.
4. **Historical Average Flattening:** Long-term predictions (> 14 days) rely on historical monthly averages. This "flattens" extreme weather events that often drive significant animal movement, potentially resulting in overly conservative probability scores.

## Next steps (TO-DO):
- [ ] Have an instance of iNaturalist API saved in own cloud DB.
- [ ] Communicate with own DB via API instead of iNaturalist API.
- [ ] Escalate previous points to save information from other resources.
- [ ] Download deforestation database. Or, download tree canopy DB and calculate deforestation by time in certain area.
- [ ] Connect to Movebank API with information about animal movement: https://github.com/movebank/movebank-api-doc/blob/master/movebank-api.md 
- [ ] Add statistics module to calculate correlations between variables. For example, correlation between deforestation and number of animals in that area.
- [ ] Add information about threatened status of species.
- [ ] Download threatened species databases (IUCN).
- [X] Calculate correlation between wind, tides, current, temperature, date of observation to estimate the probability of encountering a species in certain area.
- [X] Find a way to test if the calculations are right by comparing with real data. Use the 20% of data that was left out to test if the other 80% was calculated correctly. This is not machile learning, we don't have much information to train a model.
- [ ] In the statistics module we could add a biplot with variables and species. 
- [ ] Save iNaturalist first-time-searches in local DB. Remember: do not download the images, their size is too big and is unnecesary for the purpose of this project. 
- [ ] Add loading information abut what calculations are being made when running the analysis.