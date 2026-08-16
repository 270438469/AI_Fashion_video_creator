from pathlib import Path
from types import SimpleNamespace

import pytest

from app.providers.openai_visual_qa import (
    ImageQAJudgement,
    OpenAIVisualQAProvider,
    VideoQAJudgement,
)


class FakeResponses:
    def __init__(self):
        self.requests = []

    def parse(self, **kwargs):
        self.requests.append(kwargs)
        if kwargs["text_format"] is ImageQAJudgement:
            parsed = ImageQAJudgement(
                identity=0.96,
                garment=0.91,
                anatomy=0.95,
                scene=0.90,
                composition=0.92,
                issues=[],
            )
        else:
            parsed = VideoQAJudgement(
                identity=0.94,
                garment=0.92,
                motion=0.86,
                anatomy=0.91,
                scene=0.90,
                flicker=0.08,
                issues=[],
            )
        return SimpleNamespace(output_parsed=parsed)


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_reference_grounded_image_and_video_qa(tmp_path: Path):
    paths = []
    for name in ("identity.png", "theme.png", "generated.png", "frame1.jpg", "frame2.jpg", "frame3.jpg"):
        path = tmp_path / name
        path.write_bytes(b"image-bytes")
        paths.append(path)
    image_prompt = tmp_path / "image_qa.md"
    video_prompt = tmp_path / "video_qa.md"
    image_prompt.write_text("strict image qa", encoding="utf-8")
    video_prompt.write_text("strict video qa", encoding="utf-8")
    client = FakeClient()
    provider = OpenAIVisualQAProvider(
        "test-key", "gpt-5-mini", image_prompt, video_prompt, client=client
    )

    image_result = await provider.evaluate_image(
        "S01", paths[0], paths[1], paths[2], ["black_body_armor"],
        "neutral studio", {"identity": 0.9, "garment": 0.88, "anatomy": 0.9,
                           "scene": 0.85, "composition": 0.8}, 1,
    )
    video_result = await provider.evaluate_video(
        "S01", paths[2], paths[3:], ["black_body_armor"],
        "authentic East Asian apartment balcony",
        {"identity": 0.88, "garment": 0.86, "motion": 0.78,
         "anatomy": 0.85, "scene": 0.85}, 1,
    )

    assert image_result.status == "PASS"
    assert video_result.status == "PASS"
    assert len(client.responses.requests) == 2
    image_content = client.responses.requests[0]["input"][0]["content"]
    video_content = client.responses.requests[1]["input"][0]["content"]
    assert len([item for item in image_content if item["type"] == "input_image"]) == 3
    assert len([item for item in video_content if item["type"] == "input_image"]) == 4
    assert "helmet, wings, weapons" in image_content[0]["text"]
    assert "intentionally replaced" in video_content[0]["text"]
