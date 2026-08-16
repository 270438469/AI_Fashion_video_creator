from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.relay_config import RelaySelection


router = APIRouter(tags=["provider-configuration"])
Capability = Literal["vision", "image", "video"]


class ProviderConfigUpdate(BaseModel):
    vision_provider_id: str
    vision_model: str
    image_provider_id: str
    image_model: str
    video_provider_id: str
    video_model: str
    vision_api_key: str | None = Field(default=None, min_length=1, max_length=512)
    image_api_key: str | None = Field(default=None, min_length=1, max_length=512)
    video_api_key: str | None = Field(default=None, min_length=1, max_length=512)


class ApiKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)
    capability: Capability = "video"
    provider_id: str | None = None


@router.get("/provider-config/catalog")
async def provider_catalog(request: Request):
    return request.app.state.container.relay_config.public_catalog()


@router.get("/provider-config")
async def provider_config(request: Request):
    return request.app.state.container.relay_config.public_status()


@router.post("/provider-config")
async def save_provider_config(payload: ProviderConfigUpdate, request: Request):
    container = request.app.state.container
    selection = RelaySelection(
        vision_provider_id=payload.vision_provider_id,
        vision_model=payload.vision_model,
        image_provider_id=payload.image_provider_id,
        image_model=payload.image_model,
        video_provider_id=payload.video_provider_id,
        video_model=payload.video_model,
    )
    try:
        container.relay_config.save(selection)
        for capability in ("vision", "image", "video"):
            api_key = getattr(payload, f"{capability}_api_key")
            if api_key:
                container.relay_config.set_api_key(
                    capability, selection.provider_id(capability), api_key
                )
        if container.provider_manager.configured:
            container.provider_manager.apply()
        else:
            container.provider_manager.deactivate()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return container.relay_config.public_status()


@router.delete("/provider-config/api-key/{capability}")
async def delete_capability_api_key(
    capability: Capability, request: Request, provider_id: str | None = None
):
    container = request.app.state.container
    selection = container.relay_config.selection()
    provider_id = provider_id or selection.provider_id(capability)
    try:
        deleted = container.relay_config.delete_api_key(capability, provider_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    container.provider_manager.deactivate()
    return {"deleted": deleted, **container.relay_config.public_status()}


@router.delete("/provider-config/api-key")
async def delete_legacy_active_api_key(request: Request):
    return await delete_capability_api_key("video", request)


@router.post("/provider-config/test")
async def test_provider_connection(
    request: Request, capability: Capability | None = None
):
    return await request.app.state.container.provider_manager.test_connection(
        capability=capability
    )


@router.get("/runtime-config")
async def runtime_config(request: Request):
    status = request.app.state.container.relay_config.public_status()
    return {
        "providers": status["capability_providers"],
        "base_urls": {
            capability: value["base_url"]
            for capability, value in status["capabilities"].items()
        },
        "models": {
            "vision": status["vision_model"],
            "image": status["image_model"],
            "video": status["video_model"],
        },
        "size": "720x1280",
        "target_seconds": 18,
        "all_api_keys_configured": status["all_api_keys_configured"],
        "missing_capabilities": status["missing_capabilities"],
    }


@router.post("/settings/api-key")
async def save_active_api_key(payload: ApiKeyUpdate, request: Request):
    container = request.app.state.container
    selection = container.relay_config.selection()
    provider_id = payload.provider_id or selection.provider_id(payload.capability)
    try:
        container.relay_config.set_api_key(
            payload.capability, provider_id, payload.api_key
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if container.provider_manager.configured:
        container.provider_manager.apply()
    else:
        container.provider_manager.deactivate()
    status = container.relay_config.public_status()
    capability_status = status["capabilities"][payload.capability]
    return {
        "configured": capability_status["api_key_configured"],
        "masked": capability_status["api_key_masked"],
        "all_api_keys_configured": status["all_api_keys_configured"],
    }


@router.get("/settings/api-key/status")
async def active_api_key_status(request: Request):
    status = request.app.state.container.relay_config.public_status()
    return {
        "configured": status["all_api_keys_configured"],
        "capabilities": status["capabilities"],
    }


@router.delete("/settings/api-key")
async def delete_active_api_key(
    request: Request, capability: Capability = "video"
):
    result = await delete_capability_api_key(capability, request)
    capability_status = result["capabilities"][capability]
    return {
        "deleted": result["deleted"],
        "configured": capability_status["api_key_configured"],
        "masked": capability_status["api_key_masked"],
    }
