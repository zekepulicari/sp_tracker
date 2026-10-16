import asyncio
import httpx
import pytest
from upstream import Gateway, UpstreamError

def check(handler):
    async def scenario():
        gate=Gateway()
        gate.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await gate.get('https://api.inaturalist.org/v1/observations')
        finally:
            await gate.close()
    return asyncio.run(scenario())

def test_maintenance_is_clear_and_not_retried():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(503,text='We are down for scheduled maintenance.')
    with pytest.raises(UpstreamError,match='scheduled maintenance'):check(handler)
    assert len(calls)==1

def test_quota_stops_immediately():
    with pytest.raises(UpstreamError,match='quota'):check(lambda request:httpx.Response(429))

def test_invalid_json_does_not_become_success():
    with pytest.raises(UpstreamError,match='incomplete'):check(lambda request:httpx.Response(200,text='not json'))
