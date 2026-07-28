import asyncio
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.updater import (
    MAX_DOWNLOAD_BYTES,
    MAX_CHECKSUM_BYTES,
    Installation,
    Release,
    UpdateError,
    UpdateManager,
    expected_package_name,
    install_request_is_allowed,
    installation_info,
    is_newer,
    parse_checksum,
    parse_release,
    public_update_info,
    safe_extract_zip,
)


def release_payload(version: str = "0.4.0") -> dict:
    base = f"https://github.com/loveramarois-byte/council-lab/releases/download/v{version}"
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/loveramarois-byte/council-lab/releases/tag/v{version}",
        "published_at": "2026-07-28T00:00:00Z",
        "body": "Verified updater release.",
        "assets": [
            {"name": f"Council-v{version}-macOS.zip", "browser_download_url": f"{base}/Council-v{version}-macOS.zip"},
            {"name": f"Council-v{version}-Windows.zip", "browser_download_url": f"{base}/Council-v{version}-Windows.zip"},
            {"name": "SHA256SUMS.txt", "browser_download_url": f"{base}/SHA256SUMS.txt"},
        ],
    }


def test_versions_use_stable_semver_and_numeric_ordering():
    assert is_newer("0.10.0", "0.9.9")
    assert not is_newer("0.4.0", "0.4.0")
    with pytest.raises(UpdateError):
        is_newer("0.4.0-beta.1", "0.3.0")


def test_install_requires_council_specific_request_header():
    assert install_request_is_allowed("app")
    assert not install_request_is_allowed(None)
    assert not install_request_is_allowed("external-page")


def test_release_selects_exact_platform_asset_and_rejects_untrusted_url():
    release = parse_release(release_payload(), "macos")
    assert release.package_name == "Council-v0.4.0-macOS.zip"
    assert release.package_url.endswith("/Council-v0.4.0-macOS.zip")
    assert release.checksum_url.endswith("/SHA256SUMS.txt")
    assert expected_package_name("0.4.0", "windows") == "Council-v0.4.0-Windows.zip"

    payload = release_payload()
    payload["assets"][0]["browser_download_url"] = "https://example.com/forged.zip"
    assert parse_release(payload, "macos").package_url is None

    payload = release_payload()
    payload["assets"][2]["browser_download_url"] = "https://example.com/forged-checksums.txt"
    assert parse_release(payload, "macos").checksum_url is None


def test_checksum_requires_exact_filename():
    checksum = "a" * 64
    assert parse_checksum(f"{checksum}  Council-v0.4.0-macOS.zip\n", "Council-v0.4.0-macOS.zip") == checksum
    with pytest.raises(UpdateError):
        parse_checksum(f"{checksum}  another.zip\n", "Council-v0.4.0-macOS.zip")
    with pytest.raises(UpdateError):
        parse_checksum(f"{checksum}  nested/Council-v0.4.0-macOS.zip\n", "Council-v0.4.0-macOS.zip")


def test_safe_extract_rejects_traversal_and_restores_unix_metadata(tmp_path):
    archive_path = tmp_path / "valid.zip"
    info = zipfile.ZipInfo("Council.app/Contents/Resources/launcher/update-council.sh")
    info.external_attr = (stat.S_IFREG | 0o755) << 16
    link = zipfile.ZipInfo("Council.app/Contents/Resources/current-launcher")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "#!/bin/zsh\n")
        archive.writestr(link, "launcher/update-council.sh")
    destination = tmp_path / "valid"
    safe_extract_zip(archive_path, destination)
    extracted = destination / info.filename
    assert extracted.stat().st_mode & 0o777 == 0o755
    extracted_link = destination / link.filename
    assert extracted_link.is_symlink()
    assert extracted_link.resolve() == extracted.resolve()

    malicious_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious_path, "w") as archive:
        archive.writestr("../outside.txt", "blocked")
    with pytest.raises(UpdateError, match="越界路径"):
        safe_extract_zip(malicious_path, tmp_path / "malicious")

    symlink_path = tmp_path / "symlink.zip"
    escaping_link = zipfile.ZipInfo("Council.app/escape")
    escaping_link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink_path, "w") as archive:
        archive.writestr(escaping_link, "../../outside")
    with pytest.raises(UpdateError, match="越界符号链接"):
        safe_extract_zip(symlink_path, tmp_path / "symlink")

    corrupt_path = tmp_path / "corrupt.zip"
    corrupt_path.write_text("not a zip", encoding="utf-8")
    with pytest.raises(zipfile.BadZipFile):
        safe_extract_zip(corrupt_path, tmp_path / "corrupt")


