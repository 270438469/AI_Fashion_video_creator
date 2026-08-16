from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app


def build_app(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    return create_app(
        Settings(
            workspace_dir=tmp_path / "workspace",
            character_dir=root / "characters",
            provider_mode="real",
            vision_provider="unconfigured",
            image_provider="unconfigured",
            video_provider="unconfigured",
            allow_mock_generation=False,
        )
    )


@pytest.mark.asyncio
async def test_provider_config_api_saves_three_keys_without_returning_plaintext(
    tmp_path: Path,
):
    transport = httpx.ASGITransport(app=build_app(tmp_path))
    payload = {
        "vision_provider_id": "kuaipao",
        "vision_model": "gpt-5.6-sol",
        "image_provider_id": "openai",
        "image_model": "gpt-image-2",
        "video_provider_id": "notoken",
        "video_model": "seedance-2.0",
        "vision_api_key": "VISION-SECRET-1111",
        "image_api_key": "IMAGE-SECRET-2222",
        "video_api_key": "VIDEO-SECRET-3333",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/provider-config", json=payload)
        status = await client.get("/api/v1/provider-config")
        runtime = await client.get("/api/v1/runtime-config")
        system = await client.get("/api/v1/system/status")

    assert response.status_code == 200
    assert status.status_code == 200
    assert response.json()["all_api_keys_configured"] is True
    assert response.json()["capability_providers"] == {
        "vision": "kuaipao",
        "image": "openai",
        "video": "notoken",
    }
    assert runtime.json()["providers"] == response.json()["capability_providers"]
    assert system.json()["generation_ready"] is True
    combined = response.text + status.text + runtime.text + system.text
    assert "VISION-SECRET-1111" not in combined
    assert "IMAGE-SECRET-2222" not in combined
    assert "VIDEO-SECRET-3333" not in combined


@pytest.mark.asyncio
async def test_each_capability_key_can_be_saved_and_deleted_independently(
    tmp_path: Path,
):
    transport = httpx.ASGITransport(app=build_app(tmp_path))
    selection = {
        "vision_provider_id": "kuaipao",
        "vision_model": "gpt-5.6-sol",
        "image_provider_id": "kuaipao",
        "image_model": "gpt-image-2",
        "video_provider_id": "notoken",
        "video_model": "seedance-2.0",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/provider-config",
            json={**selection, "vision_api_key": "VISION-ONLY-KEY"},
        )
        image = await client.post(
            "/api/v1/settings/api-key",
            json={
                "capability": "image",
                "provider_id": "kuaipao",
                "api_key": "IMAGE-ONLY-KEY",
            },
        )
        video = await client.post(
            "/api/v1/settings/api-key",
            json={
                "capability": "video",
                "provider_id": "notoken",
                "api_key": "VIDEO-ONLY-KEY",
            },
        )
        ready = await client.get("/api/v1/provider-config")
        deleted = await client.delete("/api/v1/provider-config/api-key/image")
        after_delete = await client.get("/api/v1/provider-config")

    assert first.json()["missing_capabilities"] == ["image", "video"]
    assert image.json()["configured"] is True
    assert video.json()["all_api_keys_configured"] is True
    assert ready.json()["all_api_keys_configured"] is True
    assert deleted.json()["deleted"] is True
    assert after_delete.json()["missing_capabilities"] == ["image"]
    assert after_delete.json()["capabilities"]["vision"]["api_key_configured"] is True
    assert after_delete.json()["capabilities"]["video"]["api_key_configured"] is True
    combined = first.text + image.text + video.text + ready.text + deleted.text
    assert "VISION-ONLY-KEY" not in combined
    assert "IMAGE-ONLY-KEY" not in combined
    assert "VIDEO-ONLY-KEY" not in combined
