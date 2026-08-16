from pathlib import Path
from app.domain.models import QAResult


class ImageQA:
    def __init__(self, thresholds: dict, provider=None):
        self.thresholds = thresholds
        self.provider = provider

    async def evaluate(self, shot_id: str, image_path: Path, attempt: int,
                       identity_reference: Path | None = None, product_reference: Path | None = None,
                       expected_visible_details: list[str] | None = None,
                       expected_scene: str = "") -> QAResult:
        if self.provider is not None:
            if identity_reference is None or product_reference is None:
                raise RuntimeError("Real image QA requires identity and product references")
            return await self.provider.evaluate_image(
                shot_id, identity_reference, product_reference, image_path,
                expected_visible_details or [], expected_scene, self.thresholds, attempt,
            )
        scores = {"identity": 0.96, "garment": 0.95, "anatomy": 0.97, "scene": 0.94, "composition": 0.95}
        passed = image_path.exists() and all(scores[name] >= value for name, value in self.thresholds.items())
        return QAResult(shot_id=shot_id, scores=scores, status="PASS" if passed else "FAIL", attempt=attempt,
                        issues=[] if passed else ["mock asset missing"])
