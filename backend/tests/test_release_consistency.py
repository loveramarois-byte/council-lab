import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_release_consistency.py"
REQUIRED_FILES = (
    "VERSION",
    "frontend/package.json",
    "frontend/package-lock.json",
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "backend/app/updater.py",
    "docs/ARCHITECTURE.md",
)


def run_check(root: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_release_metadata_is_consistent():
    result = run_check(ROOT)
    assert result.returncode == 0, result.stderr


def test_release_check_reports_the_mismatched_file(tmp_path):
    for relative_path in REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    package = tmp_path / "frontend/package.json"
    package_data = json.loads(package.read_text(encoding="utf-8"))
    package_data["version"] = "9.9.9"
    package.write_text(json.dumps(package_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "frontend/package.json" in result.stderr
    assert "does not match VERSION" in result.stderr
