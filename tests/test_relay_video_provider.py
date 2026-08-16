import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.providers.relay_video import RelayVideoProvider
from app.services.relay_config import RelayProfile


class FakeResponse:
    def __init__(self, payload=None, content=b"video-bytes", status_code=200):
        self.payload = payload
        self.content = content
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRelayClient:
    def __init__(self, protocol: str):
        self.protocol = protocol
        self.created_payload = None
        self.created_form = None
        self.created_files = None
        self.polls = 0
        self.posts = 0
        self.urls = []

    async def post(self, url, headers=None, files=None, json=None, data=None):
        self.posts += 1
        self.urls.append(url)
        if files is not None:
            if self.protocol == "kuaipao" and "input_reference" in files:
                self.created_form = data
                self.created_files = files
                return FakeResponse({"id": "task_1", "status": "queued"})
            return FakeResponse({"id": "file_1"})
        self.created_payload = json
        return FakeResponse({"id": "task_1", "status": "queued"})

    async def get(self, url, headers=None):
        self.urls.append(url)
        if "/files/file_1" in url:
            return FakeResponse({"id": "file_1", "url": "https://cdn.test/input.png"})
        if url == "https://cdn.test/input.png":
            return FakeResponse(content=b"input")
        if url == "https://cdn.test/output.mp4":
            return FakeResponse(content=b"video-bytes")
        if self.protocol == "notoken":
            return FakeResponse({"id": "task_1", "status": "succeeded", "content": {"video_url": "https://cdn.test/output.mp4"}})
        self.polls += 1
        if self.polls == 1:
            return FakeResponse({"id": "task_1", "status": "in_progress", "progress": 50})
        return FakeResponse({"id": "task_1", "status": "succeeded", "metadata": {"url": "https://cdn.test/output.mp4"}})


class ModelUnavailableClient:
    def __init__(self):
        self.posts = 0

    async def post(self, url, **_kwargs):
        self.posts += 1
        request = httpx.Request("POST", url)
        return httpx.Response(
            503,
            request=request,
            json={
                "code": "fail_to_fetch_task",
                "message": json.dumps(
                    {
                        "error": {
                            "code": "model_not_found",
                            "message": (
                                "No available channel for model sora-2-12s "
                                "under group default"
                            ),
                        }
                    }
                ),
            },
        )