def test_safe_extract_enforces_expanded_size_limit(tmp_path, monkeypatch):
    archive_path = tmp_path / "oversized.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("payload.bin", b"12345")
    monkeypatch.setattr("app.updater.MAX_EXTRACTED_BYTES", 4)
    with pytest.raises(UpdateError, match="体积异常"):
        safe_extract_zip(archive_path, tmp_path / "oversized")


def test_safe_extract_rejects_duplicate_paths_and_excessive_entries(tmp_path, monkeypatch):
    duplicate_path = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning), zipfile.ZipFile(duplicate_path, "w") as archive:
        archive.writestr("same.txt", "first")
        archive.writestr("same.txt", "second")
    with pytest.raises(UpdateError, match="重复路径"):
        safe_extract_zip(duplicate_path, tmp_path / "duplicate")

    many_entries = tmp_path / "many.zip"
    with zipfile.ZipFile(many_entries, "w") as archive:
        archive.writestr("one.txt", "1")
        archive.writestr("two.txt", "2")
    monkeypatch.setattr("app.updater.MAX_ARCHIVE_ENTRIES", 1)
    with pytest.raises(UpdateError, match="文件数量异常"):
        safe_extract_zip(many_entries, tmp_path / "many")


def test_packaged_macos_installation_and_public_update_info(tmp_path, monkeypatch):
    app_root = tmp_path / "Council.app"
    (app_root / "Contents" / "Resources").mkdir(parents=True)
    monkeypatch.setenv("COUNCIL_PACKAGED", "1")
    monkeypatch.setenv("COUNCIL_UPDATE_PLATFORM", "macos")
    monkeypatch.setenv("COUNCIL_INSTALL_ROOT", str(app_root))
    monkeypatch.setenv("COUNCIL_VERSION", "0.3.0")

    installation = installation_info()
    assert installation.can_auto_update
    info = public_update_info(parse_release(release_payload(), "macos"))
    assert info["current_version"] == "0.3.0"
    assert info["latest_version"] == "0.4.0"
    assert info["update_available"] is True
    assert info["can_auto_update"] is True


def test_auto_update_refuses_install_root_that_contains_user_data(tmp_path, monkeypatch):
    app_root = tmp_path / "Council"
    (app_root / "runtime").mkdir(parents=True)
    (app_root / "runtime" / "start-council.ps1").touch()
    monkeypatch.setenv("COUNCIL_PACKAGED", "1")
    monkeypatch.setenv("COUNCIL_UPDATE_PLATFORM", "windows")
    monkeypatch.setenv("COUNCIL_INSTALL_ROOT", str(app_root))
    monkeypatch.setenv("COUNCIL_DATA_DIR", str(app_root / "data"))

    installation = installation_info()
    assert installation.can_auto_update is False
    assert "避免覆盖数据" in installation.reason


