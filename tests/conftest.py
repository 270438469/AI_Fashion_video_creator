from pathlib import Path
import pytest
from app.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parent.parent
    return Settings(
        workspace_dir=tmp_path / "workspace", character_dir=root / "characters",
        provider_mode="mock", vision_provider="mock", image_provider="mock",
        video_provider="mock", allow_mock_generation=True,
        ffmpeg_path="ffmpeg", ffprobe_path="ffprobe"
    )
