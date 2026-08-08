from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .paths import data_dir


REPOSITORY = "loveramarois-byte/council-lab"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 100_000
MAX_CHECKSUM_BYTES = 256 * 1024
RELEASE_CACHE_SECONDS = 15 * 60
INSTALL_REQUEST_HEADER = "app"
_release_cache: Release | None = None
_release_cache_at = 0.0
_release_lock = asyncio.Lock()


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Installation:
    platform: str
    root: Path | None
    packaged: bool
    can_auto_update: bool
    reason: str


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    page_url: str
    notes: str
    published_at: str | None
    package_name: str | None
    package_url: str | None
    checksum_url: str | None


def current_version() -> str:
    configured = os.getenv("COUNCIL_VERSION", "").strip()
    if configured:
        return configured.removeprefix("v")

    candidates = [Path(__file__).resolve().parents[2] / "VERSION"]
    executable = Path(sys.executable).resolve()
    candidates.extend(parent / "VERSION" for parent in executable.parents[:4])
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip().removeprefix("v")
    return "0.0.0"


def runtime_identity() -> str:
    return os.getenv("COUNCIL_RUNTIME_ID", "development").strip() or "development"


def is_app_store_distribution() -> bool:
    return os.getenv("COUNCIL_DISTRIBUTION", "").strip().lower() == "app_store"


