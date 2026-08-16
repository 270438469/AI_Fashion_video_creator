from pathlib import Path

from app.domain.models import ProductAnalysis, StoryboardShot
from app.services.prompt_builder import PromptBuilder


def test_runway_mode_keeps_keyframe_neutral_and_generates_asian_daily_environment_in_video():
    root = Path(__file__).resolve().parent.parent
    builder = PromptBuilder(root / "prompts", video_generated_environment=True)
    analysis = ProductAnalysis(
        category="outfit", primary_color="black", visible_details=["silver zipper"]
    )
    shot = StoryboardShot(
        shot_id="S01", duration=3, shot_type="hero", framing="full body",
        motion_id="M01", camera_motion="slow push", keyframe_type="hero",
        product_focus=["overall outfit"],
    )
    scene = {
        "environment": ["small Seoul neighborhood cafe", "ordinary wood table"],
        "lighting": "soft window daylight",
    }
    motion = {"description": "takes two natural steps"}

    image_prompt = builder.image_prompt(analysis, scene, shot, motion)
    video_prompt = builder.video_prompt(shot, motion, scene)

    assert "clean neutral light-gray studio" in image_prompt
    assert "small Seoul neighborhood cafe" not in image_prompt
    assert "small Seoul neighborhood cafe" in video_prompt
    assert "authentic contemporary East Asian everyday-life location" in video_prompt
    assert "never redesign, recolor, restyle" in video_prompt
