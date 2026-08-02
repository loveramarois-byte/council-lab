from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TERMINAL_STATUSES = {"completed", "failed", "stopped", "cancelled"}


def load_cases(dataset_path: Path, acceptance_path: Path) -> list[dict[str, Any]]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in dataset.get("cases", [])}
    case_ids = acceptance.get("case_ids", [])
    if len(case_ids) != 10 or len(set(case_ids)) != 10:
        raise ValueError("live acceptance must contain exactly ten unique case IDs")
    missing = [case_id for case_id in case_ids if case_id not in by_id]
    if missing:
        raise ValueError(f"unknown acceptance cases: {', '.join(missing)}")
    return [by_id[case_id] for case_id in case_ids]


def build_question(case: dict[str, Any], index: int) -> str:
    materials = "\n\n".join(
        f"[S{source_index}] {item['title']}\n{item['content']}"
        for source_index, item in enumerate(case.get("materials", []), 1)
    )
    prefix = f"【真实模型验收 {index}/10 · {case['id']}】"
    return f"{prefix}\n{case['prompt']}\n\n给定资料：\n{materials}" if materials else f"{prefix}\n{case['prompt']}"


def validate_real_assignments(
    providers: list[dict[str, Any]], assignments: dict[str, Any]
) -> list[dict[str, str]]:
    provider_by_id = {provider["id"]: provider for provider in providers}
    configured = [*assignments.get("seats", []), assignments.get("finalizer")]
    if len(configured) != 5 or configured[-1] is None:
        raise ValueError("saved assignments must contain four seats and one finalizer")
    public: list[dict[str, str]] = []
    for assignment in configured:
        provider_id = assignment.get("provider_id", "")
        provider = provider_by_id.get(provider_id)
        if not provider:
            raise ValueError(f"assignment references unknown provider: {provider_id}")
        if provider_id == "mock" or provider.get("provider_type") == "mock":
            raise ValueError("live acceptance refuses mock assignments")
        model = assignment.get("model", "").strip()
        if not model:
            raise ValueError(f"assignment {assignment.get('role')} has no model")
        public.append(
            {
                "role": assignment.get("role", ""),
                "provider_id": provider_id,
                "provider_name": provider.get("display_name", provider_id),
                "model": model,
                "protocol": assignment.get("protocol", "auto"),
            }
        )
    return public


class CouncilClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, *, key: str | None = None) -> Any:
        headers = {
            "Accept": "application/json",
            "X-Council-Internal-Token": self.token,
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail[:500]}") from exc


def public_run_record(run: dict[str, Any], case: dict[str, Any], wall_time_ms: int) -> dict[str, Any]:
    turns = [
        {
            "speaker_id": turn.get("speaker_id"),
            "speaker_name": turn.get("speaker_name"),
            "stage": turn.get("stage"),
            "provider_id": turn.get("provider_id"),
            "model": turn.get("model"),
            "content": turn.get("content", ""),
        }
        for turn in run.get("discussion_turns", [])
        if turn.get("speaker_type") == "agent"
    ]
    return {
        "case_id": case["id"],
        "category": case["category"],
        "run_id": run.get("id"),
        "status": run.get("status"),
        "degraded": bool(run.get("degraded")),
        "error": run.get("error"),
        "wall_time_ms": wall_time_ms,
        "usage": run.get("usage", {}),
        "turns": turns,
        "final_decision": run.get("final_decision"),
        "reference_points": case.get("reference_points", []),
        "forbidden_claims": case.get("forbidden_claims", []),
    }


