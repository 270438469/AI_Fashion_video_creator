from __future__ import annotations

from pathlib import Path

from PIL import Image


class CharacterAssetBuilder:
    """Deterministically split the approved four-view master sheet into production refs."""

    OUTPUTS = {
        "identity_face": "identity_face.png",
        "fullbody_front": "fullbody_front.png",
        "fullbody_45": "fullbody_45.png",
        "fullbody_side": "fullbody_side.png",
    }

    def build_from_master_sheet(self, master_image_path: Path, output_dir: Path) -> dict[str, str]:
        if not master_image_path.exists():
            raise FileNotFoundError(master_image_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(master_image_path) as source:
            image = source.convert("RGB")
            width, height = image.size
            # Ratios match the approved sheet layout: portrait, front, 45-degree, side.
            boxes = {
                "identity_face": (0, 0, 0.40, 0.72),
                "fullbody_front": (0.405, 0.025, 0.61, 0.97),
                "fullbody_45": (0.625, 0.025, 0.805, 0.97),
                "fullbody_side": (0.81, 0.025, 0.995, 0.97),
            }
            for role, ratios in boxes.items():
                left, top, right, bottom = ratios
                crop = image.crop(
                    (
                        int(width * left),
                        int(height * top),
                        int(width * right),
                        int(height * bottom),
                    )
                )
                crop.save(output_dir / self.OUTPUTS[role], "PNG", optimize=True)
        return dict(self.OUTPUTS)
