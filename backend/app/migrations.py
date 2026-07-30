from __future__ import annotations

import json
import sqlite3


SCHEMA_VERSION = 4

SCHEMA_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS provider_profiles (id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS project_sources (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_project_sources_project ON project_sources(project_id, created_at)",
    ),
    2: (
        "CREATE TABLE IF NOT EXISTS run_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence ON run_events(run_id, sequence)",
    ),
    3: (
        "CREATE TABLE IF NOT EXISTS idempotent_operations (scope TEXT NOT NULL, operation_key TEXT NOT NULL, request_hash TEXT NOT NULL, status TEXT NOT NULL, response_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(scope, operation_key))",
        "CREATE INDEX IF NOT EXISTS idx_idempotent_operations_updated ON idempotent_operations(updated_at)",
    ),
    4: (),
}


def _mark_candidate_structure_provenance(connection: sqlite3.Connection) -> None:
    rows = connection.execute("SELECT id, payload FROM runs").fetchall()
    for run_id, raw_payload in rows:
        payload = json.loads(raw_payload)
        candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
        changed = False
        for candidate in candidates:
            if isinstance(candidate, dict) and "structure_source" not in candidate:
                candidate["structure_source"] = "legacy_default"
                changed = True
        if changed:
            connection.execute(
                "UPDATE runs SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), run_id),
            )


DATA_MIGRATIONS = {4: _mark_candidate_structure_provenance}


def schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def apply_migrations(connection: sqlite3.Connection) -> tuple[int, int]:
    current = schema_version(connection)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"数据库 schema v{current} 高于当前程序支持的 v{SCHEMA_VERSION}，请使用更新版本的 Council。"
        )
    if current == SCHEMA_VERSION:
        return current, current

    connection.execute("BEGIN IMMEDIATE")
    try:
        for target in range(current + 1, SCHEMA_VERSION + 1):
            statements = SCHEMA_MIGRATIONS.get(target)
            if statements is None:
                raise RuntimeError(f"缺少数据库迁移 v{target}")
            for statement in statements:
                connection.execute(statement)
            data_migration = DATA_MIGRATIONS.get(target)
            if data_migration:
                data_migration(connection)
            connection.execute(f"PRAGMA user_version={target}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return current, SCHEMA_VERSION
