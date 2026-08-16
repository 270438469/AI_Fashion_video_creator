from pathlib import Path
from app.domain.models import ProductAnalysis
from app.providers.base.vision_provider import VisionProvider


class MockVisionProvider(VisionProvider):
    async def analyze_product(self, image_path: Path) -> ProductAnalysis:
        if not image_path.exists():
            raise FileNotFoundError(image_path)
        return ProductAnalysis(
            category="dress", subcategory="bodycon_mini_dress", primary_color="beige",
            sleeve="short_sleeve", neckline="deep_henley", length="mini", fit="bodycon",
            material_guess="soft_stretch_fabric", style_tags=["feminine", "sweet", "korean_casual"],
            season_tags=["spring", "summer"], occasion_tags=["date", "cafe", "casual_outing"],
            visible_details=["front_buttons", "fitted_waist", "short_sleeves"],
            unknown_details=["back_closure", "back_neckline"], source_view="front", confidence=0.94
        )

