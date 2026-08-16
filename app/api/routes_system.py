import os
import platform
import shutil
import subprocess
from fastapi import APIRouter, Request


router = APIRouter(tags=["system"])


@router.get("/system/status")
async def system_status(request: Request):
    container = request.app.state.container
    gpu = {"available": False, "name": None}
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0 and result.stdout.strip():
            gpu = {"available": True, "name": result.stdout.strip().splitlines()[0]}
    except (OSError, subprocess.TimeoutExpired):
        pass
    disk = shutil.disk_usage(container.assets.workspace)
    try:
        container.orchestrator.characters.get("asian_girl_001")
        character_ok = True
    except KeyError:
        character_ok = False
    relay_status = container.relay_config.public_status()
    capability_status = relay_status["capabilities"]
    relay_ready = container.provider_manager.configured
    legacy_runway_ready = (
        container.settings.vision_provider == "openai"
        and container.settings.image_provider == "openai"
        and bool(container.settings.openai_api_key)
        and container.settings.video_provider == "runway"
        and bool(container.settings.runway_secret)
    )
    real_vision_ready = capability_status["vision"]["api_key_configured"] or legacy_runway_ready
    real_tryon_ready = capability_status["image"]["api_key_configured"] or legacy_runway_ready
    real_video_ready = capability_status["video"]["api_key_configured"] or legacy_runway_ready
    if real_vision_ready and real_tryon_ready and real_video_ready:
        generation_mode = f"ai_tryon_{relay_status['video_model']}_daily_life_video"
    elif real_tryon_ready:
        generation_mode = "ai_tryon_camera_motion"
    else:
        generation_mode = "mock_demo"
    return {
        "python": platform.python_version(), "ffmpeg": container.ffmpeg.check_available(),
        "ffprobe": shutil.which(container.settings.ffprobe_path) is not None,
        "gpu": gpu, "cuda": bool(os.environ.get("CUDA_PATH")), "disk_free_gb": round(disk.free / 1024**3, 1),
        "provider_mode": container.settings.provider_mode,
        "generation_mode": generation_mode,
        "generation_ready": (
            (real_vision_ready and real_tryon_ready and real_video_ready)
            or container.settings.allow_mock_generation
        ),
        "real_vision_ready": real_vision_ready,
        "real_tryon_ready": real_tryon_ready,
        "real_video_ready": real_video_ready,
        "video_environment_generated": real_video_ready,
        "providers": {
            "vision": container.settings.vision_provider,
            "image": container.settings.image_provider,
            "video": container.settings.video_provider,
            "relay": relay_status["relay_id"],
            "relay_label": relay_status["relay_label"],
            "vision_provider_id": relay_status["vision_provider_id"],
            "vision_provider_label": capability_status["vision"]["provider_label"],
            "image_provider_id": relay_status["image_provider_id"],
            "image_provider_label": capability_status["image"]["provider_label"],
            "video_provider_id": relay_status["video_provider_id"],
            "video_provider_label": capability_status["video"]["provider_label"],
            "video_model": relay_status["video_model"] if relay_ready else None,
            "configured_video_model": relay_status["video_model"],
            "capability_providers": relay_status["capability_providers"],
            "missing_provider_labels": relay_status["missing_capability_labels"],
            "ffmpeg": container.ffmpeg.check_available(),
        },
        "character": {"asian_girl_001": character_ok},
    }


@router.get("/settings")
async def settings(request: Request):
    container = request.app.state.container
    value = container.settings
    relay = container.relay_config.public_status()
    capabilities = relay["capabilities"]
    runtime_ready = container.provider_manager.configured
    return {"provider_mode": "real" if runtime_ready else "waiting_for_webui_key",
            "vision_provider": "relay" if runtime_ready else "unconfigured",
            "image_provider": "relay" if runtime_ready else "unconfigured",
            "video_provider": "relay" if runtime_ready else "unconfigured",
            "composer_provider": value.composer_provider, "default_character": "asian_girl_001",
            "output_directory": str((value.workspace_dir / "outputs").resolve()),
            "ffmpeg_path": value.ffmpeg_path,
            "vision_api": f"{capabilities['vision']['provider_label']} · {capabilities['vision']['base_url']}",
            "image_api": f"{capabilities['image']['provider_label']} · {capabilities['image']['base_url']}",
            "video_api": f"{capabilities['video']['provider_label']} · {capabilities['video']['base_url']}",
            "missing_api_keys": relay["missing_capability_labels"],
            "video_resolution": "720x1280" if value.video_provider in {"runway", "relay"} else "360x640",
            "concurrent_jobs": value.max_concurrent_runs,
            "vision_model": relay["vision_model"],
            "image_model": relay["image_model"],
            "video_model": relay["video_model"],
            "environment_stage": "video_generation" if value.video_provider in {"runway", "relay"} else "keyframe",
            "generation_policy": "Mock generation blocked" if not value.allow_mock_generation else "Mock demo allowed",
            "vision_api_key": capabilities["vision"]["api_key_masked"] or "未配置",
            "image_api_key": capabilities["image"]["api_key_masked"] or "未配置",
            "video_api_key": capabilities["video"]["api_key_masked"] or "未配置"}
