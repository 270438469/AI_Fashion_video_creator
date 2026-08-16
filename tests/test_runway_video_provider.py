import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.providers.runway_video import RunwayVideoProvider


class FakeFFmpeg:
    def __init__(self):
        self.duration = None

    async def normalize_generated_video(self, source: Path, output: Path, duration: float):
        self.duration = duration
        output.write_bytes(b"normalized-" + source.read_bytes())


@pytest.mark.asyncio
async def test_runway_seedance_image_to_video_contract(tmp_path: Path):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/image_to_video"):
            captured.update(json.loads(request.content))
            captured["version"] = request.headers["X-Runway-Version"]
            captured["authorized"] = request.headers["Authorization"].startswith("Bearer ")
            return httpx.Response(200, json={"id": "task-1"})
        if request.url.path.endswith("/tasks/task-1"):
            return httpx.Response(
                200,
                json={"id": "task-1", "status": "SUCCEEDED", "output": ["https://media.test/clip.mp4"]},
            )
        if request.url.host == "media.test":
            return httpx.Response(200, content=b"video-bytes")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    frame = tmp_path / "frame.png"
    output = tmp_path / "clip.mp4"
    Image.new("RGB", (360, 640), "#ddd7d0").save(frame)
    ffmpeg = FakeFFmpeg()
    provider = RunwayVideoProvider(
        "test-secret", model="seedance2", poll_interval=0, client=client, ffmpeg=ffmpeg
    )

    await provider.generate_video(frame, "locked outfit in a daily cafe", 3, output)
    await client.aclose()

    assert output.read_bytes() == b"normalized-video-bytes"
    assert captured["model"] == "seedance2"
    assert captured["ratio"] == "720:1280"
    assert captured["duration"] == 4
    assert ffmpeg.duration == 3
    assert captured["promptImage"].startswith("data:image/jpeg;base64,")
    assert captured["version"] == "2024-11-06"
    assert captured["authorized"] is True
