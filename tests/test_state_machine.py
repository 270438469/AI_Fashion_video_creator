from pathlib import Path
from app.db.database import Database
from app.services.asset_manager import AssetManager
from app.services.run_manager import RunManager


def test_state_is_durable_and_nonterminal_run_becomes_interrupted(tmp_path):
    assets = AssetManager(tmp_path / "workspace")
    runs = RunManager(Database(tmp_path / "workspace/app.db"), assets)
    state = runs.create()
    runs.update(state.run_id, "VIDEOS_GENERATING", 72, "Generating S03", "video_generation", "running")
    second_manager = RunManager(Database(tmp_path / "workspace/app.db"), assets)
    assert second_manager.get(state.run_id).status == "VIDEOS_GENERATING"
    assert second_manager.mark_interrupted() == [state.run_id]
    assert second_manager.get(state.run_id).status == "INTERRUPTED"


def test_shot_attempts_are_isolated(tmp_path):
    assets = AssetManager(tmp_path / "workspace")
    runs = RunManager(Database(tmp_path / "workspace/app.db"), assets)
    state = runs.create()
    assert runs.increment_attempt(state.run_id, "S03", "video") == 1
    saved = runs.get(state.run_id)
    assert saved.shot_attempts["S03"]["video"] == 1
    assert "S02" not in saved.shot_attempts

