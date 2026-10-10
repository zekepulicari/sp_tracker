import pytest
from fastapi.testclient import TestClient
from main import app
from unittest.mock import patch, AsyncMock, MagicMock

client = TestClient(app)

@patch("main.httpx.AsyncClient.get", new_callable=AsyncMock)
def test_get_observations(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": [{"id": 1, "taxon": {"name": "Orcinus orca"}}]}
    mock_get.return_value = mock_response

    
    # Normally we would pass bounds to the API to only get observations in the current map view
    response = client.get("/api/observations?nelat=10&nelng=10&swlat=-10&swlng=-10")
    
    assert response.status_code == 200
    assert "results" in response.json()
    assert response.json()["results"][0]["taxon"]["name"] == "Orcinus orca"


# --- Tests for POST /api/observations/within ---

# A simple square polygon around [0,0]
SAMPLE_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [-10.0, -10.0],
        [10.0,  -10.0],
        [10.0,   10.0],
        [-10.0,  10.0],
        [-10.0, -10.0]
    ]]
}


@patch("main.httpx.AsyncClient.get", new_callable=AsyncMock)
def test_observations_within_returns_results(mock_get):
    """POST /api/observations/within with a valid polygon should return results."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [{"id": 2, "taxon": {"name": "Orcinus orca"}, "geojson": {"coordinates": [0.0, 0.0]}}]
    }
    mock_get.return_value = mock_response

    response = client.post("/api/observations/within", json={"polygon": SAMPLE_POLYGON})

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 1
    assert data["results"][0]["id"] == 2


@patch("main.httpx.AsyncClient.get", new_callable=AsyncMock)
def test_observations_within_bbox_is_derived_from_polygon(mock_get):
    """The bounding box passed to iNaturalist must match the polygon's extent."""
    import main as main_module
    main_module.cache.clear()  # Ensure no cached result from previous test

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_get.return_value = mock_response

    client.post("/api/observations/within", json={"polygon": SAMPLE_POLYGON})

    assert mock_get.called, "httpx.AsyncClient.get was not called (cache may have returned early)"
    # httpx is called with the URL as a positional or keyword arg
    call_args = mock_get.call_args
    called_url: str = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "nelat=10.0" in called_url
    assert "nelng=10.0" in called_url
    assert "swlat=-10.0" in called_url
    assert "swlng=-10.0" in called_url


def test_observations_within_rejects_invalid_body():
    """POST /api/observations/within with missing polygon should return 422."""
    response = client.post("/api/observations/within", json={})
    assert response.status_code == 422


def test_analysis_run_envelope_creates_task():
    """POST /api/analysis/run with method=envelope and polygon should return task_id."""
    payload = {
        "species": "Orcinus orca",
        "method": "envelope",
        "target_date": "2026-08-01",
        "polygon": SAMPLE_POLYGON,
        "limit": 100
    }
    response = client.post("/api/analysis/run", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data

