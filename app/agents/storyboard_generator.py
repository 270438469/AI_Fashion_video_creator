from app.domain.models import MotionDecision, ProductAnalysis, SceneDecision, Storyboard, StoryboardShot


class StoryboardGenerator:
    def __init__(self, template: dict):
        self.template = template

    def build(self, analysis: ProductAnalysis, scene: SceneDecision, motions: MotionDecision, character_id: str) -> Storyboard:
        details = [self._normalize_detail(item) for item in analysis.visible_details][:3]
        shots = []
        for item in self.template["shots"]:
            focus = details if item["shot_id"] == "S04" and details else item["default_focus"]
            shots.append(StoryboardShot(
                shot_id=item["shot_id"], duration=item["duration"], shot_type=item["shot_type"],
                framing=item["framing"], motion_id=motions.motion_ids[item["motion_slot"]],
                camera_motion=item["camera_motion"], keyframe_type=item["keyframe_type"], product_focus=focus,
                prompt_context={"known_view_policy": "front_single_image", "max_body_rotation_deg": 55}
            ))
        return Storyboard(scene_id=scene.primary_scene, character_id=character_id,
                          aspect_ratio=self.template["aspect_ratio"], target_duration=self.template["target_duration"], shots=shots)

    @staticmethod
    def _normalize_detail(detail: str) -> str:
        aliases = {"front_buttons": "buttons", "fitted_waist": "waistline", "short_sleeves": "sleeves"}
        return aliases.get(detail, detail)

