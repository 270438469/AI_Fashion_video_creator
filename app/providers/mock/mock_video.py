from pathlib import Path
from app.domain.models import Asset
from app.providers.base.video_provider import VideoProvider
from app.services.ffmpeg_service import FFmpegService


class MockVideoProvider(VideoProvider):
    def __init__(self, ffmpeg: FFmpegService):
        self.ffmpeg = ffmpeg

    async def generate_video(self, start_frame: Path, prompt: str, duration: float, output_path: Path) -> Asset:
        await self.ffmpeg.image_to_video(start_frame, output_path, duration)
        return Asset(path=str(output_path), media_type="video/mp4", duration=duration)

