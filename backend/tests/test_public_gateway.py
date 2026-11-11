import json

import httpx
import pytest
from fastapi.testclient import TestClient

import public_gateway


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    credential = tmp_path / "login.json"
    credential.write_text(json.dumps({"username": "test", "password": "fixture-only"}))
    monkeypatch.setenv("WORKBENCH_PUBLIC_CREDENTIALS", str(credential))
    requests = []

    def upstream(request):
        requests.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"upstream"), headers={"Content-Type": "text/plain"})

    original = httpx.AsyncClient
    monkeypatch.setattr(public_gateway.httpx, "AsyncClient", lambda **kwargs:
                        original(**kwargs, transport=httpx.MockTransport(upstream)))
    with TestClient(public_gateway.app) as client:
        yield client, requests


def test_public_gateway_protects_all_routes(gateway):
    client, requests = gateway
    for path in ("/", "/api/models", "/assets/main.js"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic")
    assert client.get("/", auth=("test", "wrong")).status_code == 401
    assert client.get("/", headers={"Authorization": "Basic invalid!"}).status_code == 401
    assert not requests


def test_public_gateway_forwards_query_and_body_without_credentials(gateway):
    client, requests = gateway
    response = client.post("/api/exports?test=1", auth=("test", "fixture-only"),
                           json={"value": 3}, headers={"Host": "vendor.example"})
    assert response.status_code == 200
    assert response.content == b"upstream"
    request = requests[0]
    assert str(request.url) == "http://127.0.0.1:5186/api/exports?test=1"
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {"value": 3}


def test_public_gateway_rejects_cross_site_changes(gateway):
    client, requests = gateway
    response = client.post("/api/exports", auth=("test", "fixture-only"),
                           headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert not requests
