from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .models import AgentAssignmentsConfig, ProjectRecord, ProjectSource, ProviderProfile, RunEvent, RunRecord


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
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS provider_profiles (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS project_sources (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_project_sources_project ON project_sources(project_id, created_at)")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS run_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence ON run_events(run_id, sequence)")
        self.conn.commit()

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
            return AgentAssignmentsConfig.model_validate_json(row[0])
        except ValueError:
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

    async def get_run(self, run_id: str) -> RunRecord | None:
        row = self.conn.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return RunRecord.model_validate_json(row[0]) if row else None

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
