from __future__ import annotations

import asyncio
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps

from app.domain.models import Asset
from app.providers.base.video_provider import VideoProvider
from app.services.ffmpeg_service import FFmpegService


PENDING = {"queued", "in_progress", "processing"}
SUCCESS = {"completed", "succeeded", "success"}
FAILED = {"failed", "cancelled", "canceled"}


class OpenAIVideoProvider(VideoProvider):
    """Official OpenAI image-to-video adapter using the Videos API."""

    API_ROOT = "https://api.openai.com"
    SIZE = "720x1280"

    def __init__(
        self,
        api_key: str,
        model: str = "sora-2",
        timeout_seconds: int = 900,
        poll_interval: float = 5.0,
        client: httpx.AsyncClient | None = None,
        ffmpeg: FFmpegService | None = None,
    ):
        if not api_key:
            raise RuntimeError("OpenAI API Key is required for official video generation")
        self.api_key = api_key
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
        # The storyboard uses 3s and 4s shots. Request the minimum 4s clip and
        # normalize it back to the exact storyboard duration after download.
        request_seconds = max(4, target_seconds)
        attempt_dir = self._create_attempt_dir(output_path)
        reference_bytes = self._portrait_reference(start_frame)
        self._persist_input_log(
            attempt_dir, start_frame, prompt, request_seconds, reference_bytes
        )

        timeout = httpx.Timeout(60.0, read=180.0)
        client = self.client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        owns_client = self.client is None
        try:
            files = {
                "input_reference": (
                    "input_reference.png",
                    reference_bytes,
                    "image/png",
                )
            }
            data = {
                "model": self.model,
                "prompt": prompt[:4000],
                "size": self.SIZE,
                "seconds": str(request_seconds),
            }
            response = await client.post(
                f"{self.API_ROOT}/v1/videos",
                headers=self._headers(),
                data=data,
                files=files,
            )
            response.raise_for_status()
            created = self._safe_json(response)
            self._write_json(attempt_dir / "provider_response.json", created)
            task_id = created.get("id")
            if not task_id:
                raise RuntimeError("OpenAI Videos API did not return a task id")
            task = await self._wait_for_task(client, str(task_id), attempt_dir)
            media = await client.get(
                f"{self.API_ROOT}/v1/videos/{task_id}/content",
                headers=self._headers(),
            )
            media.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            source_path = output_path.with_name(f"{output_path.stem}.openai-source.mp4")
            source_path.write_bytes(media.content)
            if self.ffmpeg is None:
                if request_seconds != target_seconds:
                    source_path.unlink(missing_ok=True)
                    raise RuntimeError(
                        "FFmpegService is required to trim OpenAI video output"
                    )
                source_path.replace(output_path)
            else:
                try:
                    await self.ffmpeg.normalize_generated_video(
                        source_path, output_path, target_seconds
                    )
                finally:
                    source_path.unlink(missing_ok=True)
            self._write_json(
                attempt_dir / "video_gate.json",
                {"status": "PASS", "task_id": task_id, "provider_status": task.get("status")},
            )
            return Asset(path=str(output_path), media_type="video/mp4", duration=duration)
        except Exception as exc:
            self._write_json(
                attempt_dir / "video_gate.json",
                {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        finally:
            if owns_client:
                await client.aclose()

    async def _wait_for_task(
        self, client: httpx.AsyncClient, task_id: str, attempt_dir: Path
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        last_event: tuple[str, Any] | None = None
        events_path = attempt_dir / "task_events.jsonl"
        while loop.time() < deadline:
            response = await client.get(
                f"{self.API_ROOT}/v1/videos/{task_id}", headers=self._headers()
            )
            response.raise_for_status()
            task = self._safe_json(response)
            status = str(task.get("status", "")).lower()
            progress = task.get("progress")
            event_key = (status, progress)
            if event_key != last_event:
                event = {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "progress": progress,
                }
                with events_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                last_event = event_key
            if status in SUCCESS:
                self._write_json(attempt_dir / "provider_response.json", task)
                return task
            if status in FAILED:
                detail = task.get("error") or task.get("message") or status
                raise RuntimeError(f"OpenAI video task {task_id} failed: {detail}")
            if status and status not in PENDING:
                raise RuntimeError(
                    f"OpenAI video task {task_id} returned unknown status: {status}"
                )
            await asyncio.sleep(self.poll_interval)
        raise TimeoutError(f"OpenAI video task {task_id} exceeded {self.timeout_seconds}s")

    def _persist_input_log(
        self,
        attempt_dir: Path,
        start_frame: Path,
        prompt: str,
        seconds: int,
        reference_bytes: bytes,
    ) -> None:
        (attempt_dir / "final_prompt.txt").write_text(prompt, encoding="utf-8")
        self._write_json(
            attempt_dir / "input_manifest.json",
            {
                "inputs": [
                    {
                        "role": "input_reference",
                        "name": start_frame.name,
                        "sha256": self._sha256(start_frame),
                        "normalized_sha256": hashlib.sha256(reference_bytes).hexdigest(),
                        "normalized_size": self.SIZE,
                    }
                ]
            },
        )
        self._write_json(
            attempt_dir / "environment_snapshot.json",
            {
                "VIDEO_PROVIDER": "openai",
                "BASE_URL": self.API_ROOT,
                "VIDEO_MODEL": self.model,
                "VIDEO_SIZE": self.SIZE,
                "VIDEO_REQUEST_SECONDS": seconds,
                "VIDEO_REQUEST_TIMEOUT_SECONDS": self.timeout_seconds,
                "VIDEO_POLL_INTERVAL_SECONDS": self.poll_interval,
            },
        )
        self._write_json(
            attempt_dir / "final_request.json",
            {
                "provider": "openai",
                "model": self.model,
                "method": "POST",
                "endpoint": "/v1/videos",
                "payload": {
                    "prompt": prompt[:4000],
                    "size": self.SIZE,
                    "seconds": str(seconds),
                    "input_reference": "input_reference.png",
                },
                "input_reference": {
                    "name": start_frame.name,
                    "sha256": self._sha256(start_frame),
                },
            },
        )

    def _create_attempt_dir(self, output_path: Path) -> Path:
        run_dir = output_path.parents[1]
        root = run_dir / "video_requests"
        root.mkdir(parents=True, exist_ok=True)
        prefix = output_path.stem
        count = len(list(root.glob(f"{prefix}_*"))) + 1
        safe_model = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in self.model
        )
        attempt = root / f"{prefix}_{count:02d}_{safe_model}"
        attempt.mkdir(parents=True, exist_ok=False)
        return attempt

    @classmethod
    def _portrait_reference(cls, path: Path) -> bytes:
        with Image.open(path) as source:
            normalized = ImageOps.fit(
                source.convert("RGB"),
                (720, 1280),
                Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            buffer = io.BytesIO()
            normalized.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
