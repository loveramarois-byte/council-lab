from __future__ import annotations

import sqlite3

import pytest

from app.migrations import SCHEMA_MIGRATIONS, SCHEMA_VERSION
from app.store import Store


def create_unversioned_database(path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES('legacy-run','{}','2026-07-29T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()


def test_existing_database_is_backed_up_and_migrated_once(tmp_path):
    database = tmp_path / "council.sqlite3"
    create_unversioned_database(database)

    store = Store(database)
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert store.conn.execute("SELECT id FROM runs").fetchone()[0] == "legacy-run"
    store.close()

    backups = list((tmp_path / "backups").glob("council-schema-v0-to-v*.sqlite3"))
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0])
    try:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
        assert backup.execute("SELECT id FROM runs").fetchone()[0] == "legacy-run"
    finally:
        backup.close()

    reopened = Store(database)
    reopened.close()
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_failed_migration_restores_original_database(tmp_path, monkeypatch):
    database = tmp_path / "council.sqlite3"
    connection = sqlite3.connect(database)
    for version in (1, 2):
        for statement in SCHEMA_MIGRATIONS[version]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={version}")
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES('protected-run','{}','2026-07-29T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()
    monkeypatch.setitem(SCHEMA_MIGRATIONS, 3, ("THIS IS NOT SQL",))

    with pytest.raises(sqlite3.OperationalError):
        Store(database)

    restored = sqlite3.connect(database)
    try:
        assert restored.execute("PRAGMA user_version").fetchone()[0] == 2
        assert restored.execute("SELECT id FROM runs").fetchone()[0] == "protected-run"
    finally:
        restored.close()


async def test_idempotent_operation_survives_process_restart(tmp_path):
    database = tmp_path / "council.sqlite3"
    store = Store(database)

    first = await store.claim_idempotent_operation("run-1:summarize", "request-key-123", "hash-a")
    assert first.state == "claimed"
    duplicate = await store.claim_idempotent_operation("run-1:summarize", "request-key-123", "hash-a")
    assert duplicate.state == "in_progress"
    await store.complete_idempotent_operation("run-1:summarize", "request-key-123", '{"id":"run-1"}')
    store.close()

    reopened = Store(database)
    cached = await reopened.claim_idempotent_operation("run-1:summarize", "request-key-123", "hash-a")
    conflict = await reopened.claim_idempotent_operation("run-1:summarize", "request-key-123", "hash-b")
    assert cached.state == "cached"
    assert cached.response_json == '{"id":"run-1"}'
    assert conflict.state == "conflict"
    reopened.close()
