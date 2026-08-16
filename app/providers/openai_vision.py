import asyncio
import base64
import mimetypes
from pathlib import Path
from typing import Any

from app.domain.models import ProductAnalysis
from app.providers.base.vision_provider import VisionProvider


class OpenAIVisionProvider(VisionProvider):
    """Evidence-only garment analysis using an OpenAI vision model."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-mini",
        prompt_path: Path | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when VISION_PROVIDER=openai")
        self.api_key = api_key
        self.model = model
        self.prompt_path = prompt_path
        self.base_url = base_url
        self.client = client

    async def analyze_product(self, image_path: Path) -> ProductAnalysis:
        if not image_path.exists():
            raise FileNotFoundError(image_path)
        return await asyncio.to_thread(self._analyze, image_path)

    def _analyze(self, image_path: Path) -> ProductAnalysis:
        client = self.client
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "Install the openai package to use VISION_PROVIDER=openai"
                ) from exc
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            client = OpenAI(**kwargs)

        prompt = (
            self.prompt_path.read_text(encoding="utf-8")
            if self.prompt_path and self.prompt_path.exists()
            else "Analyze only visibly supported garment facts."
        )
        response = client.responses.parse(
            model=self.model,
            instructions=prompt,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Analyze this single uploaded garment/product image. "
                                "Return the complete ProductAnalysis schema."
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": self._data_uri(image_path),
                            "detail": "high",
                        },
                    ],
                }
            ],
            text_format=ProductAnalysis,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI vision response did not contain parsed garment analysis")
        analysis = ProductAnalysis.model_validate(parsed)
        return analysis.model_copy(
            update={"confidence": max(0.0, min(1.0, analysis.confidence))}
        )

    @staticmethod
    def _data_uri(path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
