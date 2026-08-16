import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx

from app.providers.openai_image import OpenAIImageProvider


@pytest.mark.asyncio
async def test_openai_provider_sends_identity_then_outfit_and_writes_png(tmp_path: Path, monkeypatch):
    identity = tmp_path / "reference_sheet.png"
    outfit = tmp_path / "theme.png"
    output = tmp_path / "shot.png"
    identity.write_bytes(b"identity")
    outfit.write_bytes(b"outfit")
    captured = {}

    class FakeImages:
        def edit(self, **kwargs):
            captured.update(kwargs)
            captured["filenames"] = [item.name for item in kwargs["image"]]
            return SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(b"png-data").decode())]
            )

    class FakeClient:
        def __init__(self, api_key):
            captured["api_key_seen"] = bool(api_key)
            self.images = FakeImages()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))
    provider = OpenAIImageProvider("test-key")
    await provider.generate_keyframe([identity], outfit, "full-body hero shot", output)

    assert output.read_bytes() == b"png-data"
    assert captured["filenames"] == [str(identity), str(outfit)]
    assert captured["model"] == "gpt-image-2"
    assert captured["size"] == "1024x1536"
    assert "Image 1 is the human identity sheet" in captured["prompt"]
    assert "Image 2 is the outfit or visual fashion theme reference" in captured["prompt"]
    assert "Transfer ONLY the wearable clothing layers" in captured["prompt"]
    assert "NEVER add a helmet, mask, horns, wings, sword" in captured["prompt"]


class FakeHttpResponse:
    def __init__(self, payload=None, content=b"", status_code=200):
        self.payload = payload
        self.content = content
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncImageClient:
    def __init__(self):
        self.payload = None
        self.polls = 0

    def post(self, url, headers=None, json=None):
        assert url == "https://kuaipao.test/v1/images/generations/async"
        assert headers["Authorization"] == "Bearer image-key"
        self.payload = json
        return FakeHttpResponse({"id": "task_img_1", "status": "queued"})

    def get(self, url, headers=None):
        if url.endswith("/images/generations/async/task_img_1"):
            self.polls += 1
            if self.polls == 1:
                return FakeHttpResponse(
                    {"id": "task_img_1", "status": "processing", "progress": 42, "data": []}
                )
            return FakeHttpResponse(
                {
                    "id": "task_img_1",
                    "status": "completed",
                    "progress": 100,
                    "data": [{"url": "https://cdn.test/keyframe.png"}],
                }
            )
        assert url == "https://cdn.test/keyframe.png"
        return FakeHttpResponse(content=b"async-png")


class FakeJsonReferenceClient:
    def __init__(self):
        self.payload = None

    def post(self, url, headers=None, json=None):
        assert url == "https://kuaipao.test/v1/images/generations"
        assert headers["Authorization"] == "Bearer image-key"
        self.payload = json
        return FakeHttpResponse(
            {"data": [{"url": "https://cdn.test/reference-keyframe.png"}]}
        )

    def get(self, url, headers=None):
        assert url == "https://cdn.test/reference-keyframe.png"
        return FakeHttpResponse(content=b"reference-png")


class FlakyJsonReferenceClient(FakeJsonReferenceClient):
    def __init__(self):
        super().__init__()
        self.posts = 0

    def post(self, url, headers=None, json=None):
        self.posts += 1
        if self.posts == 1:
            return httpx.Response(
                503,
                request=httpx.Request("POST", url),
                json={"error": "temporarily unavailable"},
            )
        return super().post(url, headers=headers, json=json)


