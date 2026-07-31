from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .decision_lifecycle import RunFork, RunForkLineage
from .migrations import SCHEMA_VERSION, apply_migrations, schema_version
from .models import AgentAssignmentsConfig, DecisionBrief, ProjectRecord, ProjectSource, ProviderProfile, RunEvent, RunRecord


@dataclass(frozen=True)
class IdempotencyClaim:
    state: str
    response_json: str | None = None


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        source_path = Path(self.path)
        self.checkpoint_path = str(source_path.with_name(f"{source_path.stem}.checkpoints{source_path.suffix}"))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._event_conditions: dict[str, asyncio.Condition] = {}
        self._event_stream_counts: dict[str, int] = {}
        self._event_stream_lock = asyncio.Lock()
        existed = source_path.exists() and source_path.stat().st_size > 0
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA busy_timeout=5000")
        backup_path = None
        try:
            current = schema_version(self.conn)
            backup_path = self._create_schema_backup(current) if existed and current < SCHEMA_VERSION else None
            apply_migrations(self.conn)
        except Exception:
            self.conn.close()
            if backup_path:
                self._restore_schema_backup(backup_path)
            raise
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def _create_schema_backup(self, current_version: int) -> Path:
        source_path = Path(self.path)
        backup_dir = source_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"{source_path.stem}-schema-v{current_version}-to-v{SCHEMA_VERSION}-{timestamp}.sqlite3"
        destination = sqlite3.connect(backup_path)
        try:
            self.conn.backup(destination)
            destination.commit()
        finally:
            destination.close()
        try:
            backup_path.chmod(0o600)
        except OSError:
            pass
        self._prune_schema_backups(backup_dir, source_path.stem)
        return backup_path

    @staticmethod
    def _prune_schema_backups(backup_dir: Path, stem: str, keep: int = 5) -> None:
        backups = sorted(
            backup_dir.glob(f"{stem}-schema-v*-to-v*-*.sqlite3"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for obsolete in backups[keep:]:
            obsolete.unlink(missing_ok=True)

    def _restore_schema_backup(self, backup_path: Path) -> None:
        target = Path(self.path)
        for suffix in ("-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)
        shutil.copy2(backup_path, target)

    async def save_project(self, project: ProjectRecord) -> None:
        async with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO projects(id,payload,created_at) VALUES(?,?,?)",
                (project.id, project.model_dump_json(), project.created_at.isoformat()),
            )
            self.conn.commit()

    async def get_project(self, project_id: str) -> ProjectRecord | None:
        row = self.conn.execute("SELECT payload FROM projects WHERE id=?", (project_id,)).fetchone()
        return ProjectRecord.model_validate_json(row[0]) if row else None

    async def list_projects(self) -> list[ProjectRecord]:
        rows = self.conn.execute("SELECT payload FROM projects ORDER BY created_at DESC").fetchall()
        projects = [ProjectRecord.model_validate_json(row[0]) for row in rows]
        runs = await self.list_runs()
        for project in projects:
            project.source_count = self.conn.execute(
                "SELECT COUNT(*) FROM project_sources WHERE project_id=?", (project.id,)
            ).fetchone()[0]
            project.run_count = sum(1 for run in runs if run.project_id == project.id)
        return projects

    async def delete_project(self, project_id: str) -> bool:
        async with self._lock:
            cursor = self.conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self.conn.execute("DELETE FROM project_sources WHERE project_id=?", (project_id,))
            self.conn.commit()
            return cursor.rowcount > 0

    async def save_source(self, source: ProjectSource) -> None:
        async with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO project_sources(id,project_id,payload,created_at) VALUES(?,?,?,?)",
                (source.id, source.project_id, source.model_dump_json(), source.created_at.isoformat()),
            )
            self.conn.commit()

    async def get_source(self, source_id: str) -> ProjectSource | None:
        row = self.conn.execute("SELECT payload FROM project_sources WHERE id=?", (source_id,)).fetchone()
        return ProjectSource.model_validate_json(row[0]) if row else None

    async def list_sources(self, project_id: str) -> list[ProjectSource]:
        rows = self.conn.execute(
            "SELECT payload FROM project_sources WHERE project_id=? ORDER BY created_at DESC", (project_id,)
        ).fetchall()
        return [ProjectSource.model_validate_json(row[0]) for row in rows]

    async def delete_source(self, project_id: str, source_id: str) -> bool:
        async with self._lock:
            cursor = self.conn.execute(
                "DELETE FROM project_sources WHERE id=? AND project_id=?", (source_id, project_id)
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def load_assignment_config(self) -> AgentAssignmentsConfig | None:
        row = self.conn.execute("SELECT payload FROM app_settings WHERE key='agent_assignments'").fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[0])
            if not isinstance(payload, dict):
                return None
            payload.setdefault("schema_version", 1)
            return AgentAssignmentsConfig.model_validate(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    async def save_assignment_config(self, config: AgentAssignmentsConfig) -> None:
        async with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO app_settings(key,payload) VALUES('agent_assignments',?)",
                (config.model_dump_json(),),
            )
            self.conn.commit()

    def load_providers(self) -> list[ProviderProfile]:
        rows = self.conn.execute("SELECT payload FROM provider_profiles").fetchall()
        providers: list[ProviderProfile] = []
        for (payload,) in rows:
            try:
                providers.append(ProviderProfile.model_validate_json(payload))
            except ValueError:
                continue
        return providers

    async def save_provider(self, provider: ProviderProfile) -> None:
        async with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO provider_profiles(id,payload) VALUES(?,?)",
                (provider.id, provider.model_dump_json()),
            )
            self.conn.commit()

    async def delete_provider(self, provider_id: str) -> None:
        async with self._lock:
            self.conn.execute("DELETE FROM provider_profiles WHERE id=?", (provider_id,))
            self.conn.commit()

    async def save_run(self, run: RunRecord) -> None:
        async with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO runs(id,payload,created_at) VALUES(?,?,?)", (run.id, run.model_dump_json(), run.created_at.isoformat()))
            self.conn.commit()

    async def save_forked_run(self, run: RunRecord, fork: RunFork) -> None:
        """Atomically create a child Run and its immutable lineage record."""
        if fork.child_run_id != run.id:
            raise ValueError("fork child_run_id must match the new Run")
        async with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                if not self.conn.execute("SELECT 1 FROM runs WHERE id=?", (fork.parent_run_id,)).fetchone():
                    raise ValueError("fork parent Run does not exist")
                self.conn.execute(
                    "INSERT INTO runs(id,payload,created_at) VALUES(?,?,?)",
                    (run.id, run.model_dump_json(), run.created_at.isoformat()),
                )
                self.conn.execute(
                    "INSERT INTO run_forks(id,parent_run_id,child_run_id,checkpoint,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        fork.id,
                        fork.parent_run_id,
                        fork.child_run_id,
                        fork.checkpoint,
                        fork.model_dump_json(),
                        fork.created_at.isoformat(),
                    ),
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    async def get_run_fork(self, child_run_id: str) -> RunFork | None:
        row = self.conn.execute(
            "SELECT payload_json FROM run_forks WHERE child_run_id=?",
            (child_run_id,),
        ).fetchone()
        return RunFork.model_validate_json(row[0]) if row else None

    async def list_run_forks(self, parent_run_id: str) -> list[RunFork]:
        rows = self.conn.execute(
            "SELECT payload_json FROM run_forks WHERE parent_run_id=? ORDER BY created_at",
            (parent_run_id,),
        ).fetchall()
        return [RunFork.model_validate_json(row[0]) for row in rows]

    async def get_run_lineage(self, run_id: str) -> RunForkLineage:
        return RunForkLineage(
            parent=await self.get_run_fork(run_id),
            children=await self.list_run_forks(run_id),
        )

    async def runs_are_related(self, left_run_id: str, right_run_id: str) -> bool:
        if left_run_id == right_run_id:
            return True
        rows = self.conn.execute("SELECT parent_run_id,child_run_id FROM run_forks").fetchall()
        graph: dict[str, set[str]] = {}
        for parent, child in rows:
            graph.setdefault(parent, set()).add(child)
            graph.setdefault(child, set()).add(parent)
        pending = [left_run_id]
        seen = {left_run_id}
        while pending:
            current = pending.pop()
            for adjacent in graph.get(current, set()):
                if adjacent == right_run_id:
                    return True
                if adjacent not in seen:
                    seen.add(adjacent)
                    pending.append(adjacent)
        return False

    async def create_decision_brief(self, brief: DecisionBrief) -> DecisionBrief:
        """Append one immutable version, returning the existing identical replay."""
        async with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT payload_json FROM decision_briefs WHERE run_id=? AND version=?",
                    (brief.run_id, brief.version),
                ).fetchone()
                if row:
                    existing = DecisionBrief.model_validate_json(row[0])
                    if existing.model_dump(mode="json", exclude={"id", "generated_at"}) != brief.model_dump(
                        mode="json", exclude={"id", "generated_at"}
                    ):
                        raise ValueError("DecisionBrief version already exists with different content")
                    self.conn.commit()
                    return existing
                if not self.conn.execute("SELECT 1 FROM runs WHERE id=?", (brief.run_id,)).fetchone():
                    raise ValueError("DecisionBrief requires an existing Run")
                self.conn.execute(
                    "INSERT INTO decision_briefs(id,run_id,version,schema_version,payload_json,generation_reason,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        brief.id,
                        brief.run_id,
                        brief.version,
                        brief.schema_version,
                        brief.model_dump_json(),
                        brief.generation_reason,
                        brief.generated_at.isoformat(),
                    ),
                )
                self.conn.commit()
                return brief
            except Exception:
                self.conn.rollback()
                raise

    async def get_decision_brief(self, run_id: str) -> DecisionBrief | None:
        row = self.conn.execute(
            "SELECT payload_json FROM decision_briefs WHERE run_id=? ORDER BY version DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return DecisionBrief.model_validate_json(row[0]) if row else None

    async def claim_idempotent_operation(
        self,
        scope: str,
        operation_key: str,
        request_hash: str,
        *,
        stale_after: timedelta = timedelta(minutes=15),
    ) -> IdempotencyClaim:
        now = datetime.now(timezone.utc)
        async with self._lock:
            row = self.conn.execute(
                "SELECT request_hash,status,response_json,updated_at FROM idempotent_operations WHERE scope=? AND operation_key=?",
                (scope, operation_key),
            ).fetchone()
            if row:
                stored_hash, status, response_json, updated_at = row
                if stored_hash != request_hash:
                    return IdempotencyClaim("conflict")
                if status == "completed" and response_json:
                    return IdempotencyClaim("cached", response_json)
                try:
                    updated = datetime.fromisoformat(updated_at)
                except (TypeError, ValueError):
                    updated = now
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                if status == "in_progress" and now - updated < stale_after:
                    return IdempotencyClaim("in_progress")
                self.conn.execute(
                    "UPDATE idempotent_operations SET status='in_progress',response_json=NULL,updated_at=? WHERE scope=? AND operation_key=?",
                    (now.isoformat(), scope, operation_key),
                )
            else:
                self.conn.execute(
                    "INSERT INTO idempotent_operations(scope,operation_key,request_hash,status,response_json,created_at,updated_at) VALUES(?,?,?,'in_progress',NULL,?,?)",
                    (scope, operation_key, request_hash, now.isoformat(), now.isoformat()),
                )
            self.conn.commit()
        return IdempotencyClaim("claimed")

    async def complete_idempotent_operation(self, scope: str, operation_key: str, response_json: str) -> None:
        async with self._lock:
            self.conn.execute(
                "UPDATE idempotent_operations SET status='completed',response_json=?,updated_at=? WHERE scope=? AND operation_key=?",
                (response_json, datetime.now(timezone.utc).isoformat(), scope, operation_key),
            )
            self.conn.commit()

    async def abandon_idempotent_operation(self, scope: str, operation_key: str) -> None:
        async with self._lock:
            self.conn.execute(
                "DELETE FROM idempotent_operations WHERE scope=? AND operation_key=? AND status='in_progress'",
                (scope, operation_key),
            )
            self.conn.commit()

    async def get_run(self, run_id: str) -> RunRecord | None:
        row = self.conn.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return RunRecord.model_validate_json(row[0]) if row else None

    async def has_high_risk_control(self, run_id: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM high_risk_runs WHERE run_id=? LIMIT 1", (run_id,)
        ).fetchone() is not None

    async def list_runs(self) -> list[RunRecord]:
        rows = self.conn.execute("SELECT payload FROM runs ORDER BY created_at DESC").fetchall()
        return [RunRecord.model_validate_json(row[0]) for row in rows]

    def has_checkpoint(self, run_id: str) -> bool:
        checkpoint_path = Path(self.checkpoint_path)
        if not checkpoint_path.exists():
            return False
        connection = sqlite3.connect(checkpoint_path)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'"
            ).fetchone()
            if not table:
                return False
            return connection.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id=? LIMIT 1", (run_id,)
            ).fetchone() is not None
        finally:
            connection.close()

    async def delete_run(self, run_id: str) -> bool:
        async with self._lock:
            self.conn.execute("DELETE FROM decision_briefs WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM run_forks WHERE parent_run_id=? OR child_run_id=?", (run_id, run_id))
            cursor = self.conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
            self.conn.execute("DELETE FROM run_events WHERE run_id=?", (run_id,))
            self.conn.commit()
            checkpoint_path = Path(self.checkpoint_path)
            if checkpoint_path.exists():
                checkpoint_conn = sqlite3.connect(checkpoint_path)
                try:
                    checkpoint_tables = {
                        row[0]
                        for row in checkpoint_conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('checkpoints','writes')"
                        ).fetchall()
                    }
                    for table in checkpoint_tables:
                        checkpoint_conn.execute(f"DELETE FROM {table} WHERE thread_id=?", (run_id,))
                    checkpoint_conn.commit()
                finally:
                    checkpoint_conn.close()
            return cursor.rowcount > 0

    async def publish(self, event: RunEvent) -> RunEvent:
        async with self._lock:
            cursor = self.conn.execute(
                "INSERT INTO run_events(run_id,payload,created_at) VALUES(?,?,?)",
                (event.run_id, "{}", event.created_at.isoformat()),
            )
            event.sequence = int(cursor.lastrowid)
            self.conn.execute(
                "UPDATE run_events SET payload=? WHERE sequence=?",
                (event.model_dump_json(), event.sequence),
            )
            self.conn.commit()
        condition = self._event_conditions.setdefault(event.run_id, asyncio.Condition())
        async with condition:
            condition.notify_all()
        return event

    async def list_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[RunEvent]:
        rows = self.conn.execute(
            "SELECT sequence,payload FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence ASC LIMIT ?",
            (run_id, max(0, after_sequence), max(1, min(limit, 1000))),
        ).fetchall()
        events: list[RunEvent] = []
        for sequence, payload in rows:
            event = RunEvent.model_validate_json(payload)
            event.sequence = int(sequence)
            events.append(event)
        return events

    async def wait_for_events(
        self,
        run_id: str,
        after_sequence: int,
        timeout: float = 15,
    ) -> list[RunEvent]:
        condition = self._event_conditions.setdefault(run_id, asyncio.Condition())
        async with condition:
            events = await self.list_events(run_id, after_sequence)
            if events:
                return events
            try:
                await asyncio.wait_for(condition.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return []
        return await self.list_events(run_id, after_sequence)

    async def try_open_event_stream(self, run_id: str, limit: int = 8) -> bool:
        async with self._event_stream_lock:
            current = self._event_stream_counts.get(run_id, 0)
            if current >= limit:
                return False
            self._event_stream_counts[run_id] = current + 1
            return True

    async def close_event_stream(self, run_id: str) -> None:
        async with self._event_stream_lock:
            current = self._event_stream_counts.get(run_id, 0)
            if current <= 1:
                self._event_stream_counts.pop(run_id, None)
            else:
                self._event_stream_counts[run_id] = current - 1

    async def seed_events(self, run_id: str) -> None:
        await self.publish(RunEvent(event_id=f"seed-{run_id}", run_id=run_id, type="run_created", stage="setup", message="审议任务已建立", progress=2))

    async def diagnostic_snapshot(self) -> dict[str, Any]:
        async with self._lock:
            counts = {
                table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("runs", "projects", "project_sources", "run_events", "decision_briefs", "run_forks", "provider_profiles")
            }
            integrity = str(self.conn.execute("PRAGMA quick_check").fetchone()[0])
            journal_mode = str(self.conn.execute("PRAGMA journal_mode").fetchone()[0])
            current_schema_version = schema_version(self.conn)
        database_file = Path(self.path)
        checkpoint_file = Path(self.checkpoint_path)
        backup_dir = database_file.parent / "backups"
        backups = sorted(backup_dir.glob(f"{database_file.stem}-schema-v*-to-v*-*.sqlite3")) if backup_dir.exists() else []
        return {
            "integrity": integrity,
            "journal_mode": journal_mode,
            "schema_version": current_schema_version,
            "schema_version_supported": SCHEMA_VERSION,
            "database_bytes": database_file.stat().st_size if database_file.exists() else 0,
            "checkpoint_bytes": checkpoint_file.stat().st_size if checkpoint_file.exists() else 0,
            "schema_backup_count": len(backups),
            "counts": counts,
        }

    def close(self) -> None:
        self.conn.close()


def serialize_public_provider(profile: ProviderProfile) -> dict[str, Any]:
    data = profile.model_dump(mode="json")
    api_key_env = data.pop("api_key_reference", None)
    environment_key_present = bool(api_key_env and os.getenv(api_key_env))
    credential_saved = data.pop("credential_saved", False)
    data["api_key_env"] = api_key_env
    data["has_api_key"] = credential_saved or environment_key_present
    data["credential_source"] = "environment" if environment_key_present else "system" if credential_saved else "none"
    return data
