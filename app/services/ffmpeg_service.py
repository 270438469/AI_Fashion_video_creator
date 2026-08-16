import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


class FFmpegService:
    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def check_available(self) -> bool:
        return shutil.which(self.ffmpeg_path) is not None or Path(self.ffmpeg_path).exists()

    def probe(self, path: Path) -> dict:
        result = subprocess.run([self.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise FFmpegError(result.stderr.strip())
        return json.loads(result.stdout)

    async def image_to_video(self, image: Path, output: Path, duration: float) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [self.ffmpeg_path, "-y", "-loop", "1", "-i", str(image), "-t", str(duration),
                   "-vf", "scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                   "-r", "24", "-c:v", "libx264", "-preset", "veryfast", "-movflags", "+faststart", str(output)]
        await self._run(command)

    async def normalize_generated_video(self, source: Path, output: Path, duration: float) -> None:
        """Normalize provider output so every storyboard clip has an exact local duration/format."""
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg_path, "-y", "-i", str(source), "-t", str(duration),
            "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-r", "24", "-c:v", "libx264", "-preset", "veryfast", "-an",
            "-movflags", "+faststart", str(output),
        ]
        await self._run(command)

    async def extract_review_frames(self, video: Path, output_dir: Path) -> list[Path]:
        """Persist early/middle/late frames so video QA is reproducible from the run folder."""
        output_dir.mkdir(parents=True, exist_ok=True)
        duration = float(self.probe(video)["format"]["duration"])
        frames: list[Path] = []
        for index, fraction in enumerate((0.15, 0.50, 0.85), start=1):
            output = output_dir / f"frame_{index}.jpg"
            command = [
                self.ffmpeg_path, "-y", "-ss", f"{duration * fraction:.3f}",
                "-i", str(video), "-frames:v", "1", "-vf",
                "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2",
                "-q:v", "2", str(output),
            ]
            await self._run(command)
            frames.append(output)
        return frames

    async def concat(self, clips: list[Path], output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        list_path = output.parent / "concat.txt"
        list_path.write_text("".join(f"file '{clip.resolve().as_posix()}'\n" for clip in clips), encoding="utf-8")
        command = [self.ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
        await self._run(command)

    async def _run(self, command: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise FFmpegError(stderr.decode(errors="replace")[-3000:])
