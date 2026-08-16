from abc import ABC, abstractmethod
from pathlib import Path
from app.domain.models import Asset


class ComposerProvider(ABC):
    @abstractmethod
    async def compose(self, clips: list[Path], output_path: Path) -> Asset:
        raise NotImplementedError

