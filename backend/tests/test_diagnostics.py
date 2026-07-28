import io
import json
import zipfile

from app.diagnostics import build_diagnostic_bundle
from app.models import AgentAssignmentsConfig, AgentModelAssignment, RunRecord, utc_now
from app.provider_catalog import builtin_providers
from app.store import Store


def assignment(role: str) -> AgentModelAssignment:
    return AgentModelAssignment(role=role, provider_id="mock", model="council-mock")


async def test_diagnostic_bundle_is_useful_and_excludes_sensitive_content(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("COUNCIL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("COUNCIL_LOG_DIR", str(log_dir))
    log_dir.mkdir()
    (log_dir / "backend.log").write_text("api_key=secret-key user question secret-question", encoding="utf-8")
    (log_dir / "secret-hostname.log").write_text("should-not-be-enumerated", encoding="utf-8")
    (log_dir / "mobile-access.token").write_text("secret-mobile-token", encoding="utf-8")

    store = Store(data_dir / "council.sqlite3")
    now = utc_now()
    await store.save_run(
        RunRecord(
            id="private-run",
            question="secret-question",
            mode="standard",
            provider_id="mock",
            model="private-model-name",
            status="completed",
            created_at=now,
            updated_at=now,
        )
    )
    assignments = AgentAssignmentsConfig(
        seats=[assignment("analyst"), assignment("challenger"), assignment("builder"), assignment("observer")],
        finalizer=assignment("finalizer"),
    )

    providers = builtin_providers()
    providers["secret-provider-id"] = providers["openai"].model_copy(
        update={"id": "secret-provider-id", "display_name": "secret-provider-display-name"}
    )
    bundle = await build_diagnostic_bundle(store, providers, assignments)
    store.close()

    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == {"README.txt", "diagnostics.json"}
        report = json.loads(archive.read("diagnostics.json"))
        all_content = b"\n".join(archive.read(name) for name in archive.namelist()).decode("utf-8")

    assert report["schema_version"] == 1
    assert report["storage"]["integrity"] == "ok"
    assert report["storage"]["counts"]["runs"] == 1
    assert report["logs"] == [
        {
            "content_included": False,
            "modified_at": report["logs"][0]["modified_at"],
            "name": "backend.log",
            "size_bytes": len("api_key=secret-key user question secret-question"),
        }
    ]
    assert report["privacy"] == {
        "conversation_content_included": False,
        "log_content_included": False,
        "credentials_included": False,
        "cookies_or_pairing_tokens_included": False,
        "filesystem_paths_included": False,
    }
    for secret in (
        "secret-key",
        "secret-question",
        "secret-mobile-token",
        "private-model-name",
        "secret-provider-id",
        "secret-provider-display-name",
        "secret-hostname",
        "should-not-be-enumerated",
        str(tmp_path),
    ):
        assert secret not in all_content
