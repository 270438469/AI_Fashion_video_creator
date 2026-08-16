import json
from pathlib import Path

import pytest
from PIL import Image

from app.services.character_asset_builder import CharacterAssetBuilder
from app.services.character_registry import CharacterRegistry


def test_character_asset_builder_splits_master_into_independent_refs(tmp_path: Path):
    sheet = tmp_path / "sheet.png"
    Image.new("RGB", (1456, 1086), "white").save(sheet)
    outputs = CharacterAssetBuilder().build_from_master_sheet(sheet, tmp_path / "character")

    assert set(outputs) == {"identity_face", "fullbody_front", "fullbody_45", "fullbody_side"}
    for filename in outputs.values():
        path = tmp_path / "character" / filename
        assert path.exists()
        with Image.open(path) as image:
            assert image.width > 200
            assert image.height > 700


def test_character_registry_rejects_missing_identity_assets_instead_of_mocking_them(
    tmp_path: Path,
):
    pack = tmp_path / "asian_girl_001"
    pack.mkdir()
    (pack / "character.json").write_text(
        json.dumps(
            {
                "id": "asian_girl_001",
                "gender": "female",
                "appearance": "East Asian",
                "visual_age": "22-26",
                "style": "daily",
                "hair": "black",
                "skin": "natural",
                "body": "natural",
                "identity_lock": True,
                "references": {"identity_face": "missing.png"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="missing approved references"):
        CharacterRegistry(tmp_path).get("asian_girl_001")
