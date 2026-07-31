import io
import json
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
        FakeResponse({"id": 101}),
        FakeResponse({"id": 102}),
        FakeResponse({"id": 103}),
        FakeResponse({"id": 7, "tag_name": "v1.0.0", "assets": []}),
    ])

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(publish_gitee_release.urllib.request, "urlopen", fake_urlopen)
    release = publish_gitee_release.publish_release(
        "owner", "repo", "v1.0.0", "Council v1.0.0", "notes", assets, "secret-token"
    )

    assert release["tag_name"] == "v1.0.0"
    assert [request.get_method() for request, _ in requests] == ["GET", "POST", "GET", "POST", "POST", "POST", "GET"]
    assert all("access_token=secret-token" in request.full_url for request, _ in requests)
    assert all(b"secret-token" not in (request.data or b"") for request, _ in requests)


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
