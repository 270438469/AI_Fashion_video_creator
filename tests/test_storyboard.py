from pathlib import Path
from app.agents.storyboard_generator import StoryboardGenerator
from app.domain.models import ProductAnalysis, SceneDecision, MotionDecision
from app.services.config_loader import ConfigLoader


ROOT = Path(__file__).resolve().parent.parent
generator = StoryboardGenerator(ConfigLoader(ROOT / "config").load("storyboard_template.json"))


def test_storyboard_acceptance_invariants():
    analysis = ProductAnalysis(category="dress", subcategory="bodycon_mini_dress", primary_color="beige",
        style_tags=["sweet"], season_tags=["summer"], occasion_tags=["date"], visible_details=["front_buttons","fitted_waist","short_sleeves"], source_view="front", confidence=.94)
    scene = SceneDecision(primary_scene="SC04", confidence=.99, rankings=[], reason="test")
    motions = MotionDecision(motion_ids=["M10","M01","M04","M07","M10"])
    board = generator.build(analysis, scene, motions, "asian_girl_001")
    assert len(board.shots) == 5
    assert 15 <= sum(shot.duration for shot in board.shots) <= 20
    assert board.scene_id == "SC04"
    assert board.shots[3].shot_type == "product_detail"
    assert board.shots[4].shot_type == "ending"
    assert board.shots[3].product_focus == ["buttons", "waistline", "sleeves"]
    assert all(shot.prompt_context["max_body_rotation_deg"] <= 55 for shot in board.shots)