def test_installation_modes_and_public_current_release(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNCIL_UPDATE_PLATFORM", "unsupported")
    monkeypatch.delenv("COUNCIL_PACKAGED", raising=False)
    monkeypatch.delenv("COUNCIL_INSTALL_ROOT", raising=False)
    assert installation_info().can_auto_update is False
    assert "暂不支持" in installation_info().reason

    monkeypatch.setenv("COUNCIL_UPDATE_PLATFORM", "macos")
    monkeypatch.setenv("COUNCIL_VERSION", "0.4.0")
    info = public_update_info(parse_release(release_payload(), "macos"))
    assert info["update_available"] is False
    assert info["can_auto_update"] is False
    assert info["installation_kind"] == "development"

    payload = release_payload()
    payload["assets"] = []
    info = public_update_info(parse_release(payload, "macos"))
    assert "缺少" in info["reason"]


class StreamResponse:
    def __init__(self, chunks: list[bytes], content_length: int | None = None):
        self.chunks = chunks
        self.headers = {} if content_length is None else {"content-length": str(content_length)}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def raise_for_status(self):
        return None

    async def aiter_bytes(self, _):
        for chunk in self.chunks:
            yield chunk


class StreamClient:
    def __init__(self, response: StreamResponse):
        self.response = response

    def stream(self, *_):
        return self.response


async def test_download_tracks_progress_and_rejects_oversized_content(tmp_path):
    manager = UpdateManager()
    target = tmp_path / "package.zip"
    await manager._download(StreamClient(StreamResponse([b"ab", b"cd"], 4)), "https://example.test/file", target)
    assert target.read_bytes() == b"abcd"
    assert manager.status()["progress"] == 85

    with pytest.raises(UpdateError, match="体积异常"):
        await manager._download(StreamClient(StreamResponse([], MAX_DOWNLOAD_BYTES + 1)), "https://example.test/large", target)


def make_release(version: str = "0.5.0", *, complete: bool = True) -> Release:
    base = f"https://github.com/loveramarois-byte/council-lab/releases/download/v{version}"
    return Release(
        version=version,
        tag=f"v{version}",
        page_url=f"{base}",
        notes="Update test",
        published_at="2026-07-28T00:00:00Z",
        package_name=f"Council-v{version}-macOS.zip" if complete else None,
        package_url=f"{base}/package.zip" if complete else None,
        checksum_url=f"{base}/SHA256SUMS.txt" if complete else None,
    )


class FakeUpdateClient:
    def __init__(self, *_, **__):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, *_):
        checksums = f"{'a' * 64}  Council-v0.5.0-macOS.zip\n{'a' * 64}  Council-v0.5.0-Windows.zip\n"
        return SimpleNamespace(content=checksums.encode(), text=checksums, raise_for_status=lambda: None)


class OversizedChecksumClient(FakeUpdateClient):
    async def get(self, *_):
        content = b"x" * (MAX_CHECKSUM_BYTES + 1)
        return SimpleNamespace(content=content, text=content.decode(), raise_for_status=lambda: None)


