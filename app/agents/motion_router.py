from app.domain.models import MotionDecision, ProductAnalysis, SceneDecision


class MotionRouter:
    def __init__(self, motions: list[dict], config: dict):
        self.motions = {motion["id"]: motion for motion in motions}
        self.config = config

    def route(self, analysis: ProductAnalysis, scene: SceneDecision) -> MotionDecision:
        key = analysis.subcategory or analysis.category or "default"
        mapping = self.config["mappings"].get(key)
        if mapping is None:
            mapping = self.config["mappings"].get(analysis.category, self.config["mappings"]["default"])
        selected = list(mapping)
        lifestyle = self.config.get("scene_lifestyle", {}).get(scene.primary_scene)
        if lifestyle:
            selected[2] = lifestyle
        if scene.primary_scene == "SC07" and selected[2] == "M04":
            selected[2] = "M06"
        if analysis.length not in {"midi", "maxi", "long"} and analysis.subcategory != "long_dress":
            selected = ["M01" if motion == "M08" else motion for motion in selected]
        rejected = list(self.config["forbidden"])
        for motion_id in selected:
            if self.motions[motion_id].get("max_rotation_deg", 0) > self.config["max_body_rotation_deg"]:
                raise ValueError(f"Motion {motion_id} violates the single-front-image rotation policy")
        return MotionDecision(motion_ids=selected, rejected_motion_ids=rejected,
                              reason=f"Five-shot low-risk motion route for {key} in {scene.primary_scene}; body rotation <= 55 degrees.")

