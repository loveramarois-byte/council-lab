import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from scripts import publish_gitee_release


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_publish_release_creates_release_and_uploads_all_assets(monkeypatch, tmp_path):
    assets = [tmp_path / name for name in ("mac.zip", "windows.zip", "SHA256SUMS.txt")]
    for asset in assets:
        asset.write_bytes(asset.name.encode())
    requests = []
    responses = iter([
        urllib.error.HTTPError("url", 404, "not found", {}, io.BytesIO(b'{"message":"Not Found"}')),
        FakeResponse({"id": 7, "assets": []}),
        FakeResponse([]),
        FakeResponse({"id": 7, "tag_name": "v1.0.0", "assets": []}),
    ])
    uploads = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(publish_gitee_release.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        publish_gitee_release,
        "upload_asset",
        lambda path, token, file_path: uploads.append((path, token, file_path)) or {"id": len(uploads)},
    )
    release = publish_gitee_release.publish_release(
        "owner", "repo", "v1.0.0", "Council v1.0.0", "notes", assets, "secret-token"
    )

    assert release["tag_name"] == "v1.0.0"
    assert [request.get_method() for request, _ in requests] == ["GET", "POST", "GET", "GET"]
    assert [item[2] for item in uploads] == assets
    assert all("access_token=secret-token" in request.full_url for request, _ in requests)
    assert all(not isinstance(request.data, bytes) or b"secret-token" not in request.data for request, _ in requests)


def test_http_errors_do_not_expose_token(monkeypatch):
    error = urllib.error.HTTPError(
        "https://gitee.com/api/v5/user?access_token=secret-token",
        401,
        "unauthorized",
        {},
        io.BytesIO(b'{"message":"Unauthorized"}'),
    )
    monkeypatch.setattr(publish_gitee_release.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(publish_gitee_release.GiteeApiError) as raised:
        publish_gitee_release.api_request("GET", "/user", "secret-token")
    assert "secret-token" not in str(raised.value)


def test_asset_upload_uses_curl_with_total_timeout_without_token_in_arguments(monkeypatch, tmp_path):
    asset = tmp_path / "Council.zip"
    asset.write_bytes(b"release")
    observed = {}

    def fake_run(arguments, **kwargs):
        observed["arguments"] = arguments
        observed["input"] = kwargs["input"]
        output_path = arguments[arguments.index("--output") + 1]
        Path(output_path).write_text('{"id": 101}', encoding="utf-8")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(publish_gitee_release.subprocess, "run", fake_run)
    result = publish_gitee_release.api_request("POST", "/release/attach_files", "secret-token", file_path=asset)

    assert result == {"id": 101}
    assert observed["arguments"][0] == "curl"
    assert observed["arguments"][observed["arguments"].index("--max-time") + 1] == "3600"
    assert f"file=@{asset};type=application/octet-stream" in observed["arguments"]
    assert all("secret-token" not in argument for argument in observed["arguments"])
    assert "secret-token" in observed["input"]


def test_asset_upload_failure_does_not_expose_token(monkeypatch, tmp_path):
    asset = tmp_path / "Council.zip"
    asset.write_bytes(b"release")

    def fake_run(arguments, **_kwargs):
        return subprocess.CompletedProcess(arguments, 28)

    monkeypatch.setattr(publish_gitee_release.subprocess, "run", fake_run)
    with pytest.raises(publish_gitee_release.GiteeApiError) as raised:
        publish_gitee_release.upload_asset("/release/attach_files", "secret-token", asset)
    assert "secret-token" not in str(raised.value)


@pytest.mark.parametrize(
    ("environment", "file_name", "expected"),
    [
        ({"GITEE_API_TIMEOUT_SECONDS": "75"}, None, 75),
        ({"GITEE_UPLOAD_TIMEOUT_SECONDS": "2400"}, "Council.zip", 2400),
    ],
)
def test_timeouts_can_be_configured(monkeypatch, tmp_path, environment, file_name, expected):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    file_path = tmp_path / file_name if file_name else None
    assert publish_gitee_release._timeout_seconds(file_path) == expected


@pytest.mark.parametrize("value", ["zero", "0", "7201"])
def test_invalid_upload_timeout_is_rejected(monkeypatch, tmp_path, value):
    monkeypatch.setenv("GITEE_UPLOAD_TIMEOUT_SECONDS", value)
    with pytest.raises(publish_gitee_release.GiteeApiError, match="GITEE_UPLOAD_TIMEOUT_SECONDS"):
        publish_gitee_release._timeout_seconds(tmp_path / "Council.zip")


def test_publish_release_replaces_existing_asset(monkeypatch, tmp_path):
    asset = tmp_path / "mac.zip"
    asset.write_bytes(b"replacement")
    calls = []

    def fake_request(method, path, token, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            if path.endswith("/attach_files"):
                return [{"id": 22, "name": "mac.zip"}]
            return {"id": 9, "assets": [{"id": 22, "name": "mac.zip"}]}
        if method == "PATCH":
            return {"id": 9, "assets": [{"id": 22, "name": "mac.zip"}]}
        return {"id": 9}

    monkeypatch.setattr(publish_gitee_release, "api_request", fake_request)
    publish_gitee_release.publish_release("owner", "repo", "v1", "title", "notes", [asset], "token")
    assert ("DELETE", "/repos/owner/repo/releases/9/attach_files/22", {}) in calls
    assert any(method == "POST" and kwargs.get("file_path") == asset for method, _, kwargs in calls)


def test_main_rejects_missing_secret(monkeypatch, tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")
    monkeypatch.delenv("GITEE_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        ["publish_gitee_release.py", "--owner", "o", "--repo", "r", "--tag", "v1", "--title", "t", "--notes", str(notes)],
    )
    with pytest.raises(SystemExit, match="Missing required secret"):
        publish_gitee_release.main()
