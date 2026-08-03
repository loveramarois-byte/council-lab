#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_ROOT = "https://gitee.com/api/v5"
DEFAULT_API_TIMEOUT_SECONDS = 60
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 3600


class GiteeApiError(RuntimeError):
    pass


def _timeout_seconds(file_path: Path | None) -> int:
    variable = "GITEE_UPLOAD_TIMEOUT_SECONDS" if file_path else "GITEE_API_TIMEOUT_SECONDS"
    default = DEFAULT_UPLOAD_TIMEOUT_SECONDS if file_path else DEFAULT_API_TIMEOUT_SECONDS
    raw_value = os.environ.get(variable, str(default)).strip()
    try:
        timeout = int(raw_value)
    except ValueError as error:
        raise GiteeApiError(f"{variable} must be an integer") from error
    if timeout < 1 or timeout > 7200:
        raise GiteeApiError(f"{variable} must be between 1 and 7200 seconds")
    return timeout


def _curl_config_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise GiteeApiError("Gitee access token contains an invalid newline")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def upload_asset(path: str, token: str, file_path: Path) -> Any:
    """Upload through libcurl so the timeout is a real end-to-end budget."""
    url = f"{API_ROOT}{path}"
    timeout = _timeout_seconds(file_path)
    config = f'form = "access_token={_curl_config_value(token)}"\n'
    with tempfile.NamedTemporaryFile() as response_file:
        result = subprocess.run(
            [
                "curl",
                "--fail-with-body",
                "--show-error",
                "--connect-timeout",
                "30",
                "--max-time",
                str(timeout),
                "--request",
                "POST",
                "--form",
                f"file=@{file_path};type=application/octet-stream",
                "--output",
                response_file.name,
                "--config",
                "-",
                url,
            ],
            input=config,
            text=True,
            check=False,
        )
        response_file.seek(0)
        payload = response_file.read()
    if result.returncode != 0:
        body = payload.decode("utf-8", errors="replace").replace(token, "***").strip()
        raise GiteeApiError(
            f"Gitee asset upload failed with curl exit {result.returncode}: {body[:500]}"
        )
    try:
        return json.loads(payload) if payload else None
    except json.JSONDecodeError as error:
        raise GiteeApiError("Gitee asset upload returned invalid JSON") from error


def _response_error(error: urllib.error.HTTPError) -> GiteeApiError:
    body = error.read().decode("utf-8", errors="replace")
    try:
        message = json.loads(body).get("message") or body
    except json.JSONDecodeError:
        message = body
    return GiteeApiError(f"Gitee API returned HTTP {error.code}: {message[:500]}")


def api_request(
    method: str,
    path: str,
    token: str,
    *,
    fields: dict[str, str] | None = None,
    file_path: Path | None = None,
) -> Any:
    token_query = urllib.parse.urlencode({"access_token": token})
    url = f"{API_ROOT}{path}?{token_query}"
    headers = {"Accept": "application/json", "User-Agent": "Council-Lab-Release"}
    if file_path is None:
        data = urllib.parse.urlencode(fields or {}).encode() if method != "GET" else None
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        return upload_asset(path, token, file_path)
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds(file_path)) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise _response_error(error) from error
    except urllib.error.URLError as error:
        raise GiteeApiError(f"Gitee API request failed: {error.reason}") from error
    return json.loads(payload) if payload else None


def get_release(owner: str, repo: str, tag: str, token: str) -> dict[str, Any] | None:
    encoded_tag = urllib.parse.quote(tag, safe="")
    try:
        return api_request("GET", f"/repos/{owner}/{repo}/releases/tags/{encoded_tag}", token)
    except GiteeApiError as error:
        if "HTTP 404" in str(error):
            return None
        raise


def publish_release(
    owner: str,
    repo: str,
    tag: str,
    title: str,
    notes: str,
    assets: list[Path],
    token: str,
) -> dict[str, Any]:
    release = get_release(owner, repo, tag, token)
    fields = {
        "tag_name": tag,
        "name": title,
        "body": notes,
        "prerelease": "false",
        "target_commitish": "main",
    }
    if release:
        release = api_request("PATCH", f"/repos/{owner}/{repo}/releases/{release['id']}", token, fields=fields)
    else:
        release = api_request("POST", f"/repos/{owner}/{repo}/releases", token, fields=fields)

    attachments = api_request(
        "GET",
        f"/repos/{owner}/{repo}/releases/{release['id']}/attach_files",
        token,
    )
    existing_assets = {item["name"]: item for item in attachments or []}
    for asset in assets:
        if asset.name in existing_assets:
            api_request(
                "DELETE",
                f"/repos/{owner}/{repo}/releases/{release['id']}/attach_files/{existing_assets[asset.name]['id']}",
                token,
            )
        api_request(
            "POST",
            f"/repos/{owner}/{repo}/releases/{release['id']}/attach_files",
            token,
            file_path=asset,
        )
    return get_release(owner, repo, tag, token) or release


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update a Gitee Release and mirror its assets.")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--asset", type=Path, action="append", default=[])
    parser.add_argument("--token-env", default="GITEE_ACCESS_TOKEN")
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"Missing required secret environment variable: {args.token_env}")
    assets = [path.resolve() for path in args.asset]
    missing = [str(path) for path in assets if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing release assets: {', '.join(missing)}")
    notes = args.notes.read_text(encoding="utf-8").strip()
    if not notes:
        raise SystemExit("Release notes must not be empty")

    release = publish_release(args.owner, args.repo, args.tag, args.title, notes, assets, token)
    print(release.get("html_url") or f"https://gitee.com/{args.owner}/{args.repo}/releases/tag/{args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
