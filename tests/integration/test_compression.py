import pytest
from starlette.testclient import TestClient
from src.api.main import create_app

@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

def test_gzip_compression_enabled(client):
    headers = {"Accept-Encoding": "gzip"}
    res = client.get("/", headers=headers)
    assert res.status_code == 200
    assert res.headers.get("Content-Encoding") == "gzip"

