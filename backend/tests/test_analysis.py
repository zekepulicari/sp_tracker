"""Core environmental contracts, unavailable forecasts, and exact discovery ranking."""
import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock
import numpy as np
import pytest
from analysis.features import ENVIRONMENTS
from analysis.geo import validate_polygon
from analysis.discovery import rank_observations
from analysis.data_ingestion import environmental_days
from analysis.probability_model import train_model, predict

RING=[[0,0],[1,0],[1,1],[0,1],[0,0]]

def run(coro):
    return asyncio.run(coro)


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


def test_missing_forecast_not_imputed(monkeypatch):
    monkeypatch.setattr('analysis.data_ingestion.gateway.get',AsyncMock(return_value={'hourly':{}}))
    values,_=run(environmental_days(0,0,date.today(),date.today(),'terrestrial',True))
    assert all(v is None for v in values[str(date.today())].values())

def obs(id,taxon=10,day='2024-10-01',coords=None,rank='species'):
    return {'id':id,'observed_on':day,'geojson':{'coordinates':coords or [.5,.5]},'quality_grade':'research','captive':False,
        'taxon':{'id':taxon,'name':f'Species {taxon}','rank':rank,'ancestor_ids':[48460,1], 'iconic_taxon_name':'Aves'}}


def test_ranking_exact_boundary_filters_and_ties():
    rows=[obs(1,20),obs(2,10),obs(3,20,'2023-10-01'),obs(4,10,'2023-10-02'),obs(5,30,coords=[0,0]),obs(6,40,coords=[2,2]),obs(7,50,'2024-09-01')]
    rows += [rows[0],{**obs(8,60),'captive':True},{**obs(9,70),'taxon':{'id':70,'rank':'genus'}}]
    animals,count=run(rank_observations(rows,validate_polygon([RING]),10))
    assert [s['taxon_id'] for s in animals]==[10,20,30]
    assert count==5 and animals[2]['evidence_label']=='Single recorded sighting'
    assert animals[0]['years']==[2023,2024]
