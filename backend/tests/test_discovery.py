import asyncio
from datetime import date
from unittest.mock import AsyncMock
import pytest
from main import DiscoveryRequest
from analysis.discovery import rank_observations, run_discovery, history_cache, taxa_cache
from analysis.geo import validate_polygon
from analysis.data_ingestion import fetch_observations
from upstream import UpstreamError

RING=[[0,0],[1,0],[1,1],[0,1],[0,0]]

def obs(id,taxon=10,day='2024-10-01',coords=None,rank='species'):
    return {'id':id,'observed_on':day,'geojson':{'coordinates':coords or [.5,.5]},'quality_grade':'research','captive':False,
        'taxon':{'id':taxon,'name':f'Species {taxon}','rank':rank,'ancestor_ids':[48460,1], 'iconic_taxon_name':'Aves'}}

def run(coro):return asyncio.run(coro)

def test_ranking_exact_boundary_filters_and_ties():
    rows=[obs(1,20),obs(2,10),obs(3,20,'2023-10-01'),obs(4,10,'2023-10-02'),obs(5,30,coords=[0,0]),obs(6,40,coords=[2,2]),obs(7,50,'2024-09-01')]
    rows += [rows[0],{**obs(8,60),'captive':True},{**obs(9,70),'taxon':{'id':70,'rank':'genus'}}]
    animals,count=run(rank_observations(rows,validate_polygon([RING]),10))
    assert [s['taxon_id'] for s in animals]==[10,20,30]
    assert count==5 and animals[2]['evidence_label']=='Single recorded sighting'
    assert animals[0]['years']==[2023,2024]

def test_subspecies_consolidation(monkeypatch):
    taxa_cache.clear()
    monkeypatch.setattr('analysis.discovery.gateway.get',AsyncMock(return_value={'results':[{'ancestors':[{'id':10,'name':'Parent species','rank':'species'}]}]}))
    animals,count=run(rank_observations([obs(1,10),obs(2,11,rank='subspecies')],validate_polygon([RING]),10))
    assert len(animals)==1 and animals[0]['count']==2

def test_group_filter_and_top_ten():
    rows=[obs(i,i+10) for i in range(1,15)]
    animals,count=run(rank_observations(rows,validate_polygon([RING]),10,'mammals'))
    assert animals==[]
    assert len(run(rank_observations(rows,validate_polygon([RING]),10))[0])==10

def test_same_month_cached_ranking_and_empty_weather(monkeypatch):
    history_cache.clear()
    fetch=AsyncMock(return_value=([obs(1)],1,True))
    monkeypatch.setattr('analysis.discovery.fetch_observations',fetch)
    monkeypatch.setattr('analysis.discovery.environmental_days',AsyncMock(side_effect=UpstreamError('unavailable')))
    def request(day):return DiscoveryRequest(polygon={'type':'Polygon','coordinates':[RING]},target_date=day)
    result=run(run_discovery(request('2030-10-01'),lambda _:None))
    other=run(run_discovery(request('2030-10-15'),lambda _:None))
    assert result['species']==other['species'] and fetch.call_count==1
    assert not result['weather']['available']
    history_cache.clear()
    monkeypatch.setattr('analysis.discovery.fetch_observations',AsyncMock(return_value=([],0,True)))
    empty=run(run_discovery(request('2030-10-01'),lambda _:None))
    assert empty['species']==[] and 'does not mean' in empty['summary']

def test_interrupted_pagination_does_not_cache(monkeypatch):
    history_cache.clear()
    monkeypatch.setattr('analysis.discovery.fetch_observations',AsyncMock(side_effect=UpstreamError('incomplete')))
    request=DiscoveryRequest(polygon={'type':'Polygon','coordinates':[RING]},target_date='2030-10-01')
    with pytest.raises(UpstreamError):run(run_discovery(request,lambda _:None))
    assert len(history_cache)==0
