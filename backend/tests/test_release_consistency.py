import json
import socket
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_release_consistency.py"
RELEASE_NOTES_SCRIPT = ROOT / "scripts" / "build_release_notes.py"
GITEE_RELEASE_SCRIPT = ROOT / "scripts" / "publish_gitee_release.py"
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


def test_make_backend_test_uses_the_repository_virtual_environment_from_root():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    backend_target = makefile.split("backend-test:\n", 1)[1].split("\n\n", 1)[0]

    assert "backend/.venv/bin/python -m pytest -q backend/tests" in backend_target
    assert "cd backend" not in backend_target


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
        assert "--collect-all tzdata" in script
    requirements = (ROOT / "backend/requirements.lock").read_text(encoding="utf-8")
    assert "tzdata==" in requirements
    assert 'web/$RELEASE_DIST_DIR/static' in mac_release
    assert 'web\\$ReleaseDistDir\\static' in windows_release
    assert 'frontend/public" "$RESOURCES_DIR/web/public' in mac_release
    assert 'frontend\\public") (Join-Path $StageDir "web\\public' in windows_release


def test_release_workflow_requests_packaged_javascript_and_css():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert workflow.count("check_frontend_assets.mjs") >= 2
    assert '[[ "$backend_runtime" == macos:* ]]' in workflow
    assert 'if ($staleHealth.runtime_id -eq $staleRuntime' in workflow
    assert 'Launcher did not replace stale Council processes' in workflow
    assert "python -m pytest backend/tests/test_release_consistency.py -k macos_launcher" in workflow
    assert "build_release_notes.py --output artifacts/RELEASE_NOTES.md" in workflow
    assert workflow.count("--notes-file artifacts/RELEASE_NOTES.md") == 2
    assert workflow.count("web/public/sw.js") >= 1
    assert workflow.count('web\\public\\sw.js') >= 1
    assert workflow.count("http://127.0.0.1:3000/sw.js") >= 2
    assert "Publish Gitee Release" in workflow
    assert "secrets.GITEE_ACCESS_TOKEN" in workflow
    assert "publish_gitee_release.py" in workflow
    github_publish = workflow.split("      - name: Publish GitHub Release\n", 1)[1].split("      - name: Publish Gitee Release\n", 1)[0]
    assert github_publish.rstrip().endswith("fi")