def profile(protocol: str) -> RelayProfile:
    create_path = "/v1/videos" if protocol == "kuaipao" else "/api/v3/contents/generations/tasks"
    return RelayProfile(
        protocol,
        {
            "label": protocol,
            "api_root": f"https://{protocol}.test",
            "openai_base_url": f"https://{protocol}.test/v1",
            "video": {
                "protocol": protocol,
                "upload_path": "/api/v3/files/uploads",
                "file_query_path": "/api/v3/files/{file_id}",
                "create_path": create_path,
                "query_path": "/api/v3/contents/generations/tasks/{task_id}",
                "content_path": "/v1/videos/{task_id}/content",
            },
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["kuaipao", "notoken"])
async def test_relay_video_maps_each_contract_and_logs_before_request(tmp_path: Path, protocol: str):
    run_dir = tmp_path / "runs" / "run_1"
    start = run_dir / "keyframes" / "S01.png"
    start.parent.mkdir(parents=True)
    Image.new("RGB", (720, 1280), "white").save(start)
    output = run_dir / "videos" / "S01.mp4"
    output.parent.mkdir(parents=True)
    if protocol == "kuaipao":
        image_request = run_dir / "image_requests" / "S01_01_gpt-image-2"
        image_request.mkdir(parents=True)
        (image_request / "provider_response.json").write_text(
            json.dumps({"data": [{"url": "https://cdn.test/keyframe.png"}]}),
            encoding="utf-8",
        )
    client = FakeRelayClient(protocol)
    provider = RelayVideoProvider(
        "SECRET123",
        profile(protocol),
        "seedance-2.0",
        poll_interval=0,
        client=client,
    )

    await provider.generate_video(start, "same woman walks naturally", 4, output)

    assert output.read_bytes() == b"video-bytes"
    if protocol == "notoken":
        assert client.created_payload["ratio"] == "9:16"
        assert client.created_payload["content"][1]["type"] == "image_url"
    else:
        assert client.created_payload["model"] == "seedance-2.0"
        assert client.created_payload["size"] == "720x1280"
        assert client.created_payload["seconds"] == "4"
        assert client.created_payload["input_reference"] == "https://cdn.test/keyframe.png"
    request_dir = next((output.parents[1] / "video_requests").iterdir())
    assert (request_dir / "final_request.json").exists()
    assert (request_dir / "final_prompt.txt").exists()
    all_logs = "".join(path.read_text(encoding="utf-8") for path in request_dir.iterdir() if path.suffix in {".json", ".txt", ".jsonl"})
    assert "SECRET123" not in all_logs
    assert json.loads((request_dir / "final_request.json").read_text())["model"] == "seedance-2.0"


@pytest.mark.asyncio
async def test_kuaipao_recovers_accepted_task_after_local_poll_failure(tmp_path: Path):
    start = tmp_path / "runs" / "run_2" / "keyframes" / "S01.png"
    start.parent.mkdir(parents=True)
    Image.new("RGB", (720, 1280), "white").save(start)
    output = tmp_path / "runs" / "run_2" / "videos" / "S01.mp4"
    output.parent.mkdir(parents=True)
    previous = output.parents[1] / "video_requests" / "S01_01_seedance-2_0"
    previous.mkdir(parents=True)
    (previous / "provider_response.json").write_text(
        json.dumps({"id": "task_1", "status": "queued"}), encoding="utf-8"
    )
    (previous / "final_request.json").write_text(
        json.dumps({"input_transport": "provider_https_url"}), encoding="utf-8"
    )
    client = FakeRelayClient("kuaipao")
    provider = RelayVideoProvider(
        "SECRET123",
        profile("kuaipao"),
        "seedance-2.0",
        poll_interval=0,
        client=client,
    )

    await provider.generate_video(start, "same woman walks naturally", 4, output)

    assert client.posts == 0
    assert output.read_bytes() == b"video-bytes"
    resumed = output.parents[1] / "video_requests" / "S01_02_seedance-2_0" / "resumed_task.json"
    assert json.loads(resumed.read_text())["task_id"] == "task_1"


@pytest.mark.asyncio
async def test_kuaipao_sora_12s_uses_local_multipart_reference(tmp_path: Path):
    start = tmp_path / "runs" / "run_sora" / "keyframes" / "S01.png"
    start.parent.mkdir(parents=True)
    Image.new("RGB", (720, 1280), "white").save(start)
    output = tmp_path / "runs" / "run_sora" / "videos" / "S01.mp4"
    output.parent.mkdir(parents=True)
    client = FakeRelayClient("kuaipao")
    provider = RelayVideoProvider(
        "SECRET123",
        profile("kuaipao"),
        "sora-2-12s",
        poll_interval=0,
        client=client,
    )

    await provider.generate_video(start, "same woman walks naturally", 12, output)

    assert output.read_bytes() == b"video-bytes"
    assert client.created_payload is None
    assert client.created_form == {
        "model": "sora-2-12s",
        "prompt": "same woman walks naturally",
        "size": "720x1280",
        "seconds": "12",
    }
    assert "input_reference" in client.created_files
    request_dir = next((output.parents[1] / "video_requests").iterdir())
    request = json.loads((request_dir / "final_request.json").read_text())
    assert request["model_family"] == "sora"
    assert request["input_transport"] == "multipart_local_upload"


@pytest.mark.asyncio
async def test_kuaipao_model_group_error_is_readable_and_not_retried(tmp_path: Path):
    start = tmp_path / "runs" / "run_group" / "keyframes" / "S01.png"
    start.parent.mkdir(parents=True)
    Image.new("RGB", (720, 1280), "white").save(start)
    output = tmp_path / "runs" / "run_group" / "videos" / "S01.mp4"
    output.parent.mkdir(parents=True)
    client = ModelUnavailableClient()
    provider = RelayVideoProvider(
        "SECRET123",
        profile("kuaipao"),
        "sora-2-12s",
        poll_interval=0,
        client=client,
    )

    with pytest.raises(RuntimeError, match="No available channel.*group default"):
        await provider.generate_video(start, "same woman walks naturally", 12, output)

    assert client.posts == 1
