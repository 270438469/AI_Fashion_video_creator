from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.domain.models import ProductAnalysis
from app.providers.openai_vision import OpenAIVisionProvider


class FakeResponses:
    def __init__(self):
        self.request = None

    def parse(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            output_parsed=ProductAnalysis(
                category="top",
                subcategory="ribbed_tank_top",
                primary_color="white",
                sleeve="sleeveless",
                neckline="square_scoop_neck",
                length="hip_length",
                fit="fitted",
                style_tags=["minimal", "casual"],
                season_tags=["summer"],
                occasion_tags=["daily"],
                visible_details=["white_ribbed_fabric", "wide_shoulder_straps"],
                unknown_details=["back_neckline", "fiber_content"],
                source_view="front",
                confidence=0.93,
            )
        )


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_openai_vision_uses_image_and_structured_product_schema(tmp_path: Path):
    image_path = tmp_path / "garment.png"
    Image.new("RGB", (320, 480), "white").save(image_path)
    prompt_path = tmp_path / "product_analysis.md"
    prompt_path.write_text("evidence only", encoding="utf-8")
    client = FakeClient()
    provider = OpenAIVisionProvider(
        "test-key", model="gpt-5-mini", prompt_path=prompt_path, client=client
    )

    analysis = await provider.analyze_product(image_path)

    request = client.responses.request
    image_part = request["input"][0]["content"][1]
    assert request["model"] == "gpt-5-mini"
    assert request["instructions"] == "evidence only"
    assert request["text_format"] is ProductAnalysis
    assert image_part["type"] == "input_image"
    assert image_part["detail"] == "high"
    assert image_part["image_url"].startswith("data:image/png;base64,")
    assert analysis.category == "top"
    assert "white_ribbed_fabric" in analysis.visible_details
