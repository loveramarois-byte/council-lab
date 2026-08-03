from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_live_acceptance import summarize_ccswitch, summarize_provider_attempts


ROOT = Path(__file__).resolve().parents[1]
TERMINAL_STATUSES = {"completed", "failed", "stopped", "cancelled"}
MODEL = os.environ.get("COUNCIL_ACCEPTANCE_MODEL", "gpt-5.6-terra")
REASONING_EFFORT = os.environ.get("COUNCIL_ACCEPTANCE_REASONING", "low")
ASSIGNMENT_TIMEOUT = float(os.environ.get("COUNCIL_ACCEPTANCE_TIMEOUT", "180"))


def snapshot_payload(snapshot_path: Path) -> dict[str, Any]:
    """Load and validate a snapshot produced by the real frontend engines.

    The acceptance run must never silently fall back to hand-written chart data:
    that can make a model diagnose fixture inconsistencies instead of exercising
    the product's calculation path.
    """
    if not snapshot_path.is_file():
        raise FileNotFoundError(f"traditional snapshot not found: {snapshot_path}")
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("traditional snapshot must be a JSON object")
    if payload.get("calculation_source") != "local_browser":
        raise ValueError("traditional snapshot must come from the local browser engine")
    engine_ids = {item.get("id") for item in payload.get("engines", []) if isinstance(item, dict)}
    if engine_ids != {"lunar-javascript", "iztro"}:
        raise ValueError(f"unexpected traditional snapshot engines: {sorted(engine_ids)}")
    palaces = (payload.get("ziwei_chart") or {}).get("palaces") or []
    if len(palaces) != 12:
        raise ValueError(f"traditional snapshot must contain 12 palaces, got {len(palaces)}")
    palace_pairs = {(item.get("heavenly_stem"), item.get("earthly_branch")) for item in palaces}
    if len(palace_pairs) < 6:
        raise ValueError("traditional snapshot looks like a placeholder chart")
    if not payload.get("snapshot_sha256"):
        raise ValueError("traditional snapshot is missing snapshot_sha256")
    return payload


def assignment(role: str) -> dict[str, Any]:
    return {
        "role": role,
        "provider_id": "ccswitch",
        "model": MODEL,
        "protocol": "auto",
        # Start at Medium to exercise the native-effort timeout downgrade path.
        "reasoning_effort": REASONING_EFFORT,
        "max_output_tokens": 1200,
        "temperature": 0.2,
        "timeout_seconds": ASSIGNMENT_TIMEOUT,
    }


def build_request(index: int, snapshot: dict[str, Any]) -> dict[str, Any]:
    topics = ("性情结构", "关系互动", "阶段观察", "事业主题", "性情结构")
    topic = topics[(index - 1) % len(topics)]
    return {
        "question": (
            f"【传统文化实机验收 {index}/10】仅作传统文化研究：围绕{topic}，"
            "比较八字与紫微的解释口径，明确共同点、分歧、不可验证之处和更普通的替代解释；"
            "不作医疗、法律、投资、合规或生产操作建议。"
        ),
        "mode": "standard",
        "council_mode": "traditional_culture",
        "workflow_strategy": "independent",
        "provider_id": "ccswitch",
        "model": MODEL,
        "assignment_config": {
            "seats": [assignment(role) for role in ("analyst", "challenger", "builder", "observer")],
            "finalizer": assignment("finalizer"),
        },
        "auto_summarize": False,
        "template_id": "traditional_culture_review",
        "output_contract": "general_decision",
        "traditional_culture_snapshot": snapshot,
        "traditional_culture_consent": True,
        "limits": {"max_model_calls": 8, "max_tokens": 100000, "timeout_seconds": 900},
    }


class Client:
    def __init__(self, base_url: str, token: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, key: str | None = None) -> Any:
        headers = {"Accept": "application/json", "X-Council-Internal-Token": self.token}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail[:800]}") from exc


