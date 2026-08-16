from pathlib import Path
from app.agents.motion_router import MotionRouter
from app.domain.models import ProductAnalysis, SceneDecision
from app.services.config_loader import ConfigLoader


ROOT = Path(__file__).resolve().parent.parent
loader = ConfigLoader(ROOT / "config")
router = MotionRouter(loader.load("motion_library.json"), loader.load("motion_router.json"))


def analysis(subcategory="bodycon_mini_dress", length="mini"):
    return ProductAnalysis(category="dress", subcategory=subcategory, primary_color="beige", length=length,
        style_tags=["feminine"], season_tags=["summer"], occasion_tags=["date"], source_view="front", confidence=.9)


def scene(scene_id):
    return SceneDecision(primary_scene=scene_id, confidence=.9, rankings=[], reason="test")


def test_bodycon_cafe_route_matches_acceptance_fixture():
    result = router.route(analysis(), scene("SC04"))
    assert result.motion_ids == ["M10","M01","M04","M07","M10"]
    assert "M08" not in result.motion_ids
    assert "full_360_turn" in result.rejected_motion_ids


def test_long_dress_uses_m08():
    result = router.route(analysis("long_dress", "maxi"), scene("SC11"))
    assert "M08" in result.motion_ids


def test_office_never_uses_coffee_motion():
    result = router.route(analysis("blazer"), scene("SC07"))
    assert "M04" not in result.motion_ids
    assert "M06" in result.motion_ids


def test_all_selected_motions_obey_rotation_policy():
    result = router.route(analysis(), scene("SC04"))
    assert all(router.motions[mid]["max_rotation_deg"] <= 55 for mid in result.motion_ids)