def version_key(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise UpdateError(f"无法识别版本号：{value}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_newer(candidate: str, installed: str) -> bool:
    return version_key(candidate) > version_key(installed)


def install_request_is_allowed(value: str | None) -> bool:
    """Require a non-simple browser request before restarting the local app."""
    return value == INSTALL_REQUEST_HEADER


def installation_info() -> Installation:
    platform_override = os.getenv("COUNCIL_UPDATE_PLATFORM", "").strip().lower()
    platform = platform_override or ("macos" if sys.platform == "darwin" else "windows" if os.name == "nt" else "unsupported")
    root_value = os.getenv("COUNCIL_INSTALL_ROOT", "").strip()
    packaged = os.getenv("COUNCIL_PACKAGED", "") == "1" or bool(getattr(sys, "frozen", False))
    root = Path(root_value).expanduser().resolve() if root_value else None

    if is_app_store_distribution():
        return Installation("app_store", root, packaged, False, "更新由 Mac App Store 安全提供。")
    if platform not in {"macos", "windows"}:
        return Installation(platform, root, packaged, False, "当前系统暂不支持应用内安装。")
    if not packaged or root is None:
        return Installation(platform, root, packaged, False, "源码运行模式只检查版本，不自动覆盖项目文件。")
    if platform == "macos" and (root.name != "Council.app" or not (root / "Contents" / "Resources").is_dir()):
        return Installation(platform, root, packaged, False, "没有识别到完整的 Council.app。")
    if platform == "windows" and not (root / "runtime" / "start-council.ps1").is_file():
        return Installation(platform, root, packaged, False, "没有识别到完整的 Windows 安装目录。")
    if data_dir().resolve().is_relative_to(root):
        return Installation(platform, root, packaged, False, "数据目录位于应用目录内部；为避免覆盖数据，请手动安装新版到独立目录。")
    return Installation(
        platform,
        root,
        packaged,
        True,
        "可以在软件内安全下载、校验并重启更新。",
    )


def expected_package_name(version: str, platform: str) -> str | None:
    suffix = {"macos": "macOS", "windows": "Windows"}.get(platform)
    return f"Council-v{version}-{suffix}.zip" if suffix else None


def _trusted_asset_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.path.startswith(f"/{REPOSITORY}/releases/download/")


def parse_release(payload: dict[str, Any], platform: str) -> Release:
    tag = str(payload.get("tag_name") or "").strip()
    version = tag.removeprefix("v")
    version_key(version)
    package_name = expected_package_name(version, platform)
    assets = {str(item.get("name")): str(item.get("browser_download_url")) for item in payload.get("assets", []) if isinstance(item, dict)}
    package_url = assets.get(package_name or "")
    checksum_url = assets.get("SHA256SUMS.txt")
    if package_url and not _trusted_asset_url(package_url):
        package_url = None
    if checksum_url and not _trusted_asset_url(checksum_url):
        checksum_url = None
    return Release(
        version=version,
        tag=tag,
        page_url=str(payload.get("html_url") or RELEASE_PAGE),
        notes=str(payload.get("body") or ""),
        published_at=payload.get("published_at"),
        package_name=package_name,
        package_url=package_url,
        checksum_url=checksum_url,
    )


async def fetch_release(client: httpx.AsyncClient | None = None, *, refresh: bool = False) -> Release:
    global _release_cache, _release_cache_at
    installation = installation_info()
    if client is None and not refresh and _release_cache and time.monotonic() - _release_cache_at < RELEASE_CACHE_SECONDS:
        return _release_cache
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(follow_redirects=True, timeout=20, headers={"Accept": "application/vnd.github+json", "User-Agent": f"Council/{current_version()}"})
    try:
        response = await client.get(RELEASE_API)
        response.raise_for_status()
        release = parse_release(response.json(), installation.platform)
        if owns_client:
            async with _release_lock:
                _release_cache = release
                _release_cache_at = time.monotonic()
        return release
    except (httpx.HTTPError, ValueError, json.JSONDecodeError, UpdateError) as exc:
        raise UpdateError(f"无法读取 GitHub 最新版本：{exc}") from exc
    finally:
        if owns_client:
            await client.aclose()


def public_update_info(release: Release) -> dict[str, Any]:
    installed = current_version()
    installation = installation_info()
    available = is_newer(release.version, installed)
    package_ready = bool(release.package_url and release.checksum_url)
    return {
        "current_version": installed,
        "latest_version": release.version,
        "update_available": available,
        "current_is_newer": is_newer(installed, release.version),
        "can_auto_update": installation.can_auto_update and package_ready,
        "installation_kind": installation.platform if installation.packaged else "development",
        "reason": installation.reason if package_ready else "该版本缺少当前系统安装包或校验文件。",
        "release_url": release.page_url,
        "published_at": release.published_at,
        "notes": release.notes[:4000],
        "package_name": release.package_name,
    }


def app_store_update_info() -> dict[str, Any]:
    installed = current_version()
    return {
        "current_version": installed,
        "latest_version": installed,
        "update_available": False,
        "current_is_newer": False,
        "can_auto_update": False,
        "installation_kind": "app_store",
        "reason": "更新由 Mac App Store 安全提供。",
        "release_url": "",
        "published_at": None,
        "notes": "",
        "package_name": None,
    }


def unavailable_update_info(error: str) -> dict[str, Any]:
    installed = current_version()
    installation = installation_info()
    return {
        "current_version": installed,
        "latest_version": installed,
        "update_available": False,
        "current_is_newer": False,
        "can_auto_update": False,
        "installation_kind": installation.platform if installation.packaged else "development",
        "reason": "暂时无法确认最新版本；当前版本仍可正常使用。",
        "release_url": RELEASE_PAGE,
        "published_at": None,
        "notes": "",
        "package_name": None,
        "check_error": error,
    }


def parse_checksum(text: str, filename: str) -> str:
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line.strip())
        if match and match.group(2) == filename:
            return match.group(1).lower()
    raise UpdateError(f"校验文件中没有 {filename}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    total_size = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_ENTRIES:
            raise UpdateError("更新包文件数量异常，已拒绝安装。")
        seen_paths: set[Path] = set()
        for member in members:
            member_path = (destination / member.filename).resolve()
            if not member_path.is_relative_to(destination):
                raise UpdateError("更新包包含越界路径，已拒绝安装。")
            if member_path in seen_paths:
                raise UpdateError("更新包包含重复路径，已拒绝安装。")
            seen_paths.add(member_path)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                link_target = archive.read(member).decode("utf-8")
                resolved_target = (member_path.parent / link_target).resolve()
                if Path(link_target).is_absolute() or not resolved_target.is_relative_to(destination):
                    raise UpdateError("更新包包含越界符号链接，已拒绝安装。")
            total_size += member.file_size
            if total_size > MAX_EXTRACTED_BYTES:
                raise UpdateError("更新包解压后体积异常，已拒绝安装。")

        for member in members:
            extracted = destination / member.filename
            mode = member.external_attr >> 16
            if member.is_dir():
                extracted.mkdir(parents=True, exist_ok=True)
                continue
            extracted.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(mode):
                os.symlink(archive.read(member).decode("utf-8"), extracted)
                continue
            with archive.open(member) as source, extracted.open("wb") as target:
                shutil.copyfileobj(source, target)
            permissions = mode & 0o777
            if permissions:
                extracted.chmod(permissions)


class UpdateManager:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._state: dict[str, Any] = {
            "phase": "idle",
            "progress": 0,
            "message": "尚未开始更新。",
            "target_version": None,
            "error": None,
        }

    def status(self) -> dict[str, Any]:
        state = self._state
        result_path = data_dir() / "updates" / "last-result.json"
        if state["phase"] in {"idle", "restarting"} and result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
                if result.get("status") == "error":
                    message = str(result.get("message") or "上次更新未完成。")
                    state = {**state, "phase": "error", "message": message, "error": message}
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return {"current_version": current_version(), **state}

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self._task and not self._task.done():
                return self.status()
            installation = installation_info()
            if not installation.can_auto_update:
                raise UpdateError(installation.reason)
            result_path = data_dir() / "updates" / "last-result.json"
            result_path.unlink(missing_ok=True)
            self._state = {"phase": "checking", "progress": 0, "message": "正在确认最新版。", "target_version": None, "error": None}
            self._task = asyncio.create_task(self._run())
            return self.status()

    async def _download(self, client: httpx.AsyncClient, url: str, target: Path) -> None:
        received = 0
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            if total > MAX_DOWNLOAD_BYTES:
                raise UpdateError("更新包体积异常，已停止下载。")
            with target.open("wb") as handle:
                async for chunk in response.aiter_bytes(1024 * 1024):
                    received += len(chunk)
                    if received > MAX_DOWNLOAD_BYTES:
                        raise UpdateError("更新包超过允许大小，已停止下载。")
                    handle.write(chunk)
                    if total:
                        self._state["progress"] = min(85, int(received * 85 / total))

    async def _run(self) -> None:
        try:
            installation = installation_info()
            if not installation.can_auto_update or installation.root is None:
                raise UpdateError(installation.reason)
            release = await fetch_release(refresh=True)
            self._state["target_version"] = release.version
            if not is_newer(release.version, current_version()):
                raise UpdateError("当前已经是最新版。")
            if not release.package_name or not release.package_url or not release.checksum_url:
                raise UpdateError("最新版缺少当前系统安装包或 SHA256 校验文件。")

            update_root = data_dir() / "updates"
            stage = update_root / f"v{release.version}-{installation.platform}"
            if stage.exists():
                await asyncio.to_thread(shutil.rmtree, stage)
            payload_dir = stage / "payload"
            payload_dir.mkdir(parents=True, exist_ok=True)
            package_path = stage / release.package_name

            self._state.update(phase="downloading", progress=0, message=f"正在下载 {release.package_name}。")
            timeout = httpx.Timeout(30, read=600, write=30, pool=30)
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers={"User-Agent": f"Council/{current_version()}"}) as client:
                checksum_response = await client.get(release.checksum_url)
                checksum_response.raise_for_status()
                if len(checksum_response.content) > MAX_CHECKSUM_BYTES:
                    raise UpdateError("SHA256 校验文件体积异常，已停止更新。")
                expected = parse_checksum(checksum_response.text, release.package_name)
                await self._download(client, release.package_url, package_path)

            self._state.update(phase="verifying", progress=88, message="正在校验下载包。")
            if await asyncio.to_thread(sha256_file, package_path) != expected:
                raise UpdateError("SHA256 校验失败，更新包已拒绝安装。")
            await asyncio.to_thread(safe_extract_zip, package_path, payload_dir)
            self._state.update(progress=96, message="校验通过，准备重启。")

            if installation.platform == "macos":
                app_candidates = list(payload_dir.glob("*/Council.app"))
                if len(app_candidates) != 1:
                    raise UpdateError("macOS 更新包结构不完整。")
                helper = app_candidates[0] / "Contents" / "Resources" / "launcher" / "update-council.sh"
                stopper = installation.root / "Contents" / "Resources" / "launcher" / "stop-council.sh"
                if not helper.is_file() or not stopper.is_file():
                    raise UpdateError("macOS 更新助手不完整。")
                command = ["/bin/zsh", str(helper), str(app_candidates[0]), str(installation.root), str(stopper)]
            else:
                root_candidates = [item for item in payload_dir.iterdir() if item.is_dir() and (item / "runtime" / "update-council.ps1").is_file()]
                if len(root_candidates) != 1:
                    raise UpdateError("Windows 更新包结构不完整。")
                helper = root_candidates[0] / "runtime" / "update-council.ps1"
                stopper = installation.root / "runtime" / "stop-council.ps1"
                if not stopper.is_file():
                    raise UpdateError("Windows 更新助手不完整。")
                command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper), "-NewRoot", str(root_candidates[0]), "-TargetRoot", str(installation.root), "-Stopper", str(stopper)]

            log_path = stage / "update.log"
            result_path = update_root / "last-result.json"
            command.extend(["-LogFile" if installation.platform == "windows" else str(log_path)])
            if installation.platform == "windows":
                command.extend([str(log_path), "-ResultFile", str(result_path)])
            else:
                command.append(str(result_path))
            self._state.update(phase="restarting", progress=100, message="更新已验证，Council 即将重启。")
            popen_options: dict[str, Any] = {
                "cwd": str(stage),
                "env": os.environ.copy(),
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if installation.platform == "windows":
                popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            else:
                popen_options["start_new_session"] = True
            subprocess.Popen(command, **popen_options)
        except Exception as exc:
            message = str(exc).strip() or "更新失败。"
            self._state.update(phase="error", message=message, error=message)


update_manager = UpdateManager()