@pytest.mark.asyncio
async def test_kuaipao_async_image_generation_polls_and_preserves_reference_order(
    tmp_path: Path,
):
    identity = tmp_path / "identity_face.png"
    outfit = tmp_path / "theme.png"
    identity.write_bytes(b"identity")
    outfit.write_bytes(b"outfit")
    output = tmp_path / "runs" / "run_1" / "keyframes" / "S01.png"
    client = FakeAsyncImageClient()
    provider = OpenAIImageProvider(
        "image-key",
        model="gpt-image-2",
        base_url="https://kuaipao.test/v1",
        async_generation=True,
        poll_interval=0,
        http_client=client,
    )

    await provider.generate_keyframe([identity], outfit, "neutral studio hero", output)

    assert output.read_bytes() == b"async-png"
    assert client.payload["model"] == "gpt-image-2"
    assert client.payload["size"] == "1024x1536"
    assert len(client.payload["image"]) == 2
    assert client.payload["image"][0].startswith("data:image/png;base64,")
    assert "Image 1 is the human identity sheet" in client.payload["prompt"]
    assert "Image 2 is the outfit or visual fashion theme reference" in client.payload["prompt"]
    request_dir = next((output.parents[1] / "image_requests").iterdir())
    request_log = (request_dir / "final_request.json").read_text(encoding="utf-8")
    assert "data:image" not in request_log
    assert (request_dir / "task_events.jsonl").exists()


@pytest.mark.asyncio
async def test_kuaipao_json_reference_route_uses_two_identity_refs_and_outfit(
    tmp_path: Path,
):
    identity_face = tmp_path / "identity_face.png"
    fullbody_front = tmp_path / "fullbody_front.png"
    fullbody_45 = tmp_path / "fullbody_45.png"
    outfit = tmp_path / "theme.png"
    for path, value in (
        (identity_face, b"face"),
        (fullbody_front, b"front"),
        (fullbody_45, b"45"),
        (outfit, b"outfit"),
    ):
        path.write_bytes(value)
    output = tmp_path / "runs" / "run_2" / "keyframes" / "S01.png"
    client = FakeJsonReferenceClient()
    provider = OpenAIImageProvider(
        "image-key",
        model="gpt-image-2-1k",
        base_url="https://kuaipao.test/v1",
        json_reference_generation=True,
        http_client=client,
    )

    await provider.generate_keyframe(
        [fullbody_45, fullbody_front, identity_face],
        outfit,
        "neutral studio hero",
        output,
    )

    assert output.read_bytes() == b"reference-png"
    assert client.payload["model"] == "gpt-image-2-1k"
    assert client.payload["quality"] == "auto"
    assert client.payload["watermark"] is False
    assert len(client.payload["image"]) == 3
    assert "Images 1 through 2" in client.payload["prompt"]
    assert "Image 3 is the outfit or visual fashion theme reference" in client.payload["prompt"]
    request_dir = next((output.parents[1] / "image_requests").iterdir())
    request = json.loads(
        (request_dir / "final_request.json").read_text(encoding="utf-8")
    )
    assert request["endpoint"] == "/images/generations"
    assert request["reference_count"] == 3


@pytest.mark.asyncio
async def test_kuaipao_json_reference_retries_temporary_503(tmp_path: Path):
    identity = tmp_path / "identity_face.png"
    outfit = tmp_path / "theme.png"
    identity.write_bytes(b"identity")
    outfit.write_bytes(b"outfit")
    output = tmp_path / "runs" / "run_3" / "keyframes" / "S05.png"
    client = FlakyJsonReferenceClient()
    provider = OpenAIImageProvider(
        "image-key",
        model="gpt-image-2-1k",
        base_url="https://kuaipao.test/v1",
        json_reference_generation=True,
        transport_backoff_seconds=0,
        http_client=client,
    )

    await provider.generate_keyframe([identity], outfit, "ending pose", output)

    assert client.posts == 2
    assert output.read_bytes() == b"reference-png"
    request_dir = next((output.parents[1] / "image_requests").iterdir())
    events = [
        json.loads(line)
        for line in (request_dir / "transport_events.jsonl").read_text().splitlines()
    ]
    assert events[0]["http_status"] == 503
    assert events[0]["status"] == "retrying"
    assert events[1]["status"] == "success"
