from pathlib import Path

from app.api.dependencies import build_container
from app.config import Settings
from app.providers.relay_video import RelayVideoProvider
from app.services.relay_config import RelaySelection


def test_runtime_uses_three_independent_provider_keys(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    container = build_container(
        Settings(
            workspace_dir=tmp_path / "workspace",
            character_dir=root / "characters",
            provider_mode="mock",
            vision_provider="mock",
            image_provider="mock",
            video_provider="mock",
            allow_mock_generation=True,
        )
    )
    container.relay_config.save(
        RelaySelection(
            vision_provider_id="kuaipao",
            vision_model="gpt-5.6-sol",
            image_provider_id="openai",
            image_model="gpt-image-2",
            video_provider_id="notoken",
            video_model="seedance-2.0",
        )
    )
    container.relay_config.set_api_key("vision", "kuaipao", "vision-only-key")
    container.relay_config.set_api_key("image", "openai", "image-only-key")
    container.relay_config.set_api_key("video", "notoken", "video-only-key")

    container.provider_manager.apply()

    vision = container.orchestrator.analyzer.provider
    image = container.orchestrator.image_provider
    video = container.orchestrator.video_provider
    assert vision.api_key == "vision-only-key"
    assert vision.base_url == "https://kuaipao.pro/v1"
    assert image.api_key == "image-only-key"
    assert image.base_url == "https://api.openai.com/v1"
    assert isinstance(video, RelayVideoProvider)
    assert video.api_key == "video-only-key"
    assert video.profile.relay_id == "notoken"


class _ModelResponse:
    status_code = 200

    def __init__(self, models: list[str]):
        self.models = models

    def json(self):
        return {"object": "list", "data": [{"id": model} for model in self.models]}


class _ModelClient:
    def __init__(self, models: list[str]):
        self.models = models

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _url, headers=None):
        assert headers and headers["Authorization"].startswith("Bearer ")
        return _ModelResponse(self.models)


def _three_kuaipao_container(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    container = build_container(
        Settings(
            workspace_dir=tmp_path / "workspace",
            character_dir=root / "characters",
            provider_mode="mock",
            vision_provider="mock",
            image_provider="mock",
            video_provider="mock",
            allow_mock_generation=True,
        )
    )
    selection = RelaySelection()
    container.relay_config.save(selection)
    for capability in ("vision", "image", "video"):
        container.relay_config.set_api_key(
            capability, selection.provider_id(capability), f"{capability}-key"
        )
    return container


async def test_connection_rejects_key_group_without_selected_model(
    tmp_path: Path, monkeypatch
):
    container = _three_kuaipao_container(tmp_path)
    video_only_models = ["doubao-seedance-2.0-mini-720p"]
    monkeypatch.setattr(
        "app.services.provider_manager.httpx.AsyncClient",
        lambda **_kwargs: _ModelClient(video_only_models),
    )

    result = await container.provider_manager.test_connection(capability="vision")

    assert result["connected"] is False
    assert result["capability"] == "vision"
    assert result["model"] == "gpt-5.6-sol"
    assert "所属模型分组不包含 gpt-5.6-sol" in result["message"]


async def test_connection_accepts_key_group_with_selected_model(
    tmp_path: Path, monkeypatch
):
    container = _three_kuaipao_container(tmp_path)
    monkeypatch.setattr(
        "app.services.provider_manager.httpx.AsyncClient",
        lambda **_kwargs: _ModelClient(["gpt-image-2"]),
    )

    result = await container.provider_manager.test_connection(capability="image")

    assert result == {
        "connected": True,
        "message": "快跑科技 image 连接成功",
    }
