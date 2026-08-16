import asyncio
import base64
import io
from pathlib import Path

import httpx
from PIL import Image

from app.domain.models import Asset
from app.providers.base.video_provider import VideoProvider
from app.services.ffmpeg_service import FFmpegService


class RunwayVideoProvider(VideoProvider):
    """Runway image-to-video adapter; model may be Gen-4.5 or Seedance."""

    API_ROOT = "https://api.dev.runwayml.com/v1"
    SUPPORTED_MODELS = {
        "gen4.5",
        "gen4_turbo",
        "seedance2",
        "seedance2_fast",
        "seedance2_mini",
    }

    def __init__(
        self,
        api_secret: str,
        model: str = "seedance2",
        timeout_seconds: int = 900,
        poll_interval: float = 5.0,
        client: httpx.AsyncClient | None = None,
        ffmpeg: FFmpegService | None = None,
    ):
        if not api_secret:
            raise RuntimeError(
                "RUNWAYML_API_SECRET (or RUNWAY_API_KEY) is required when VIDEO_PROVIDER=runway"
            )
        if model not in self.SUPPORTED_MODELS:
            raise RuntimeError(f"Unsupported Runway video model: {model}")
        self.api_secret = api_secret
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.client = client
        self.ffmpeg = ffmpeg

    async def generate_video(
        self, start_frame: Path, prompt: str, duration: float, output_path: Path
    ) -> Asset:
        target_seconds = int(round(duration))
        if target_seconds <= 0:
            raise ValueError("Video duration must be positive")
        is_seedance = self.model.startswith("seedance2")
        request_seconds = max(4, target_seconds) if is_seedance else target_seconds
        max_seconds = 15 if is_seedance else 10
        min_seconds = 4 if is_seedance else 2
        if not min_seconds <= request_seconds <= max_seconds:
            raise ValueError(
                f"Runway {self.model} duration must be between {min_seconds} and {max_seconds} seconds"
            )

        client = self.client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=120.0))
        owns_client = self.client is None
        try:
            response = await client.post(
                f"{self.API_ROOT}/image_to_video",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "promptImage": self._image_data_uri(start_frame),
                    "promptText": prompt[:1000],
                    "ratio": "720:1280",
                    "duration": request_seconds,
                },
            )
            response.raise_for_status()
            task_id = response.json().get("id")
            if not task_id:
                raise RuntimeError("Runway did not return a task id")
            task = await self._wait_for_task(client, task_id)
            outputs = task.get("output") or []
            if not outputs:
                raise RuntimeError("Runway task completed without a video URL")
            media = await client.get(outputs[0])
            media.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            source_path = output_path.with_name(f"{output_path.stem}.runway-source.mp4")
            source_path.write_bytes(media.content)
            if self.ffmpeg is None:
                if request_seconds != target_seconds:
                    source_path.unlink(missing_ok=True)
                    raise RuntimeError(
                        "FFmpegService is required to trim Seedance output to the storyboard duration"
                    )
                source_path.replace(output_path)
            else:
                try:
                    await self.ffmpeg.normalize_generated_video(
                        source_path, output_path, target_seconds
                    )
                finally:
                    source_path.unlink(missing_ok=True)
            return Asset(path=str(output_path), media_type="video/mp4", duration=duration)
        finally:
            if owns_client:
                await client.aclose()

    async def _wait_for_task(self, client: httpx.AsyncClient, task_id: str) -> dict:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        while loop.time() < deadline:
            response = await client.get(
                f"{self.API_ROOT}/tasks/{task_id}", headers=self._headers()
            )
            response.raise_for_status()
            task = response.json()
            status = str(task.get("status", "")).upper()
            if status == "SUCCEEDED":
                return task
            if status in {"FAILED", "CANCELLED"}:
                detail = task.get("failure") or task.get("failureCode") or status
                raise RuntimeError(f"Runway task {task_id} failed: {detail}")
            await asyncio.sleep(self.poll_interval)
        raise TimeoutError(f"Runway task {task_id} exceeded {self.timeout_seconds}s")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_secret}",
            "X-Runway-Version": "2024-11-06",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _image_data_uri(path: Path) -> str:
        # A normalized portrait JPEG stays below Runway's 5 MB data-URI limit.
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((720, 1280), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (720, 1280), "#e8e5df")
            canvas.paste(image, ((720 - image.width) // 2, (1280 - image.height) // 2))
            buffer = io.BytesIO()
            canvas.save(buffer, "JPEG", quality=92, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
