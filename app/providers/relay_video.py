from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from app.domain.models import Asset
from app.providers.base.video_provider import VideoProvider
from app.services.ffmpeg_service import FFmpegService
from app.services.relay_config import RelayProfile


PENDING = {"queued", "pending", "running", "processing", "in_progress", "unknown", "created"}
SUCCESS = {"completed", "succeeded", "success"}
FAILED = {"failed", "error", "cancelled", "canceled"}


class RelayVideoProvider(VideoProvider):
    """Image-to-video adapter for the fixed Kuaipao and NoToken contracts."""

    def __init__(
        self,
        api_key: str,
        profile: RelayProfile,
        model: str,
        timeout_seconds: int = 900,
        poll_interval: float = 5.0,
        client: httpx.AsyncClient | None = None,
        ffmpeg: FFmpegService | None = None,
    ):
        if not api_key:
            raise RuntimeError("Relay API Key is required")
        self.api_key = api_key
        self.profile = profile
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
        request_seconds = self._request_seconds(target_seconds)
        attempt_dir = self._create_attempt_dir(output_path)
        self._persist_input_log(attempt_dir, start_frame, prompt, request_seconds)
        recovered_task = self._recover_pending_task(output_path, attempt_dir)

        timeout = httpx.Timeout(60.0, read=180.0)
        client = self.client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        owns_client = self.client is None
        try:
            if recovered_task is not None:
                created = recovered_task
                self._write_json(
                    attempt_dir / "resumed_task.json",
                    {
                        "task_id": created["id"],
                        "status": created.get("status"),
                        "reason": "Recovered an accepted provider task after local polling failure",
                    },
                )
            elif self.profile.video["protocol"] == "kuaipao":
                created = await self._create_kuaipao_video(
                    client, start_frame, prompt, request_seconds, attempt_dir
                )
            else:
                file_id = await self._upload_image(client, start_frame, attempt_dir)
                image_ref = file_id
                image_ref = await self._query_file_url(client, file_id, attempt_dir)
                payload = self._create_payload(image_ref, prompt, request_seconds)
                self._write_json(
                    attempt_dir / "final_request.json",
                    {
                        "provider": self.profile.relay_id,
                        "model": self.model,
                        "method": "POST",
                        "endpoint": self.profile.video["create_path"],
                        "payload": payload,
                        "input_reference": {
                            "name": start_frame.name,
                            "sha256": self._sha256(start_frame),
                        },
                    },
                )
                response = await client.post(
                    self._url(self.profile.video["create_path"]),
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                created = self._safe_json(response)
                self._write_json(attempt_dir / "provider_response.json", created)
            task_id = created.get("id") or created.get("task_id") or created.get("taskId")
            if not task_id:
                raise RuntimeError("Relay video API did not return a task id")
            task = await self._wait_for_task(client, str(task_id), attempt_dir)
            video_url = self._video_url(task)
            if video_url:
                media = await client.get(
                    video_url, headers=self._download_headers(video_url)
                )
            elif self.profile.video.get("content_path"):
                content_path = self.profile.video["content_path"].format(
                    task_id=task_id
                )
                media = await client.get(
                    self._url(content_path), headers=self._auth_headers()
                )
            else:
                raise RuntimeError("Relay video task completed without a video URL")
            media.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            source_path = output_path.with_name(
                f"{output_path.stem}.{self.profile.relay_id}-source.mp4"
            )
            source_path.write_bytes(media.content)
            if self.ffmpeg is None:
                if request_seconds != target_seconds:
                    source_path.unlink(missing_ok=True)
                    raise RuntimeError("FFmpeg is required to normalize relay video duration")
                source_path.replace(output_path)
            else:
                try:
                    await self.ffmpeg.normalize_generated_video(
                        source_path, output_path, target_seconds
                    )
                finally:
                    source_path.unlink(missing_ok=True)
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

    def _recover_pending_task(
        self, output_path: Path, current_attempt_dir: Path
    ) -> dict[str, Any] | None:
        root = output_path.parents[1] / "video_requests"
        candidates = sorted(
            (
                path
                for path in root.glob(f"{output_path.stem}_*")
                if path != current_attempt_dir
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            response_path = path / "provider_response.json"
            request_path = path / "final_request.json"
            if not response_path.exists():
                continue
            try:
                payload = json.loads(response_path.read_text(encoding="utf-8"))
                request = (
                    json.loads(request_path.read_text(encoding="utf-8"))
                    if request_path.exists()
                    else {}
                )
            except (OSError, json.JSONDecodeError):
                continue
            if (
                self.profile.video["protocol"] == "kuaipao"
                and request.get("input_transport")
                not in {"provider_https_url", "multipart_local_upload"}
            ):
                continue
            gate_path = path / "video_gate.json"
            if gate_path.exists():
                try:
                    gate_error = str(
                        json.loads(gate_path.read_text(encoding="utf-8")).get(
                            "error", ""
                        )
                    )
                except (OSError, json.JSONDecodeError):
                    gate_error = ""
                if "Relay task" in gate_error and " failed:" in gate_error:
                    continue
            task_id = payload.get("id") or payload.get("task_id") or payload.get("taskId")
            status = str(payload.get("status", "")).lower()
            if task_id and status in PENDING:
                return {**payload, "id": str(task_id)}
            return None
        return None

    async def _create_kuaipao_video(
        self,
        client: httpx.AsyncClient,
        image: Path,
        prompt: str,
        seconds: int,
        attempt_dir: Path,
    ) -> dict[str, Any]:
        """Create a Kuaipao task using the contract required by the model family."""
        text = prompt[:4000]
        family = self._model_family()
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": text,
            "size": "720x1280",
            "seconds": str(seconds),
        }
        input_transport = "multipart_local_upload"
        if family == "seedance":
            payload["input_reference"] = self._source_image_url(image)
            input_transport = "provider_https_url"
        self._write_json(
            attempt_dir / "final_request.json",
            {
                "provider": self.profile.relay_id,
                "model": self.model,
                "method": "POST",
                "endpoint": self.profile.video["create_path"],
                "model_family": family,
                "content_type": (
                    "application/json"
                    if input_transport == "provider_https_url"
                    else "multipart/form-data"
                ),
                "input_transport": input_transport,
                "payload": {
                    **payload,
                    "input_reference": (
                        payload.get("input_reference")
                        if input_transport == "provider_https_url"
                        else image.name
                    ),
                },
                "input_reference": {
                    "field": "input_reference",
                    "name": image.name,
                    "sha256": self._sha256(image),
                },
            },
        )
        response = None
        for transport_attempt in range(1, 4):
            try:
                if input_transport == "provider_https_url":
                    response = await client.post(
                        self._url(self.profile.video["create_path"]),
                        headers=self._headers(),
                        json=payload,
                    )
                else:
                    with image.open("rb") as handle:
                        response = await client.post(
                            self._url(self.profile.video["create_path"]),
                            headers=self._auth_headers(),
                            data=payload,
                            files={
                                "input_reference": (
                                    image.name,
                                    handle,
                                    self._image_media_type(image),
                                )
                            },
                        )
                response.raise_for_status()
                break
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                status = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                response_detail = None
                if isinstance(exc, httpx.HTTPStatusError):
                    response_detail = self._upstream_error_message(exc.response)
                deterministic_model_error = bool(
                    response_detail
                    and (
                        "model_not_found" in response_detail
                        or "No available channel" in response_detail
                    )
                )
                retryable = (
                    status is None or status == 429 or status >= 500
                ) and not deterministic_model_error
                with (attempt_dir / "transport_events.jsonl").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write(
                        json.dumps(
                            {
                                "attempt": transport_attempt,
                                "status": status,
                                "error_type": type(exc).__name__,
                                "response": response_detail,
                                "retrying": retryable and transport_attempt < 3,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                if not retryable or transport_attempt >= 3:
                    if isinstance(exc, httpx.HTTPStatusError):
                        raise RuntimeError(
                            f"Kuaipao video create failed (HTTP {status}): "
                            f"{response_detail or 'upstream error'}"
                        ) from exc
                    raise
                await asyncio.sleep(2 * transport_attempt)
        if response is None:
            raise RuntimeError("Kuaipao video create retry loop ended unexpectedly")
        created = self._safe_json(response)
        self._write_json(attempt_dir / "provider_response.json", created)
        return created

    def _request_seconds(self, target_seconds: int) -> int:
        """Respect fixed-duration relay aliases while retaining short-shot support."""
        for suffix, fixed_seconds in (("-12s", 12), ("-8s", 8)):
            if self.model.endswith(suffix):
                return fixed_seconds
        return max(4, target_seconds)

    def _model_family(self) -> str:
        if self.model.startswith("doubao-seedance") or "seedance" in self.model:
            return "seedance"
        if self.model.startswith("grok-"):
            return "grok"
        if self.model.startswith("sora-"):
            return "sora"
        if self.model.startswith(("veo-", "veo_")):
            return "veo"
        return "openai_compatible"

    @staticmethod
    def _image_media_type(image: Path) -> str:
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(image.suffix.lower(), "image/png")

    def _upstream_error_message(self, response: httpx.Response) -> str:
        """Extract a useful relay error without leaking the configured secret."""
        raw = response.text[:2000].replace(self.api_key, "***")
        try:
            payload: Any = response.json()
        except ValueError:
            return raw
        for _ in range(3):
            if not isinstance(payload, dict):
                break
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return f"{error.get('code') or payload.get('code')}: {error['message']}"
            message = payload.get("message")
            if isinstance(message, dict):
                payload = message
                continue
            if isinstance(message, str):
                try:
                    nested = json.loads(message)
                except json.JSONDecodeError:
                    return f"{payload.get('code')}: {message}"
                payload = nested
                continue
            break
        return raw

    def _source_image_url(self, image: Path) -> str:
        public_base_path = image.parents[1] / "public_keyframe_base_url.txt"
        if public_base_path.exists():
            public_base = public_base_path.read_text(encoding="utf-8").strip().rstrip("/")
            if public_base.startswith(("https://", "http://")):
                return f"{public_base}/{image.name}"
        root = image.parents[1] / "image_requests"
        candidates = sorted(
            root.glob(f"{image.stem}_*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            response_path = path / "provider_response.json"
            if not response_path.exists():
                continue
            try:
                payload = json.loads(response_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            data = payload.get("data")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and str(item.get("url", "")).startswith(
                        ("https://", "http://")
                    ):
                        return str(item["url"])
        raise RuntimeError(
            f"Kuaipao video requires a public source URL for {image.name}; "
            "the successful image provider response did not contain one"
        )

    async def _upload_image(
        self, client: httpx.AsyncClient, image: Path, attempt_dir: Path
    ) -> str:
        with image.open("rb") as handle:
            response = await client.post(
                self._url(self.profile.video["upload_path"]),
                headers=self._auth_headers(),
                files={"file": (image.name, handle, "image/png")},
            )
        response.raise_for_status()
        payload = self._safe_json(response)
        self._write_json(attempt_dir / "upload_response.json", payload)
        file_id = payload.get("id") or payload.get("file_id") or payload.get("fileId")
        if not file_id:
            raise RuntimeError("Relay upload API did not return a file id")
        return str(file_id)

    async def _query_file_url(
        self, client: httpx.AsyncClient, file_id: str, attempt_dir: Path
    ) -> str:
        path = self.profile.video["file_query_path"].format(file_id=file_id)
        response = await client.get(self._url(path), headers=self._auth_headers())
        response.raise_for_status()
        payload = self._safe_json(response)
        self._write_json(attempt_dir / "file_response.json", payload)
        url = payload.get("url") or (payload.get("data") or {}).get("url")
        if not url:
            raise RuntimeError("Relay file API did not return an image URL")
        return str(url)

    def _create_payload(self, image_ref: str, prompt: str, seconds: int) -> dict[str, Any]:
        text = prompt[:4000]
        if self.profile.video["protocol"] == "notoken":
            image_item = {"type": "image_url", "image_url": {"url": image_ref}}
            return {
                "model": self.model,
                "content": [
                    {"type": "text", "text": text},
                    image_item,
                ],
                "duration": seconds,
                "ratio": "9:16",
                "resolution": "720p",
                "watermark": False,
            }
        return {
            "model": self.model,
            "content": [
                {"type": "image", "file_id": image_ref},
                {"type": "text", "text": text},
            ],
            "duration": seconds,
            "ratio": "9:16",
        }

    async def _wait_for_task(
        self, client: httpx.AsyncClient, task_id: str, attempt_dir: Path
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        last_event: tuple[str, Any] | None = None
        events_path = attempt_dir / "task_events.jsonl"
        while loop.time() < deadline:
            path = self.profile.video["query_path"].format(task_id=task_id)
            response = await client.get(self._url(path), headers=self._auth_headers())
            response.raise_for_status()
            task = self._safe_json(response)
            status = str(task.get("status", "")).lower()
            progress = task.get("progress")
            current_event = (status, progress)
            if current_event != last_event:
                event = {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "progress": progress,
                }
                with events_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                last_event = current_event
            if status in SUCCESS:
                self._write_json(attempt_dir / "provider_response.json", task)
                return task
            if status in FAILED:
                error = task.get("error") or task.get("message") or status
                raise RuntimeError(f"Relay task {task_id} failed: {error}")
            if status and status not in PENDING:
                raise RuntimeError(f"Relay task {task_id} returned unknown status: {status}")
            await asyncio.sleep(self.poll_interval)
        raise TimeoutError(f"Relay task {task_id} exceeded {self.timeout_seconds}s")

    def _persist_input_log(
        self, attempt_dir: Path, start_frame: Path, prompt: str, seconds: int
    ) -> None:
        (attempt_dir / "final_prompt.txt").write_text(prompt, encoding="utf-8")
        with Image.open(start_frame) as image:
            width, height = image.size
        self._write_json(
            attempt_dir / "input_manifest.json",
            {
                "inputs": [
                    {
                        "role": "input_reference",
                        "name": start_frame.name,
                        "sha256": self._sha256(start_frame),
                        "width": width,
                        "height": height,
                    }
                ]
            },
        )
        self._write_json(
            attempt_dir / "environment_snapshot.json",
            {
                "VIDEO_PROVIDER": self.profile.relay_id,
                "BASE_URL": self.profile.api_root,
                "VIDEO_MODEL": self.model,
                "VIDEO_ASPECT_RATIO": "9:16",
                "VIDEO_RESOLUTION": "720p",
                "VIDEO_REQUEST_SECONDS": seconds,
                "VIDEO_REQUEST_TIMEOUT_SECONDS": self.timeout_seconds,
                "VIDEO_POLL_INTERVAL_SECONDS": self.poll_interval,
            },
        )
        # A pre-request record always exists, even when image upload fails.
        self._write_json(
            attempt_dir / "final_request.json",
            {
                "provider": self.profile.relay_id,
                "model": self.model,
                "method": "POST",
                "endpoint": self.profile.video["create_path"],
                "status": "INPUT_PERSISTED_BEFORE_REQUEST",
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
        safe_model = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.model)
        attempt = root / f"{prefix}_{count:02d}_{safe_model}"
        attempt.mkdir(parents=True, exist_ok=False)
        return attempt

    def _url(self, path: str) -> str:
        return f"{self.profile.api_root}/{path.lstrip('/')}"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    def _headers(self) -> dict[str, str]:
        return {**self._auth_headers(), "Content-Type": "application/json"}

    def _download_headers(self, url: str) -> dict[str, str]:
        return self._auth_headers() if url.startswith(self.profile.api_root) else {}

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    @staticmethod
    def _video_url(task: dict[str, Any]) -> str | None:
        content = task.get("content")
        if isinstance(content, dict):
            return content.get("video_url") or content.get("url")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and (
                    item.get("type") == "video" or item.get("url") or item.get("video_url")
                ):
                    return item.get("url") or item.get("video_url")
        output = task.get("output")
        if isinstance(output, dict):
            return output.get("url") or output.get("video_url")
        if isinstance(output, list) and output:
            first = output[0]
            return first if isinstance(first, str) else first.get("url")
        metadata = task.get("metadata")
        if isinstance(metadata, dict) and metadata.get("url"):
            return str(metadata["url"])
        return task.get("video_url") or task.get("url")

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
