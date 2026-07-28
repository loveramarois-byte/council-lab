import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


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


def copy_release_files(tmp_path: Path) -> None:
    for relative_path in REQUIRED_FILES:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


@pytest.mark.parametrize(
    ("relative_path", "field"),
    (
        ("frontend/package.json", "version"),
        ("frontend/package-lock.json", "version"),
        ("frontend/package-lock.json", "packages-root-version"),
    ),
)
def test_release_check_reports_mismatched_package_versions(tmp_path, relative_path, field):
    copy_release_files(tmp_path)
    package = tmp_path / relative_path
    package_data = json.loads(package.read_text(encoding="utf-8"))
    if field == "packages-root-version":
        package_data["packages"][""]["version"] = "9.9.9"
    else:
        package_data["version"] = "9.9.9"
    package.write_text(json.dumps(package_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert relative_path in result.stderr
    assert "does not match VERSION" in result.stderr