def test_gitee_release_can_be_replayed_from_verified_github_assets():
    workflow = (ROOT / ".github/workflows/gitee-release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "council-gitee-local" in workflow
    assert "inputs.runner == 'council-gitee-local'" in workflow
    assert 'gh release download "${tag}"' in workflow
    assert "sha256sum -c SHA256SUMS.txt" in workflow
    assert 'git show "${tag}:VERSION"' in workflow
    assert 'git show "${tag}:CHANGELOG.md"' in workflow
    assert "--root release-source" in workflow
    assert "build_release_notes.py" in workflow
    assert "publish_gitee_release.py" in workflow
    assert "GITEE_ACCESS_TOKEN" in workflow


def test_release_smoke_preserves_internal_api_authentication_on_both_platforms():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    macos_job = workflow.split("\n  macos:\n", 1)[1].split("\n  windows:\n", 1)[0]
    windows_job = workflow.split("\n  windows:\n", 1)[1].split("\n  publish:\n", 1)[0]

    assert 'backend-access.token' in macos_job
    assert 'http://127.0.0.1:8001/api/update/status)\" = \"403\"' in macos_job
    assert 'curl -fsS -H "X-Council-Internal-Token: $internal_token" http://127.0.0.1:8001/api/update/status' in macos_job

    assert 'backend-access.token' in windows_job
    assert '$unauthorizedUpdateStatus -ne 403' in windows_job
    assert 'Invoke-RestMethod http://127.0.0.1:8001/api/update/status -Headers @{ "X-Council-Internal-Token" = $internalToken }' in windows_job
    assert 'packaged-backend.stderr.log' in windows_job
    assert 'packaged-frontend.stderr.log' in windows_job
    assert 'Last health error:' in windows_job
    assert 'Backend exited:' in windows_job
    assert 'Frontend exited:' in windows_job


def test_release_notes_include_version_changes_and_installation(tmp_path):
    output = tmp_path / "RELEASE_NOTES.md"
    result = subprocess.run(
        [sys.executable, str(RELEASE_NOTES_SCRIPT), "--root", str(ROOT), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    notes = output.read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section_start = changelog.index(f"## [{version}]")
    section_body_start = changelog.index("\n", section_start) + 1
    section_end = changelog.find("\n## [", section_body_start)
    expected_body = changelog[section_body_start : section_end if section_end >= 0 else None].strip()

    assert f"Council v{version} 更新内容" in notes
    assert expected_body
    assert expected_body in notes
    assert "## 安装与升级" in notes


def test_release_notes_reject_an_empty_current_version_section(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [9.9.9] - 2026-07-31\n\n## [9.9.8] - 2026-07-30\n\n- Previous.\n",
        encoding="utf-8",
    )
    output = tmp_path / "RELEASE_NOTES.md"

    result = subprocess.run(
        [sys.executable, str(RELEASE_NOTES_SCRIPT), "--root", str(root), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "empty release section" in result.stderr
    assert not output.exists()


def test_release_notes_exclude_previous_version_content(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [9.9.9] - 2026-07-31\n\n- Current-only marker.\n\n"
        "## [9.9.8] - 2026-07-30\n\n- Previous-only marker.\n",
        encoding="utf-8",
    )
    output = tmp_path / "RELEASE_NOTES.md"

    result = subprocess.run(
        [sys.executable, str(RELEASE_NOTES_SCRIPT), "--root", str(root), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    notes = output.read_text(encoding="utf-8")
    assert "Current-only marker." in notes
    assert "Previous-only marker." not in notes


def test_packaged_launchers_only_reuse_services_from_the_same_installation():
    mac_launcher = (ROOT / "desktop/start-bundled.sh").read_text(encoding="utf-8")
    windows_launcher = (ROOT / "desktop/start-bundled.ps1").read_text(encoding="utf-8")
    backend = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    frontend_health = (ROOT / "frontend/app/mobile-access/health/route.ts").read_text(encoding="utf-8")

    for source in (mac_launcher, windows_launcher, backend, frontend_health):
        assert "COUNCIL_RUNTIME_ID" in source or "runtime_identity" in source
    assert "service_is_current" in mac_launcher
    assert "stop_existing_council_service" in mac_launcher
    assert "listeners_before" in mac_launcher
    assert "process_is_council" in mac_launcher
    assert "\"$APP_ROOT\" \"$COUNCIL_VERSION\"" in mac_launcher
    assert "internal_api_id" in mac_launcher
    assert "$Health.runtime_id -eq $env:COUNCIL_RUNTIME_ID" in windows_launcher
    assert "$Health.internal_api_id -eq $InternalApiId" in windows_launcher
    assert "Stop-ExistingCouncilService" in windows_launcher
    assert "$ProcessIdsBefore -contains $ProcessId" in windows_launcher
    assert "Test-CouncilProcessOwnership" in windows_launcher
    assert '$RuntimeSeed = "$PackageRoot$([char]0)$($env:COUNCIL_VERSION)"' in windows_launcher


def _free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _health_server(
    port: int,
    service: str,
    runtime_id: str,
    cwd: Path | None = None,
    internal_api_id: str = "current-token-id",
) -> subprocess.Popen[str]:
    source = """
import http.server
import json
import sys

port = int(sys.argv[1])
payload = json.dumps({"status": "ok", "service": sys.argv[2], "runtime_id": sys.argv[3], "internal_api_id": sys.argv[4]}, separators=(",", ":")).encode()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass

http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", source, str(port), service, runtime_id, internal_api_id],
        text=True,
        cwd=cwd,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.1).close()
            return process
        except OSError:
            time.sleep(0.02)
    process.terminate()
    process.wait(timeout=2)
    raise AssertionError("health fixture did not start")


@pytest.mark.skipif(sys.platform != "darwin", reason="exercises the macOS launcher with system lsof and zsh")
def test_macos_launcher_reuses_only_current_install_and_replaces_stale_council(tmp_path):
    launcher = (ROOT / "desktop/start-bundled.sh").read_text(encoding="utf-8")
    helpers = launcher[launcher.index("service_is_current()") : launcher.index("if [[ ! -x")]
    helper_script = tmp_path / "launcher-helpers.zsh"
    helper_script.write_text(
        f"set -u\nCOUNCIL_RUNTIME_ID=current-install\nINTERNAL_API_ID=current-token-id\n{helpers}",
        encoding="utf-8",
    )

    current_port = _free_port()
    current = _health_server(current_port, "council-lab", "current-install")
    try:
        matched = subprocess.run(
            ["/bin/zsh", "-c", 'source "$1"; service_is_current "$2" council-lab', "test", str(helper_script), f"http://127.0.0.1:{current_port}/health"],
            check=False,
        )
        assert matched.returncode == 0
        assert current.poll() is None
    finally:
        current.terminate()
        current.wait(timeout=2)

    stale_port = _free_port()
    frontend_dir = tmp_path / "frontend"
    (frontend_dir / "app").mkdir(parents=True)
    (frontend_dir / "package.json").write_text('{"name":"council-lab-web"}\n', encoding="utf-8")
    (frontend_dir / "next.config.ts").write_text("export default {};\n", encoding="utf-8")
    (frontend_dir / "app/layout.tsx").write_text("export default function Layout() {}\n", encoding="utf-8")
    stale = _health_server(stale_port, "council-mobile-access", "old-install", cwd=frontend_dir)
    stopped = subprocess.run(
        ["/bin/zsh", "-c", 'source "$1"; stop_existing_council_service "$2" "$3" council-mobile-access', "test", str(helper_script), str(stale_port), f"http://127.0.0.1:{stale_port}/health"],
        check=False,
    )
    assert stopped.returncode == 0
    stale.wait(timeout=2)


@pytest.mark.skipif(sys.platform != "darwin", reason="exercises the macOS launcher with system lsof and zsh")
def test_macos_launcher_never_stops_a_foreign_service_spoofing_council_health(tmp_path):
    launcher = (ROOT / "desktop/start-bundled.sh").read_text(encoding="utf-8")
    helpers = launcher[launcher.index("service_is_current()") : launcher.index("if [[ ! -x")]
    helper_script = tmp_path / "launcher-helpers.zsh"
    helper_script.write_text(
        f"set -u\nCOUNCIL_RUNTIME_ID=current-install\nINTERNAL_API_ID=current-token-id\n{helpers}",
        encoding="utf-8",
    )
    port = _free_port()
    foreign = _health_server(port, "council-lab", "foreign")
    try:
        result = subprocess.run(
            ["/bin/zsh", "-c", 'source "$1"; stop_existing_council_service "$2" "$3" council-lab', "test", str(helper_script), str(port), f"http://127.0.0.1:{port}/health"],
            check=False,
        )
        assert result.returncode != 0
        assert foreign.poll() is None
    finally:
        foreign.terminate()
        foreign.wait(timeout=2)


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
