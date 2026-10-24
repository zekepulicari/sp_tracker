"""Core API validation, task lifecycle, and personal-key isolation."""
import time
import asyncio
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from main import app
from map_observations import map_cache, map_observations, close_map_requests

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


def test_map_payload_cache_coverage_and_capped_samples(monkeypatch):
    map_cache.clear()
    row = {'id': 1, 'geojson': {'coordinates': [.5, .5]}, 'observed_on': '2024-01-01',
           'taxon': {'name': 'Example'}, 'user': {'login': 'Observer'},
           'identifications': ['unused'] * 1000, 'photos': [{'url': 'not-requested'}]}
    get = AsyncMock(return_value={'results': [row], 'total_results': 1})
    monkeypatch.setattr('map_observations.gateway.get', get)
    url = '/api/observations?taxon_id=42&nelat=1&nelng=1&swlat=0&swlng=0'
    with TestClient(app) as client:
        first = client.get(url)
        assert first.status_code == 200 and first.json()['complete']
        assert 'identifications' not in first.text and 'photos' not in first.text
        assert len(first.content) < 1000
        assert client.get(url).json() == first.json()
        empty = client.get('/api/observations?taxon_id=42&nelat=.2&nelng=.2&swlat=0&swlng=0').json()
        assert empty['results'] == [] and empty['total_results'] == 0 and empty['complete']
        assert get.await_count == 1
        upstream_url, params = get.call_args.args
        assert upstream_url == 'https://api.inaturalist.org/v2/observations'
        assert params['per_page'] == 100 and params['geo'] == 'true' and params['captive'] == 'false'
        assert 'geojson' in params['fields'] and 'photo' not in params['fields']
        map_cache.clear()
        get.return_value = {'results': [row], 'total_results': 101}
        assert not client.get(url).json()['complete']
        client.get('/api/observations?taxon_id=42&nelat=.8&nelng=.8&swlat=.2&swlng=.2')
        assert get.await_count == 3  # Capped parent results cannot satisfy a smaller extent.
        assert client.get('/api/observations?taxon_id=43&nelat=1&nelng=1&swlat=0&swlng=0').status_code == 200
        assert get.await_count == 4
    map_cache.clear()


def test_map_shared_requests_cancellation_and_deadline(monkeypatch):
    from fastapi import HTTPException
    async def scenario():
        map_cache.clear()
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(url, params):
            entered.set()
            await release.wait()
            return {'results': [], 'total_results': 0}
        get = AsyncMock(side_effect=slow)
        monkeypatch.setattr('map_observations.gateway.get', get)
        first = asyncio.create_task(map_observations(42, [1, 1, 0, 0]))
        await entered.wait()
        second = asyncio.create_task(map_observations(42, [1, 1, 0, 0]))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert (await second)['complete'] and get.await_count == 1
        map_cache.clear()
        release.clear()
        monkeypatch.setattr('map_observations.MAP_TIMEOUT', .02)
        with pytest.raises(HTTPException) as error:
            await map_observations(42, [1, 1, 0, 0])
        assert error.value.status_code == 504 and not map_cache
        release.set()
        assert (await map_observations(42, [1, 1, 0, 0]))['complete']
        assert get.await_count == 3  # A timed-out result is not cached; Retry starts fresh.
        await close_map_requests()
        map_cache.clear()
    asyncio.run(scenario())


def test_photo_details_are_small_cached_and_keep_credits(monkeypatch):
    map_cache.clear()
    get = AsyncMock(return_value={'results': [{'id': 99, 'identifications': ['unused'],
        'observation_photos': [{'position': 0, 'photo': {'url': 'https://example.com/square.jpg',
        'medium_url': 'https://example.com/medium.jpg', 'attribution': 'Original photographer', 'license_code': 'cc-by'}}]}]})
    monkeypatch.setattr('map_observations.gateway.get', get)
    with TestClient(app) as client:
        response = client.get('/api/observations/99')
        assert response.status_code == 200
        assert response.json() == {'id': 99, 'photos': [{'url': 'https://example.com/medium.jpg',
            'attribution': 'Original photographer', 'license_code': 'cc-by'}]}
        assert client.get('/api/observations/99').json() == response.json() and get.await_count == 1
        assert 'observation_photos.photo.attribution' in get.call_args.args[1]['fields']
        assert get.call_args.args[0].endswith('/v2/observations') and get.call_args.args[1]['id'] == 99
        assert client.get('/api/observations/0').status_code == 422
        get.return_value = {'results': []}
        assert client.get('/api/observations/100').status_code == 404
    map_cache.clear()
