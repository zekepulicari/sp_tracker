from fastapi.testclient import TestClient
from main import app

def test_health_check():
    with TestClient(app) as client:
        assert client.get('/api/health').json()=={'status':'ok'}
        assert client.get('/').status_code==200
