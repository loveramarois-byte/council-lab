from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .models import AgentAssignmentsConfig, ProviderProfile, RunEvent, RunRecord


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        source_path = Path(self.path)
        self.checkpoint_path = str(source_path.with_name(f"{source_path.stem}.checkpoints{source_path.suffix}"))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._queues: dict[str, asyncio.Queue[RunEvent]] = {}
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS provider_profiles (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.conn.commit()

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

    async def publish(self, event: RunEvent) -> None:
        queue = self._queues.setdefault(event.run_id, asyncio.Queue())
        await queue.put(event)

    def queue(self, run_id: str) -> asyncio.Queue[RunEvent]:
        return self._queues.setdefault(run_id, asyncio.Queue())

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
