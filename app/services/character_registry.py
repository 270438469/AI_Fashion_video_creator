import json
from pathlib import Path
from app.domain.models import Character
from app.services.character_asset_builder import CharacterAssetBuilder


class CharacterRegistry:
    def __init__(self, root: Path):
        self.root = root

    def get(self, character_id: str) -> Character:
        pack = self.root / character_id
        config_path = pack / "character.json"
        if not config_path.exists():
            raise KeyError(f"Character pack not found: {character_id}")
        data = json.loads(config_path.read_text(encoding="utf-8"))
        source_sheet = data.get("source_sheet")
        references = data["references"]
        if source_sheet and any(not (pack / name).exists() for name in references.values()):
            CharacterAssetBuilder().build_from_master_sheet(pack / source_sheet, pack)
        missing = [name for name in references.values() if not (pack / name).exists()]
        if missing:
            raise FileNotFoundError(
                f"Character pack {character_id} is missing approved references: "
                f"{', '.join(missing)}"
            )
        return Character.model_validate(data)

    def reference_paths(self, character_id: str) -> list[Path]:
        character = self.get(character_id)
        pack = self.root / character_id
        return [pack / filename for filename in character.references.values()]
