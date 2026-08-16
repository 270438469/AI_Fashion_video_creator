import json
import shutil
from pathlib import Path
from typing import Any


class AssetManager:
    SUBDIRS = ["input", "analysis", "prompts", "keyframes", "image_qa", "videos", "video_qa", "logs", "final"]

    def __init__(self, workspace: Path):
        self.workspace = workspace
        for name in ["characters", "inputs", "runs", "outputs", "cache", "logs", "temp"]:
            (workspace / name).mkdir(parents=True, exist_ok=True)

    def create_run(self, run_id: str) -> Path:
        root = self.workspace / "runs" / run_id
        for subdir in self.SUBDIRS:
            (root / subdir).mkdir(parents=True, exist_ok=True)
        return root

    def run_dir(self, run_id: str) -> Path:
        return self.workspace / "runs" / run_id

    def write_json(self, run_id: str, relative: str, data: Any) -> Path:
        target = self.run_dir(run_id) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def read_json(self, run_id: str, relative: str) -> dict:
        return json.loads((self.run_dir(run_id) / relative).read_text(encoding="utf-8"))

    def copy_input(self, run_id: str, source: Path, suffix: str) -> Path:
        target = self.run_dir(run_id) / "input" / f"product{suffix.lower()}"
        shutil.copy2(source, target)
        return target

    def publish(self, run_id: str) -> Path:
        source = self.run_dir(run_id)
        output = self.workspace / "outputs" / run_id
        output.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "final" / "final.mp4", output / "final.mp4")
        shutil.copy2(
            source / "final" / "final_validation.json",
            output / "final_validation.json",
        )
        shutil.copy2(source / "keyframes" / "S01.png", output / "cover.jpg")
        shutil.copy2(source / "analysis" / "storyboard.json", output / "storyboard.json")
        shutil.copy2(source / "analysis" / "product_analysis.json", output / "product_analysis.json")
        return output
