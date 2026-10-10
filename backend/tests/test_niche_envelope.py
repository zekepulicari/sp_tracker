import pytest
from analysis.niche_envelope import (
    compute_polygon_centroid,
    compute_niche_envelope,
    evaluate_niche_viability,
)

def test_compute_polygon_centroid():
    polygon_ring = [
        [-6.0, 35.0],
        [-5.0, 35.0],
        [-5.0, 37.0],
        [-6.0, 37.0],
        [-6.0, 35.0]
    ]
    lat, lng = compute_polygon_centroid(polygon_ring)
    assert round(lat, 2) == 36.0
    assert round(lng, 2) == -5.5

def test_compute_niche_envelope():
    records = [
        {"sst": 16.0, "wind_speed": 10.0, "wave_height": 1.0, "ocean_current": 0.2},
        {"sst": 18.0, "wind_speed": 15.0, "wave_height": 1.5, "ocean_current": 0.4},
        {"sst": 20.0, "wind_speed": 20.0, "wave_height": 2.0, "ocean_current": 0.6},
        {"sst": 22.0, "wind_speed": 25.0, "wave_height": 2.5, "ocean_current": 0.8},
        {"sst": 24.0, "wind_speed": 30.0, "wave_height": 3.0, "ocean_current": 1.0},
    ]
    envelope = compute_niche_envelope(records)
    
    assert "sst" in envelope
    assert envelope["sst"]["min"] == 16.0
    assert envelope["sst"]["max"] == 24.0
    assert envelope["sst"]["median"] == 20.0
    assert envelope["wind_speed"]["min"] == 10.0
    assert envelope["wind_speed"]["max"] == 30.0

def test_evaluate_niche_viability_optimal():
    envelope = {
        "sst": {"min": 15.0, "p10": 17.0, "median": 20.0, "p90": 23.0, "max": 25.0},
        "wind_speed": {"min": 5.0, "p10": 10.0, "median": 18.0, "p90": 26.0, "max": 35.0},
        "wave_height": {"min": 0.5, "p10": 1.0, "median": 1.8, "p90": 2.6, "max": 4.0},
        "ocean_current": {"min": 0.1, "p10": 0.2, "median": 0.5, "p90": 0.8, "max": 1.2},
    }
    forecast = {
        "sst": 20.0,
        "wind_speed": 18.0,
        "wave_height": 1.8,
        "ocean_current": 0.5,
    }
    result = evaluate_niche_viability(envelope, forecast)
    assert result["viability_score"] >= 90.0
    assert result["status"] == "Optimal"
    assert len(result["limiting_factors"]) == 0

def test_evaluate_niche_viability_hostile_extreme():
    envelope = {
        "sst": {"min": 15.0, "p10": 17.0, "median": 20.0, "p90": 23.0, "max": 25.0},
        "wind_speed": {"min": 5.0, "p10": 10.0, "median": 18.0, "p90": 26.0, "max": 35.0},
    }
    forecast = {
        "sst": 33.0,
        "wind_speed": 60.0,
    }
    result = evaluate_niche_viability(envelope, forecast)
    assert result["viability_score"] < 40.0
    assert result["status"] in ["Suboptimal", "Unsuitable"]
    assert "sst" in [f["variable"] for f in result["limiting_factors"]]
