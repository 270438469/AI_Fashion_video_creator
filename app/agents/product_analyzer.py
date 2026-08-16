from pathlib import Path
from app.providers.base.vision_provider import VisionProvider
from app.domain.models import ProductAnalysis


class ProductAnalyzer:
    def __init__(self, provider: VisionProvider):
        self.provider = provider

    async def analyze(self, product_image: Path) -> ProductAnalysis:
        return await self.provider.analyze_product(product_image)

