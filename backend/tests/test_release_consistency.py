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


def test_source_desktop_runtime_build_is_isolated_from_validation_and_release_builds():
    next_config = (ROOT / "frontend/next.config.ts").read_text(encoding="utf-8")
    mac_launcher = (ROOT / "desktop/start-council.sh").read_text(encoding="utf-8")
    windows_launcher = (ROOT / "desktop/start-council.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "setup.sh").read_text(encoding="utf-8")
    windows_installer = (ROOT / "desktop/install-windows.ps1").read_text(encoding="utf-8")
    mac_release = (ROOT / "packaging/build-macos-release.sh").read_text(encoding="utf-8")
    windows_release = (ROOT / "packaging/build-windows-release.ps1").read_text(encoding="utf-8")

    assert "COUNCIL_NEXT_DIST_DIR" in next_config
    for script in (mac_launcher, windows_launcher, installer, windows_installer):
        assert ".next-runtime" in script
        assert "COUNCIL_NEXT_DIST_DIR" in script
    for script in (mac_release, windows_release):
        assert ".next-release" in script
        assert "COUNCIL_NEXT_DIST_DIR" in script
    assert 'web/$RELEASE_DIST_DIR/static' in mac_release
    assert 'web\\$ReleaseDistDir\\static' in windows_release


def test_release_workflow_requests_packaged_javascript_and_css():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert workflow.count("check_frontend_assets.mjs") >= 2


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
