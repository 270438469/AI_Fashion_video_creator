import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import QAResult
from app.providers.openai_vision import OpenAIVisionProvider


class ImageQAJudgement(BaseModel):
    identity: float = Field(ge=0, le=1)
    garment: float = Field(ge=0, le=1)
    anatomy: float = Field(ge=0, le=1)
    scene: float = Field(ge=0, le=1)
    composition: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)


class VideoQAJudgement(BaseModel):
    identity: float = Field(ge=0, le=1)
    garment: float = Field(ge=0, le=1)
    motion: float = Field(ge=0, le=1)
    anatomy: float = Field(ge=0, le=1)
    scene: float = Field(ge=0, le=1)
    flicker: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)


class OpenAIVisualQAProvider:
    """Reference-grounded QA. It never invents a PASS score from file existence."""

    def __init__(
        self,
        api_key: str,
        model: str,
        image_prompt_path: Path,
        video_prompt_path: Path,
        base_url: str | None = None,
        client: Any | None = None,
    ):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for real visual QA")
        self.api_key = api_key
        self.model = model
        self.image_prompt_path = image_prompt_path
        self.video_prompt_path = video_prompt_path
        self.base_url = base_url
        self.client = client

    async def evaluate_image(
        self,
        shot_id: str,
        identity_reference: Path,
        product_reference: Path,
        generated_image: Path,
        expected_visible_details: list[str],
        expected_scene: str,
        thresholds: dict[str, float],
        attempt: int,
    ) -> QAResult:
        return await asyncio.to_thread(
            self._evaluate_image,
            shot_id,
            identity_reference,
            product_reference,
            generated_image,
            expected_visible_details,
            expected_scene,
            thresholds,
            attempt,
        )

    def _evaluate_image(
        self,
        shot_id: str,
        identity_reference: Path,
        product_reference: Path,
        generated_image: Path,
        expected_visible_details: list[str],
        expected_scene: str,
        thresholds: dict[str, float],
        attempt: int,
    ) -> QAResult:
        client = self._client()
        prompt = self.image_prompt_path.read_text(encoding="utf-8")
        judgement = client.responses.parse(
            model=self.model,
            instructions=prompt,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Image 1: fixed identity sheet. Image 2: outfit/theme reference. "
                                "Image 3: generated keyframe to grade. Only body-worn clothing from "
                                "Image 2 should be transferred; helmet, wings, weapons, props and "
                                f"background must not transfer. Expected garment facts: {expected_visible_details}. "
                                f"Expected scene: {expected_scene}."
                            ),
                        },
                        self._image_part(identity_reference),
                        self._image_part(product_reference),
                        self._image_part(generated_image),
                    ],
                }
            ],
            text_format=ImageQAJudgement,
        ).output_parsed
        if judgement is None:
            raise RuntimeError("OpenAI image QA returned no parsed judgement")
        scores = judgement.model_dump(exclude={"issues"})
        passed = all(scores[name] >= value for name, value in thresholds.items())
        return QAResult(
            shot_id=shot_id,
            scores=scores,
            issues=judgement.issues,
            status="PASS" if passed else "FAIL",
            attempt=attempt,
        )

    async def evaluate_video(
        self,
        shot_id: str,
        keyframe: Path,
        sampled_frames: list[Path],
        expected_visible_details: list[str],
        expected_scene: str,
        thresholds: dict[str, float],
        attempt: int,
    ) -> QAResult:
        return await asyncio.to_thread(
            self._evaluate_video,
            shot_id,
            keyframe,
            sampled_frames,
            expected_visible_details,
            expected_scene,
            thresholds,
            attempt,
        )

    def _evaluate_video(
        self,
        shot_id: str,
        keyframe: Path,
        sampled_frames: list[Path],
        expected_visible_details: list[str],
        expected_scene: str,
        thresholds: dict[str, float],
        attempt: int,
    ) -> QAResult:
        client = self._client()
        prompt = self.video_prompt_path.read_text(encoding="utf-8")
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    "Image 1 is the approved keyframe. Remaining images are chronological video "
                    "samples. Grade identity and garment against Image 1. The neutral keyframe "
                    "background is intentionally replaced by a video-generated daily-life environment; "
                    "do not penalize that planned transition. Score scene for authenticity and stability "
                    "across the video samples themselves. Penalize "
                    "any new helmet, wings, weapons, props, garment redesign, recolor or disappearing "
                    f"detail. Expected garment facts: {expected_visible_details}. "
                    f"Expected generated environment: {expected_scene}."
                ),
            },
            self._image_part(keyframe),
        ]
        content.extend(self._image_part(frame) for frame in sampled_frames)
        judgement = client.responses.parse(
            model=self.model,
            instructions=prompt,
            input=[{"role": "user", "content": content}],
            text_format=VideoQAJudgement,
        ).output_parsed
        if judgement is None:
            raise RuntimeError("OpenAI video QA returned no parsed judgement")
        scores = judgement.model_dump(exclude={"issues"})
        passed = all(scores[name] >= value for name, value in thresholds.items())
        passed = passed and judgement.flicker <= 0.15
        return QAResult(
            shot_id=shot_id,
            scores=scores,
            issues=judgement.issues,
            status="PASS" if passed else "FAIL",
            attempt=attempt,
        )

    def _client(self):
        if self.client is not None:
            return self.client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install the openai package to use real visual QA") from exc
        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return OpenAI(**kwargs)

    @staticmethod
    def _image_part(path: Path) -> dict[str, str]:
        return {
            "type": "input_image",
            "image_url": OpenAIVisionProvider._data_uri(path),
            "detail": "high",
        }