def read_ccswitch_rows(db_path: Path, model: str, since: int) -> list[dict[str, Any]]:
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
            WHERE app_type = 'codex'
              AND COALESCE(NULLIF(TRIM(request_model), ''), NULLIF(TRIM(model), '')) = ?
              AND created_at >= ?
            ORDER BY created_at, request_id
            """,
            (model, since),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def summarize_ccswitch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "requests": len(rows),
        "successful_requests": sum(1 for row in rows if 200 <= int(row["status_code"]) < 300),
        "failed_requests": sum(1 for row in rows if not 200 <= int(row["status_code"]) < 300),
        "input_tokens": sum(int(row["input_tokens"] or 0) for row in rows),
        "output_tokens": sum(int(row["output_tokens"] or 0) for row in rows),
        "reported_cost_usd": round(sum(float(row["total_cost_usd"] or 0) for row in rows), 6),
        "latency_ms": [int(row["latency_ms"] or 0) for row in rows],
        "provider_ids": sorted({str(row["provider_id"]) for row in rows}),
        "status_codes": {
            str(status): sum(1 for row in rows if int(row["status_code"]) == status)
            for status in sorted({int(row["status_code"]) for row in rows})
        },
    }


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise ValueError("internal API token file is missing or invalid")
    cases = load_cases(args.dataset, args.acceptance)
    client = CouncilClient(args.base_url, token)
    providers = client.request("GET", "/api/providers")
    assignments = client.request("GET", "/api/agent-assignments")
    public_assignments = validate_real_assignments(providers, assignments)
    models = {item["model"] for item in public_assignments}
    if len(models) != 1:
        raise ValueError("this acceptance runner currently requires one shared model for request accounting")
    model = next(iter(models))

    session_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    started_epoch = int(time.time()) - 1
    baseline_ids = {row["request_id"] for row in read_ccswitch_rows(args.ccswitch_db, model, started_epoch)}
    results: list[dict[str, Any]] = []
    logical_calls = 0

    for index, case in enumerate(cases, 1):
        if logical_calls + 5 > args.max_calls:
            break
        create_started = time.perf_counter()
        run = client.request(
            "POST",
            "/api/runs",
            {
                "question": build_question(case, index),
                "mode": "standard",
                "council_mode": "general",
                "workflow_strategy": "sequential",
                "use_saved_assignments": True,
                "auto_summarize": True,
                "limits": {"max_model_calls": 5, "max_tokens": 100000, "timeout_seconds": 900},
            },
            key=f"live-acceptance:{session_id}:{case['id']}",
        )
        run_id = run["id"]
        deadline = time.monotonic() + args.run_timeout
        while run.get("status") not in TERMINAL_STATUSES:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"run {run_id} did not finish within {args.run_timeout} seconds")
            time.sleep(args.poll_interval)
            run = client.request("GET", f"/api/runs/{run_id}")
        wall_time_ms = int((time.perf_counter() - create_started) * 1000)
        record = public_run_record(run, case, wall_time_ms)
        results.append(record)
        calls = int(record.get("usage", {}).get("model_calls", 0))
        logical_calls += calls
        print(
            f"[{index}/10] {case['id']}: status={record['status']} "
            f"calls={calls} total={logical_calls}/{args.max_calls} wall_ms={wall_time_ms}",
            flush=True,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        partial = {
            "schema_version": "council-live-acceptance-result-v1",
            "session_id": session_id,
            "started_at": started_at.isoformat(),
            "completed_at": None,
            "expected_logical_calls": args.max_calls,
            "logical_calls": logical_calls,
            "assignments": public_assignments,
            "cases": results,
            "complete": False,
        }
        args.output.write_text(json.dumps(partial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if record["status"] != "completed" or calls != 5:
            break

    completed_at = datetime.now(timezone.utc)
    all_rows = read_ccswitch_rows(args.ccswitch_db, model, started_epoch)
    session_rows = [row for row in all_rows if row["request_id"] not in baseline_ids]
    result = {
        "schema_version": "council-live-acceptance-result-v1",
        "session_id": session_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "expected_logical_calls": args.max_calls,
        "logical_calls": logical_calls,
        "assignments": public_assignments,
        # CC Switch can be shared by other local clients. This time-window view
        # is diagnostic only; Run usage remains the authoritative call count.
        "ccswitch_shared_log_window": {
            "attribution": "untrusted_shared_window",
            **summarize_ccswitch(session_rows),
        },
        "cases": results,
        "complete": len(results) == 10 and logical_calls == args.max_calls and all(item["status"] == "completed" for item in results),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ten real Council runs with a hard 50 logical-call budget.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--token-file", type=Path, default=Path.home() / "Library/Logs/Council/backend-access.token")
    parser.add_argument("--ccswitch-db", type=Path, default=Path.home() / ".cc-switch/cc-switch.db")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/council_benchmark_v1.json")
    parser.add_argument("--acceptance", type=Path, default=ROOT / "evals/live_acceptance_v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evals/results/live-acceptance-50.json")
    parser.add_argument("--max-calls", type=int, choices=[50], default=50)
    parser.add_argument("--run-timeout", type=float, default=900)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    report = run_acceptance(arguments)
    print(json.dumps({
        "complete": report["complete"],
        "logical_calls": report["logical_calls"],
        "ccswitch_shared_log_window": report["ccswitch_shared_log_window"],
        "output": str(arguments.output),
    }, ensure_ascii=False, indent=2))
