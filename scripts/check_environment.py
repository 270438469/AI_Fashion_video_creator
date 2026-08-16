import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def version(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        return result.returncode == 0, (result.stdout or result.stderr).splitlines()[0]
    except (OSError, subprocess.TimeoutExpired):
        return False, "not found"


root = Path(__file__).resolve().parent.parent
checks = {
    "python": {"ok": sys.version_info >= (3, 10), "value": platform.python_version(), "required_native": ">=3.10"},
    "ffmpeg": dict(zip(("ok", "value"), version(["ffmpeg", "-version"]))),
    "ffprobe": dict(zip(("ok", "value"), version(["ffprobe", "-version"]))),
    "docker": dict(zip(("ok", "value"), version(["docker", "--version"]))),
    "docker_compose": dict(zip(("ok", "value"), version(["docker", "compose", "version"]))),
    "disk_free_gb": round(shutil.disk_usage(root).free / 1024**3, 1),
    "character_pack": (root / "characters" / "asian_girl_001" / "character.json").exists(),
}
try:
    gpu_ok, gpu_name = version(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
except Exception:
    gpu_ok, gpu_name = False, "not found"
checks["gpu"] = {"ok": gpu_ok, "value": gpu_name}
print(json.dumps(checks, ensure_ascii=False, indent=2))
container_ready = checks["docker"]["ok"] and checks["docker_compose"]["ok"]
native_ready = checks["python"]["ok"] and checks["ffmpeg"]["ok"] and checks["ffprobe"]["ok"]
print("\nReady via Docker." if container_ready else "\nDocker path is not ready.")
print("Native runtime ready." if native_ready else "Native runtime needs Python >=3.10 plus FFmpeg/ffprobe.")
sys.exit(0 if container_ready or native_ready else 1)

