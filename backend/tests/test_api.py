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
