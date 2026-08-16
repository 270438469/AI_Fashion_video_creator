from abc import ABC, abstractmethod
from pathlib import Path
from app.domain.models import Asset


class VideoProvider(ABC):
    @abstractmethod
    async def generate_video(self, start_frame: Path, prompt: str, duration: float, output_path: Path) -> Asset:
        raise NotImplementedError