@pytest.mark.parametrize("platform", ["macos", "windows"])
async def test_update_manager_stages_verified_package_and_spawns_platform_helper(tmp_path, monkeypatch, platform):
    installed = tmp_path / ("Council.app" if platform == "macos" else "Council")
    stopper = installed / ("Contents/Resources/launcher/stop-council.sh" if platform == "macos" else "runtime/stop-council.ps1")
    stopper.parent.mkdir(parents=True)
    stopper.write_text("stop", encoding="utf-8")
    stopper.chmod(0o755)
    release = make_release()
    if platform == "windows":
        release = Release(**{**release.__dict__, "package_name": "Council-v0.5.0-Windows.zip"})

    async def fake_release(*_, **__):
        return release

    async def fake_download(_, __, target: Path):
        target.write_bytes(b"verified")

    def fake_extract(_, destination: Path):
        if platform == "macos":
            helper = destination / "Council-v0.5.0-macOS/Council.app/Contents/Resources/launcher/update-council.sh"
        else:
            helper = destination / "Council-v0.5.0-Windows/runtime/update-council.ps1"
        helper.parent.mkdir(parents=True)
        helper.write_text("helper", encoding="utf-8")
        helper.chmod(0o755)

    spawned: list[list[str]] = []
    monkeypatch.setenv("COUNCIL_VERSION", "0.4.0")
    monkeypatch.setattr("app.updater.data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr("app.updater.installation_info", lambda: Installation(platform, installed, True, True, "ok"))
    monkeypatch.setattr("app.updater.fetch_release", fake_release)
    monkeypatch.setattr("app.updater.httpx.AsyncClient", FakeUpdateClient)
    monkeypatch.setattr("app.updater.safe_extract_zip", fake_extract)
    monkeypatch.setattr("app.updater.sha256_file", lambda _: "a" * 64)
    monkeypatch.setattr("app.updater.subprocess.Popen", lambda command, **_: spawned.append(command))
    monkeypatch.setattr("app.updater.subprocess.CREATE_NEW_PROCESS_GROUP", 1, raising=False)
    monkeypatch.setattr("app.updater.subprocess.DETACHED_PROCESS", 2, raising=False)

    manager = UpdateManager()
    monkeypatch.setattr(manager, "_download", fake_download)
    await manager._run()

    assert manager.status()["phase"] == "restarting"
    assert manager.status()["progress"] == 100
    assert len(spawned) == 1
    assert "update-council" in " ".join(spawned[0])
    assert str(installed) in spawned[0]


@pytest.mark.parametrize(
    ("release", "installation", "expected"),
    [
        (make_release("0.4.0"), Installation("macos", Path("/tmp/Council.app"), True, True, "ok"), "最新版"),
        (make_release(), Installation("macos", Path("/tmp/Council.app"), True, False, "manual only"), "manual only"),
        (make_release(complete=False), Installation("macos", Path("/tmp/Council.app"), True, True, "ok"), "缺少"),
    ],
)
async def test_update_manager_reports_preflight_failures(tmp_path, monkeypatch, release, installation, expected):
    async def fake_release(*_, **__):
        return release

    monkeypatch.setenv("COUNCIL_VERSION", "0.4.0")
    monkeypatch.setattr("app.updater.data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr("app.updater.installation_info", lambda: installation)
    monkeypatch.setattr("app.updater.fetch_release", fake_release)
    manager = UpdateManager()
    await manager._run()
    assert manager.status()["phase"] == "error"
    assert expected in manager.status()["message"]


async def test_update_manager_rejects_checksum_mismatch_before_extraction(tmp_path, monkeypatch):
    installed = tmp_path / "Council.app"
    installed.mkdir()

    async def fake_release(*_, **__):
        return make_release()

    async def fake_download(_, __, target: Path):
        target.write_bytes(b"tampered")

    monkeypatch.setenv("COUNCIL_VERSION", "0.4.0")
    monkeypatch.setattr("app.updater.data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr("app.updater.installation_info", lambda: Installation("macos", installed, True, True, "ok"))
    monkeypatch.setattr("app.updater.fetch_release", fake_release)
    monkeypatch.setattr("app.updater.httpx.AsyncClient", FakeUpdateClient)
    monkeypatch.setattr("app.updater.sha256_file", lambda _: "b" * 64)
    monkeypatch.setattr("app.updater.safe_extract_zip", lambda *_: pytest.fail("tampered package must not be extracted"))
    manager = UpdateManager()
    monkeypatch.setattr(manager, "_download", fake_download)
    await manager._run()
    assert manager.status()["phase"] == "error"
    assert "SHA256 校验失败" in manager.status()["message"]


async def test_update_manager_rejects_oversized_checksum_file(tmp_path, monkeypatch):
    async def fake_release(*_, **__):
        return make_release()

    monkeypatch.setenv("COUNCIL_VERSION", "0.4.0")
    monkeypatch.setattr("app.updater.data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr("app.updater.installation_info", lambda: Installation("macos", tmp_path / "Council.app", True, True, "ok"))
    monkeypatch.setattr("app.updater.fetch_release", fake_release)
    monkeypatch.setattr("app.updater.httpx.AsyncClient", OversizedChecksumClient)
    manager = UpdateManager()
    await manager._run()
    assert manager.status()["phase"] == "error"
    assert "校验文件体积异常" in manager.status()["message"]


async def test_update_start_reuses_active_task_and_clears_previous_result(tmp_path, monkeypatch):
    result = tmp_path / "updates/last-result.json"
    result.parent.mkdir(parents=True)
    result.write_text("old result", encoding="utf-8")
    release_task = asyncio.Event()

    async def blocked_run():
        await release_task.wait()

    monkeypatch.setattr("app.updater.data_dir", lambda: tmp_path)
    manager = UpdateManager()
    monkeypatch.setattr(manager, "_run", blocked_run)
    await manager.start()
    first_task = manager._task
    await manager.start()
    assert manager._task is first_task
    assert not result.exists()
    release_task.set()
    await first_task


def test_update_status_surfaces_persisted_error_and_ignores_corrupt_result(tmp_path, monkeypatch):
    update_dir = tmp_path / "updates"
    update_dir.mkdir()
    result = update_dir / "last-result.json"
    result.write_text(json.dumps({"status": "error", "message": "rollback restored"}), encoding="utf-8")
    monkeypatch.setattr("app.updater.data_dir", lambda: tmp_path)
    manager = UpdateManager()
    assert manager.status()["phase"] == "error"
    assert manager.status()["error"] == "rollback restored"

    manager._state.update(phase="restarting", progress=100, message="restarting")
    assert manager.status()["phase"] == "error"
    assert manager.status()["error"] == "rollback restored"

    result.write_text("not json", encoding="utf-8")
    assert UpdateManager().status()["phase"] == "idle"
