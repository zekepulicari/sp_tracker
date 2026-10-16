import asyncio
from datetime import date, timedelta
import numpy as np
import pytest
from analysis.features import aggregate, seasonality, ENVIRONMENTS
from analysis.geo import validate_polygon, inside, distance_km, background_samples, polygon_area
from analysis.data_ingestion import environmental_days, fetch_observations
from analysis.probability_model import train_model, predict, split_groups
from upstream import UpstreamError, Budget
from unittest.mock import AsyncMock

RING = [[0,0],[1,0],[1,1],[0,1],[0,0]]

def run(coro):
    return asyncio.run(coro)

@pytest.mark.parametrize('coordinates', [[], [RING,RING], [[[0,0],[1,1],[0,1],[1,0],[0,0]]], [[[179,0],[-179,0],[-179,1],[179,0]]], [[[0,0],[1,0],[1,1]]], [[[0,0],[float('nan'),0],[1,1],[0,0]]]])
def test_invalid_polygons(coordinates):
    with pytest.raises(ValueError): validate_polygon(coordinates)

def test_boundary_and_geodesic_area():
    poly = validate_polygon([RING])
    assert inside(poly,0,.5) and inside(poly,0,0)
    assert not inside(poly,2,2)
    assert 12000 < polygon_area(poly) < 13000

def test_background_reproducible_and_local():
    records = [{'date':'2024-01-01'} for _ in range(100)]
    a = background_samples(records,-34,-58,5)
    assert a == background_samples(records,-34,-58,5)
    assert all(distance_km(-34,-58,p['lat'],p['lng']) <= 5.00001 for p in a)
    assert {p['date'] for p in a} == {'2024-01-01'}

def test_features_and_cyclic_seasonality():
    assert aggregate([2]*24,'precipitation') == 48
    assert aggregate([2]*24,'wind_speed') == 2
    assert aggregate([None]*24,'sst') is None
    assert aggregate([2]*23,'sst') is None
    a,b = seasonality(12),seasonality(1)
    assert np.linalg.norm(np.array(list(a.values()))-np.array(list(b.values()))) < .6

@pytest.mark.parametrize('environment',['terrestrial','marine'])
def test_history_and_forecast_have_identical_aggregation(monkeypatch, environment):
    from analysis.features import FEATURES
    values = {FEATURES[k]['variable']:[2.0]*24 for k in ENVIRONMENTS[environment]}
    async def response(url,params):
        day=params['start_date']
        return {'hourly':{'time':[f'{day}T{h:02d}:00' for h in range(24)],**values}}
    monkeypatch.setattr('analysis.data_ingestion.gateway.get',response)
    historical,_=run(environmental_days(0,0,'2024-01-01','2024-01-01',environment))
    future,_=run(environmental_days(0,0,'2024-01-01','2024-01-01',environment,True))
    assert historical == future
    assert set(historical['2024-01-01']) == set(ENVIRONMENTS[environment])
    if environment=='terrestrial': assert historical['2024-01-01']['precipitation']==48

def test_missing_forecast_not_imputed(monkeypatch):
    monkeypatch.setattr('analysis.data_ingestion.gateway.get',AsyncMock(return_value={'hourly':{}}))
    values,_=run(environmental_days(0,0,date.today(),date.today(),'terrestrial',True))
    assert all(v is None for v in values[str(date.today())].values())

def test_pagination_cap_and_partial_page(monkeypatch):
    monkeypatch.setattr('analysis.data_ingestion.gateway.get',AsyncMock(return_value={'total_results':5001,'results':[]}))
    with pytest.raises(UpstreamError,match='Narrow'):run(fetch_observations({},5000,True))
    monkeypatch.setattr('analysis.data_ingestion.gateway.get',AsyncMock(return_value={'total_results':300,'results':[{'id':1}]}))
    with pytest.raises(UpstreamError,match='incomplete'):run(fetch_observations({},5000,True))

def model_records(environment='terrestrial'):
    rng=np.random.default_rng(42)
    rows=[]
    for i in range(240):
        presence=i%2
        day=date(2023,1,1)+timedelta(days=i//2)
        row={'id':i,'presence':presence,'date':str(day),'lat':(i//2%12)*.2,'lng':(i//24)*.2}
        for k in ENVIRONMENTS[environment]:row[k]=float(10+presence*8+rng.normal(0,2))
        rows.append(row)
    return rows

@pytest.mark.parametrize('environment',['terrestrial','marine'])
def test_models_validate_and_keep_feature_contract(environment):
    model,metadata=train_model(model_records(environment),environment,'glm')
    assert metadata['validation']['spatial'] and metadata['validation']['chronological']
    assert set(metadata['bounds'])==set(ENVIRONMENTS[environment])
    values={k:15.0 for k in ENVIRONMENTS[environment]}
    prediction=predict(model,metadata,values,'2026-10-16')
    assert prediction['available'] and 0<=prediction['relative_score']<=1
    assert not predict(model,metadata,{},'2026-10-16')['available']
    values[next(iter(values))]=9999
    assert predict(model,metadata,values,'2026-10-16')['extrapolated_variables']

def test_constant_and_small_classes_rejected():
    rows=model_records()
    for row in rows:
        for key in ENVIRONMENTS['terrestrial']:row[key]=10
    with pytest.raises(ValueError,match='constant'):train_model(rows,'terrestrial','glm')
    with pytest.raises(ValueError,match='Insufficient'):train_model(rows[:10],'terrestrial','glm')

def test_spatial_groups_keep_repeated_locations_together_across_dates():
    import pandas as pd
    groups=split_groups(pd.DataFrame([
        {'lat':0.01,'lng':0.01,'date':'2023-01-01'},
        {'lat':0.01,'lng':0.01,'date':'2024-06-01'},
        {'lat':1,'lng':1,'date':'2023-01-01'},
    ]))
    assert groups[0]==groups[1]
    assert groups[0]!=groups[2]

def test_budget_limits():
    budget=Budget(daily=1)
    assert budget.reserve('example',0)==0
    with pytest.raises(UpstreamError,match='budget'):budget.reserve('example',1)
