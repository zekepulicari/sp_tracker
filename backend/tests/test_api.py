"""Core API validation, task lifecycle, and personal-key isolation."""
import time
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from main import app

PAYLOAD={'species':'Puma concolor','taxon_id':42007,'environment':'terrestrial','target_lat':0,'target_lng':0,'target_date':'2026-10-16'}
RING=[[0,0],[1,0],[1,1],[0,1],[0,0]]

@pytest.mark.parametrize('change',[{'taxon_id':0},{'target_lat':91},{'environment':'unknown'}])
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


def test_personal_keys_are_scoped_to_jobs_and_never_returned(monkeypatch):
    analyze = AsyncMock(return_value={'type': 'historical_profile', 'summary': 'done'})
    monkeypatch.setattr('main.analyze', analyze)
    keys = ['personal-key-alpha', 'personal-key-beta', None]
    with TestClient(app) as client:
        for key in keys:
            headers = {'X-Gemini-Key': key} if key else {}
            task_id = client.post('/api/analysis/run', json=PAYLOAD, headers=headers).json()['task_id']
            for _ in range(100):
                response = client.get(f'/api/analysis/results/{task_id}')
                if response.status_code == 200: break
                time.sleep(.01)
            assert response.status_code == 200
            assert all(secret not in response.text for secret in keys if secret)
        assert [call.args[2] for call in analyze.call_args_list] == keys
        assert all(secret not in str(app.state.jobs.records) for secret in keys if secret)
