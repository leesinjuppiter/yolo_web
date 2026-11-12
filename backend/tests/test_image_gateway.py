import httpx
import pytest

import public_gateway
from test_public_gateway import gateway


@pytest.mark.parametrize("path,status,content_type,expected", [
    ("/api/datasets/one/images/two/content", 200, "image/png", "private, max-age=3600"),
    ("/api/datasets/one/images/two/thumbnail", 200, "image/jpeg", "private, max-age=3600"),
    ("/api/datasets/one/images/two/content", 404, "application/json", "no-store"),
    ("/api/datasets", 200, "application/json", "no-store"),
    ("/api/changes", 200, "text/event-stream", "no-store"),
])
def test_gateway_only_allows_private_cache_for_successful_dataset_images(gateway, monkeypatch, path, status, content_type, expected):
    client, _ = gateway

    async def send(*args, **kwargs):
        return httpx.Response(status, stream=httpx.ByteStream(b"fixture"),
                              headers={"Content-Type": content_type, "Cache-Control": "private, max-age=3600"})

    monkeypatch.setattr(public_gateway.app.state.upstream, "send", send)
    response = client.get(path, auth=("test", "fixture-only"))
    assert response.status_code == status
    assert response.headers["cache-control"] == expected
    assert response.headers.get_list("cache-control") == [expected]
