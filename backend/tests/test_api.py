import asyncio
import time
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from main import app, cache
from jobs import Jobs, BusyError

PAYLOAD={'species':'Puma concolor','taxon_id':42007,'environment':'terrestrial','target_lat':0,'target_lng':0,'target_date':'2026-10-16'}
RING=[[0,0],[1,0],[1,1],[0,1],[0,0]]

@pytest.mark.parametrize('change',[{'limit':99},{'limit':501},{'taxon_id':0},{'target_lat':91},{'radius_km':0},{'target_date':'bad'},{'method':'unsupported'},{'operation':'compare_days','method':'rf'},{'environment':'unknown'}])
def test_invalid_analysis_rejected_before_queue(change):
    with TestClient(app) as client:
        assert client.post('/api/analysis/run',json={**PAYLOAD,**change}).status_code==422
        assert not app.state.jobs.records

def test_analysis_and_discovery_end_to_end(monkeypatch):
    monkeypatch.setattr('main.analyze',AsyncMock(return_value={'type':'historical_profile','summary':'done'}))
    monkeypatch.setattr('main.run_discovery',AsyncMock(return_value={'type':'seasonal_discovery','species':[]}))
    with TestClient(app) as client:
        for path,payload in [('/api/analysis/run',PAYLOAD),('/api/discovery/run',{'polygon':{'type':'Polygon','coordinates':[RING]},'target_date':'2026-10-16'})]:
            response=client.post(path,json=payload)
            assert response.status_code==200
            task_id=response.json()['task_id']
            for _ in range(100):
                status=client.get(f'/api/analysis/status/{task_id}').json()['status']
                if status=='complete':break
                time.sleep(.01)
            assert status=='complete'
            assert client.get(f'/api/analysis/results/{task_id}').status_code==200

def test_queued_expired_and_restart_states():
    with TestClient(app) as client:
        jobs=app.state.jobs
        jobs.records['queued']={'status':'queued','progress':'wait','error':None,'results':None}
        assert client.get('/api/analysis/results/queued').status_code==202
        jobs.records['old']={'status':'complete','progress':'done','error':None,'results':{},'finished':time.monotonic()-86401}
        assert client.get('/api/analysis/status/old').json()['status']=='expired'
        assert client.get('/api/analysis/results/old').status_code==410
        assert client.get('/api/analysis/status/missing').status_code==404

def test_queue_limits_and_worker_bounds():
    async def scenario():
        jobs=Jobs(active=2,queued=8)
        release=asyncio.Event()
        started=0
        async def runner(progress):
            nonlocal started
            started+=1
            await release.wait()
            return {}
        await jobs.start()
        for _ in range(2):jobs.submit(runner)
        await asyncio.sleep(.01)
        for _ in range(8):jobs.submit(runner)
        with pytest.raises(BusyError):jobs.submit(runner)
        assert started==2
        release.set()
        await jobs.queue.join()
        assert all(task['status']=='complete' for task in jobs.records.values())
        await jobs.stop()
    asyncio.run(scenario())

def test_map_zero_bounds_and_exact_polygon_filter(monkeypatch):
    cache.clear()
    mocked=AsyncMock(return_value={'total_results':300,'results':[{'id':1,'observed_on':'2024-01-01','geojson':{'coordinates':[0,0]}},{'id':2,'observed_on':'2024-01-01','geojson':{'coordinates':[2,2]}}]})
    monkeypatch.setattr('main.gateway.get',mocked)
    with TestClient(app) as client:
        assert client.get('/api/observations?nelat=1&nelng=1&swlat=0&swlng=0').status_code==200
        assert mocked.call_args[0][1]['swlat']==0
        response=client.post('/api/observations/within',json={'polygon':{'type':'Polygon','coordinates':[RING]},'taxon_id':42})
        assert [r['id'] for r in response.json()['results']]==[1]
        assert not response.json()['complete']
        assert mocked.call_args[0][1]['taxon_id']==42
