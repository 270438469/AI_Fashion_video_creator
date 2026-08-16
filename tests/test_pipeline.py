import shutil
import json
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from app.api.dependencies import build_container
from app.orchestrator.orchestrator import Orchestrator


def test_resume_only_reuses_outputs_with_passing_qa(tmp_path: Path):
    qa = tmp_path / "qa.json"
    assert Orchestrator._qa_passed(qa) is False
    qa.write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")
    assert Orchestrator._qa_passed(qa) is False
    qa.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    assert Orchestrator._qa_passed(qa) is True


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required for the media pipeline")
async def test_offline_mock_pipeline_completes_with_real_mp4(settings):
    container = build_container(settings)
    state = container.runs.create()
    image_path = container.assets.run_dir(state.run_id) / "input" / "product.jpg"
    image = Image.new("RGB", (480, 640), "#d9c2a6")
    draw = ImageDraw.Draw(image)
    draw.polygon([(130,120),(350,120),(410,550),(70,550)], fill="#d3b18a")
    image.save(image_path, "JPEG")
    await container.orchestrator.execute(state.run_id)
    final_state = container.runs.get(state.run_id)
    final = settings.workspace_dir / "outputs" / state.run_id / "final.mp4"
    assert final_state.status == "COMPLETED"
    assert final.exists() and final.stat().st_size > 1000
    assert len(list((container.assets.run_dir(state.run_id) / "keyframes").glob("*.png"))) == 5
    assert len(list((container.assets.run_dir(state.run_id) / "videos").glob("*.mp4"))) == 5
    probe = container.ffmpeg.probe(final)
    duration = float(probe["format"]["duration"])
    assert 17.5 <= duration <= 18.5
    validation_path = settings.workspace_dir / "outputs" / state.run_id / "final_validation.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["status"] == "PASS"
    assert validation["aspect_ratio"] == "9:16"
    assert validation["clip_count"] == 5
