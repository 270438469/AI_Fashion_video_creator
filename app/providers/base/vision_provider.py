from abc import ABC, abstractmethod
from pathlib import Path
from app.domain.models import ProductAnalysis


class VisionProvider(ABC):
    @abstractmethod
    async def analyze_product(self, image_path: Path) -> ProductAnalysis:
        raise NotImplementedError

