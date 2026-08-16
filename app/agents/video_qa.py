from pathlib import Path
from app.domain.models import QAResult


class VideoQA:
    def __init__(self, thresholds: dict, provider=None, ffmpeg=None):
        self.thresholds = thresholds
        self.provider = provider
        self.ffmpeg = ffmpeg

    async def evaluate(self, shot_id: str, video_path: Path, attempt: int,
                       keyframe: Path | None = None, review_dir: Path | None = None,
                       expected_visible_details: list[str] | None = None,
                       expected_scene: str = "") -> QAResult:
        if self.provider is not None:
            if keyframe is None or review_dir is None or self.ffmpeg is None:
                raise RuntimeError("Real video QA requires keyframe, review directory and FFmpeg")
            sampled_frames = await self.ffmpeg.extract_review_frames(video_path, review_dir)
            return await self.provider.evaluate_video(
                shot_id, keyframe, sampled_frames, expected_visible_details or [],
                expected_scene, self.thresholds, attempt,
            )
        scores = {"identity": 0.94, "garment": 0.93, "motion": 0.90, "anatomy": 0.94, "scene": 0.93, "flicker": 0.04}
        passed = video_path.exists() and all(scores[name] >= value for name, value in self.thresholds.items())
        return QAResult(shot_id=shot_id, scores=scores, status="PASS" if passed else "FAIL", attempt=attempt,
                        issues=[] if passed else ["mock clip missing"])