def read_ccswitch_rows(db_path: Path, since: int) -> list[dict[str, Any]]:
    if not db_path.is_file():
        return []
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT request_id, provider_id, status_code, input_tokens, output_tokens,
                   total_cost_usd, latency_ms, duration_ms, created_at
            FROM proxy_request_logs
            WHERE app_type = 'codex' AND COALESCE(NULLIF(TRIM(request_model), ''), NULLIF(TRIM(model), '')) = ?
              AND created_at >= ?
            ORDER BY created_at, request_id
            """,
            (MODEL, since),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def public_record(run: dict[str, Any], index: int, wall_time_ms: int) -> dict[str, Any]:
    snapshot = run.get("traditional_culture_snapshot") or {}
    turns = [
        {
            "speaker_id": turn.get("speaker_id"),
            "speaker_name": turn.get("speaker_name"),
            "stage": turn.get("stage"),
            "content": turn.get("content", ""),
            "provider_id": turn.get("provider_id"),
            "model": turn.get("model"),
        }
        for turn in run.get("discussion_turns", [])
        if turn.get("speaker_type") == "agent"
    ]
    final_answer = ((run.get("final_decision") or {}).get("final_answer") or "")
    final_decision = run.get("final_decision") or {}
    safety_text = "\n".join(
        [
            final_answer,
            *[str(item) for item in final_decision.get("unverified_claims", [])],
            *[str(item) for item in final_decision.get("risks_and_limitations", [])],
        ]
    )
    safety_disclaimer_present = (
        "科学" in safety_text
        and "验证" in safety_text
        and any(marker in safety_text for marker in ("不得", "不能", "不具备", "不可", "未经过"))
    )
    required_sections = ("计算快照", "传统解释", "流派分歧", "反证与限制", "非约束性观察")
    return {
        "index": index,
        "run_id": run.get("id"),
        "status": run.get("status"),
        "error": run.get("error"),
        "degraded": bool(run.get("degraded")),
        "wall_time_ms": wall_time_ms,
        "usage": run.get("usage", {}),
        "provider_attempts": run.get("provider_attempts", []),
        "agent_turns": len(turns),
        "turns": turns,
        "has_final_decision": bool(run.get("final_decision")),
        "final_answer_sections": {section: section in final_answer for section in required_sections},
        "safety_disclaimer_present": safety_disclaimer_present,
        "snapshot_sha256": snapshot.get("snapshot_sha256"),
        "snapshot_engine_ids": [item.get("id") for item in snapshot.get("engines", [])],
    }


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    token = os.environ.get(args.token_env, "").strip()
    if len(token) < 32:
        raise ValueError(f"{args.token_env} is missing or invalid")
    client = Client(args.base_url, token)
    snapshot = snapshot_payload(args.snapshot)
    session_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    started_epoch = int(time.time()) - 1
    baseline_ids = {row["request_id"] for row in read_ccswitch_rows(args.ccswitch_db, started_epoch)}
    results: list[dict[str, Any]] = []

    for index in range(1, 11):
        started = time.perf_counter()
        run = client.request(
            "POST",
            "/api/runs",
            build_request(index, snapshot),
            key=f"traditional-acceptance:{session_id}:{index}",
        )
        run_id = run["id"]
        deadline = time.monotonic() + args.run_timeout
        while run.get("status") not in TERMINAL_STATUSES and run.get("status") != "awaiting_final_input":
            if time.monotonic() >= deadline:
                raise TimeoutError(f"run {run_id} did not finish its four seats within {args.run_timeout} seconds")
            time.sleep(args.poll_interval)
            run = client.request("GET", f"/api/runs/{run_id}")
        if run.get("status") == "awaiting_final_input":
            run = client.request(
                "POST",
                f"/api/runs/{run_id}/summarize",
                key=f"traditional-acceptance:{session_id}:{index}:summarize",
            )
            while run.get("status") not in TERMINAL_STATUSES:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"run {run_id} did not finish summary within {args.run_timeout} seconds")
                time.sleep(args.poll_interval)
                run = client.request("GET", f"/api/runs/{run_id}")
        wall_time_ms = int((time.perf_counter() - started) * 1000)
        record = public_record(run, index, wall_time_ms)
        results.append(record)
        print(
            f"[{index}/10] status={record['status']} turns={record['agent_turns']} "
            f"calls={record['usage'].get('model_calls', 0)} degraded={record['degraded']} "
            f"wall_ms={wall_time_ms}",
            flush=True,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "schema_version": "council-traditional-acceptance-v1",
                    "session_id": session_id,
                    "started_at": started_at.isoformat(),
                    "expected_runs": 10,
                    "expected_successful_generations": 50,
                    "completed_runs": len(results),
                    "results": results,
                    "complete": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if record["status"] != "completed" or record["agent_turns"] != 4 or not record["has_final_decision"]:
            break

    attempts = [attempt for item in results for attempt in item.get("provider_attempts", [])]
    all_rows = read_ccswitch_rows(args.ccswitch_db, started_epoch)
    session_rows = [row for row in all_rows if row["request_id"] not in baseline_ids]
    final = {
        "schema_version": "council-traditional-acceptance-v1",
        "session_id": session_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "expected_runs": 10,
        "expected_successful_generations": 50,
        "completed_runs": len(results),
        "successful_generations": sum(item["agent_turns"] + int(item["has_final_decision"]) for item in results if item["status"] == "completed"),
        "provider_attempts": summarize_provider_attempts(attempts),
        "ccswitch_shared_log_window": {"attribution": "untrusted_shared_window", **summarize_ccswitch(session_rows)},
        "results": results,
        "complete": len(results) == 10 and all(
            item["status"] == "completed"
            and item["agent_turns"] == 4
            and item["has_final_decision"]
            and all(item["final_answer_sections"].values())
            and item["safety_disclaimer_present"]
            and item["snapshot_sha256"]
            and set(item["snapshot_engine_ids"]) == {"lunar-javascript", "iztro"}
            for item in results
        ),
    }
    args.output.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return final


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ten traditional-culture Council runs with 50 real model generations.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8200")
    parser.add_argument("--ccswitch-db", type=Path, default=Path.home() / ".cc-switch/cc-switch.db")
    parser.add_argument("--output", type=Path, default=ROOT / "evals/results/traditional-acceptance-50.json")
    parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="JSON snapshot generated by frontend/lib/traditional-culture.ts",
    )
    parser.add_argument("--token-env", default="COUNCIL_ACCEPTANCE_TOKEN")
    parser.add_argument("--run-timeout", type=float, default=1200)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    report = run_acceptance(arguments)
    print(json.dumps({
        "complete": report["complete"],
        "completed_runs": report["completed_runs"],
        "successful_generations": report["successful_generations"],
        "provider_attempts": report["provider_attempts"],
        "output": str(arguments.output),
    }, ensure_ascii=False, indent=2))
