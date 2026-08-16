from abc import ABC, abstractmethod
from pathlib import Path
from app.domain.models import Asset


class ImageProvider(ABC):
    @abstractmethod
    async def generate_keyframe(self, character_refs: list[Path], product_image: Path, prompt: str, output_path: Path) -> Asset:
        raise NotImplementedError

