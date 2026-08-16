import json
from pathlib import Path
from typing import Any


class ConfigLoader:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir

    def load(self, name: str) -> Any:
        with (self.config_dir / name).open("r", encoding="utf-8") as handle:
            return json.load(handle)

