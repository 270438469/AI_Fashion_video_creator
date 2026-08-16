import json
from pathlib import Path
from app.domain.models import Asset
from app.providers.base.composer_provider import ComposerProvider
from app.services.ffmpeg_service import FFmpegService


class FFmpegComposer(ComposerProvider):
    def __init__(self, ffmpeg: FFmpegService):
        self.ffmpeg = ffmpeg

    async def compose(self, clips: list[Path], output_path: Path) -> Asset:
        await self.ffmpeg.concat(clips, output_path)
        probe = self.ffmpeg.probe(output_path)
        duration = float(probe.get("format", {}).get("duration", 0))
        video_stream = next(
            (
                stream
                for stream in probe.get("streams", [])
                if stream.get("codec_type") == "video"
            ),
            None,
        )
        if video_stream is None:
            raise RuntimeError("Final output has no playable video stream")
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        if not 17.5 <= duration <= 18.5:
            raise RuntimeError(
                f"Final output duration must be 18 seconds, got {duration:.3f}"
            )
        if width <= 0 or height <= 0 or abs(width / height - 9 / 16) > 0.01:
            raise RuntimeError(
                f"Final output must be 9:16 vertical video, got {width}x{height}"
            )
        validation = {
            "status": "PASS",
            "duration_seconds": round(duration, 3),
            "expected_duration_seconds": 18,
            "width": width,
            "height": height,
            "aspect_ratio": "9:16",
            "codec": video_stream.get("codec_name"),
            "clip_count": len(clips),
        }
        (output_path.parent / "final_validation.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return Asset(path=str(output_path), media_type="video/mp4")
