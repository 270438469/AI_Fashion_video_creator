import json
from pathlib import Path
from app.agents.scene_router import SceneRouter
from app.domain.models import ProductAnalysis
from app.services.config_loader import ConfigLoader


ROOT = Path(__file__).resolve().parent.parent
loader = ConfigLoader(ROOT / "config")
router = SceneRouter(loader.load("scene_library.json"), loader.load("scene_router.json"))


def fixture_analysis() -> ProductAnalysis:
    return ProductAnalysis.model_validate(json.loads((ROOT / "tests/fixtures/product_analysis.json").read_text()))


def test_bodycon_fixture_selects_sc04_with_sc03_backup():
    result = router.route(fixture_analysis())
    assert result.primary_scene == "SC04"
    assert result.backup_scene == "SC03"


def test_suit_routes_to_office():
    item = fixture_analysis().model_copy(update={"category":"suit", "subcategory":"blazer", "style_tags":["business","commute"], "occasion_tags":["office","work"], "season_tags":["autumn"], "primary_color":"gray"})
    assert router.route(item).primary_scene == "SC07"


def test_evening_gown_routes_to_hotel():
    item = fixture_analysis().model_copy(update={"subcategory":"evening_gown", "length":"maxi", "style_tags":["gown","evening","luxury"], "occasion_tags":["formal","event"], "primary_color":"red"})
    assert router.route(item).primary_scene == "SC06"


def test_resort_long_dress_routes_to_sc11():
    item = fixture_analysis().model_copy(update={"subcategory":"long_dress", "length":"maxi", "style_tags":["long_dress","resort","flowy"], "occasion_tags":["vacation","resort"], "primary_color":"white"})
    assert router.route(item).primary_scene == "SC11"


def test_low_confidence_forces_studio():
    item = fixture_analysis().model_copy(update={"confidence":0.2})
    assert router.route(item).primary_scene == "SC01"

