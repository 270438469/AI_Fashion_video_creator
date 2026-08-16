import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.providers.openai_video import OpenAIVideoProvider


class FakeFFmpeg:
    def __init__(self):
        self.duration = None

    async def normalize_generated_video(
        self, source: Path, output: Path, duration: float
    ) -> None:
        self.duration = duration
        output.write_bytes(b"normalized-" + source.read_bytes())


@pytest.mark.asyncio
async def test_openai_official_image_to_video_contract(tmp_path: Path):
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/videos":
            body = request.content
            captured["authorized"] = request.headers["Authorization"].startswith("Bearer ")
            captured["has_model"] = b'sora-2' in body
            captured["has_size"] = b'720x1280' in body
            captured["has_seconds"] = b'4' in body
            captured["has_reference"] = b'input_reference.png' in body
            return httpx.Response(200, json={"id": "video-1", "status": "queued"})
        if request.method == "GET" and request.url.path == "/v1/videos/video-1":
            return httpx.Response(
                200,
                json={"id": "video-1", "status": "completed", "progress": 100},
            )
        if request.method == "GET" and request.url.path == "/v1/videos/video-1/content":
            return httpx.Response(200, content=b"video-bytes")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    frame = tmp_path / "frame.png"
    output = tmp_path / "run" / "videos" / "S01.mp4"
    output.parent.mkdir(parents=True)
    Image.new("RGB", (1024, 1536), "#ddd7d0").save(frame)
    ffmpeg = FakeFFmpeg()
    provider = OpenAIVideoProvider(
        "test-openai-key",
        model="sora-2",
        poll_interval=0,
        client=client,
        ffmpeg=ffmpeg,
    )

    await provider.generate_video(frame, "same woman walking in a daily cafe", 3, output)
    await client.aclose()

    assert output.read_bytes() == b"normalized-video-bytes"
    assert captured == {
        "authorized": True,
        "has_model": True,
        "has_size": True,
        "has_seconds": True,
        "has_reference": True,
    }
    assert ffmpeg.duration == 3
    attempt = next((output.parents[1] / "video_requests").iterdir())
    request_log = json.loads((attempt / "final_request.json").read_text(encoding="utf-8"))
    assert request_log["model"] == "sora-2"
    assert "test-openai-key" not in str(request_log)
