from io import BytesIO

from PIL import Image

from app.core.config import data_dir
from test_dataset_api import client, dataset_url


def test_thumbnail_is_small_cached_preserves_original_and_is_removed_with_image(client, dataset_url):
    original = BytesIO()
    Image.new("RGB", (2048, 1024), "#abbccd").save(original, format="PNG")
    image = client.post(dataset_url + "/images", files={"files": ("large.png", original.getvalue(), "image/png")}).json()["images"][0]
    response = client.get(image["url"])
    assert response.content == original.getvalue()
    assert response.headers["cache-control"] == "private, max-age=3600"
    thumb_url = image["url"].removesuffix("content") + "thumbnail"
    first = client.get(thumb_url)
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert first.headers["cache-control"] == "private, max-age=3600"
    assert Image.open(BytesIO(first.content)).size == (160, 80)
    assert len(first.content) < len(original.getvalue()) / 5
    files = list((data_dir() / "thumbnails").glob("*.jpg"))
    assert len(files) == 1
    modified = files[0].stat().st_mtime_ns
    assert client.get(thumb_url).content == first.content
    assert files[0].stat().st_mtime_ns == modified
    assert client.delete(dataset_url + "/images/" + image["id"]).status_code == 204
    assert not files[0].exists()
    assert client.get(thumb_url).status_code == 404
