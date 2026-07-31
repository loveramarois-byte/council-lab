from __future__ import annotations

import json
import sqlite3


SCHEMA_VERSION = 6

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
    5: (
        "CREATE TABLE IF NOT EXISTS high_risk_runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL, version INTEGER NOT NULL, assessment_json TEXT NOT NULL, facts_json TEXT NOT NULL, decision_json TEXT, action_type TEXT, action_payload_hash TEXT, report_hash TEXT, requested_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_high_risk_runs_status_updated ON high_risk_runs(status, updated_at)",
        "CREATE TABLE IF NOT EXISTS high_risk_approvals (approval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, action_type TEXT NOT NULL, action_payload_hash TEXT NOT NULL, report_hash TEXT NOT NULL, requested_at TEXT NOT NULL, requested_by TEXT NOT NULL, status TEXT NOT NULL, decided_at TEXT, decided_by TEXT, decision_reason TEXT, expires_at TEXT NOT NULL, consumed_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_high_risk_approvals_run_status ON high_risk_approvals(run_id, status, expires_at)",
        "CREATE TABLE IF NOT EXISTS high_risk_audit_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL, event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, actor_type TEXT NOT NULL, actor_id TEXT, previous_status TEXT, new_status TEXT, policy_version TEXT, model_provider TEXT, model_name TEXT, prompt_template_version TEXT, request_hash TEXT, response_hash TEXT, metadata_json TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_high_risk_audit_run_sequence ON high_risk_audit_events(run_id, sequence)",
        "CREATE TRIGGER IF NOT EXISTS high_risk_audit_no_update BEFORE UPDATE ON high_risk_audit_events BEGIN SELECT RAISE(ABORT, 'high-risk audit events are append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS high_risk_audit_no_delete BEFORE DELETE ON high_risk_audit_events BEGIN SELECT RAISE(ABORT, 'high-risk audit events are append-only'); END",
    ),
    6: (
        "CREATE TABLE IF NOT EXISTS decision_briefs (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, version INTEGER NOT NULL, schema_version INTEGER NOT NULL, payload_json TEXT NOT NULL, generation_reason TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(id), UNIQUE(run_id, version))",
        "CREATE INDEX IF NOT EXISTS idx_decision_briefs_run_version ON decision_briefs(run_id, version DESC)",
        "CREATE TRIGGER IF NOT EXISTS decision_briefs_no_update BEFORE UPDATE ON decision_briefs BEGIN SELECT RAISE(ABORT, 'decision briefs are append-only'); END",
    ),
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
