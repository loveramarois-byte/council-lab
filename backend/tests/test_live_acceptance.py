from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from evals.run_live_acceptance import (
    build_question,
    load_cases,
    public_run_record,
    summarize_ccswitch,
    summarize_provider_attempts,
    validate_real_assignments,
)
from app.provider_catalog import builtin_providers
from app.models import ProviderAttempt, RunCreate, RunLimits
from app.orchestrator import Orchestrator
from app.providers import Generation, OpenAICompatibleProvider
from app.store import Store


ROOT = Path(__file__).resolve().parents[2]


def test_live_acceptance_has_exactly_ten_known_cases():
    cases = load_cases(ROOT / "evals/council_benchmark_v1.json", ROOT / "evals/live_acceptance_v1.json")

    assert len(cases) == 10
    assert len({case["id"] for case in cases}) == 10
    assert "[S1]" in build_question(cases[0], 1)


def test_live_acceptance_rejects_mock_or_incomplete_assignments():
    providers = [
        {"id": "real", "display_name": "Real", "provider_type": "openai_compatible"},
        {"id": "mock", "display_name": "Mock", "provider_type": "mock"},
    ]
    valid = {
        "seats": [{"role": role, "provider_id": "real", "model": "model", "protocol": "auto"} for role in ("a", "b", "c", "d")],
        "finalizer": {"role": "finalizer", "provider_id": "real", "model": "model", "protocol": "auto"},
    }
    assert len(validate_real_assignments(providers, valid)) == 5

    invalid = json.loads(json.dumps(valid))
    invalid["seats"][0]["provider_id"] = "mock"
    with pytest.raises(ValueError, match="refuses mock"):
        validate_real_assignments(providers, invalid)


def test_ccswitch_summary_reports_attempts_tokens_cost_and_failures():
    rows = [
        {"provider_id": "p1", "status_code": 200, "input_tokens": 100, "output_tokens": 20, "total_cost_usd": "0.01", "latency_ms": 30},
        {"provider_id": "p1", "status_code": 503, "input_tokens": 0, "output_tokens": 0, "total_cost_usd": "0", "latency_ms": 10},
    ]

    summary = summarize_ccswitch(rows)

    assert summary == {
        "requests": 2,
        "successful_requests": 1,
        "failed_requests": 1,
        "input_tokens": 100,
        "output_tokens": 20,
        "reported_cost_usd": 0.01,
        "latency_ms": [30, 10],
        "provider_ids": ["p1"],
        "status_codes": {"200": 1, "503": 1},
    }


def test_live_record_keeps_non_sensitive_run_attempts_and_authoritative_latency():
    record = public_run_record(
        {
            "id": "run-1",
            "status": "completed",
            "usage": {"model_calls": 1},
            "provider_attempts": [
                {
                    "role": "analyst",
                    "provider_id": "ccswitch",
                    "provider_name": "CC Switch",
                    "model": "gpt-test",
                    "endpoint": "/responses",
                    "attempt": 1,
                    "status_code": 200,
                    "duration_ms": 1200,
                    "upstream_request_id": "must-not-export",
                    "error_kind": None,
                },
                {
                    "role": "finalizer",
                    "provider_id": "ccswitch",
                    "provider_name": "CC Switch",
                    "model": "gpt-test",
                    "endpoint": "/responses",
                    "attempt": 2,
                    "status_code": 200,
                    "duration_ms": 2400,
                    "error_kind": None,
                },
            ],
        },
        {"id": "case-1", "category": "decision"},
        4000,
    )

    assert len(record["provider_attempts"]) == 2
    assert "upstream_request_id" not in record["provider_attempts"][0]
    assert summarize_provider_attempts(record["provider_attempts"]) == {
        "attribution": "authoritative_run_provider_attempts",
        "requests": 2,
        "successful_requests": 2,
        "failed_requests": 0,
        "retry_attempts": 1,
        "status_codes": {"200": 2},
        "latency_ms": {"p50": 1200, "p95": 1200, "max": 2400, "mean": 1800.0},
    }


async def test_compatible_provider_records_each_http_retry(monkeypatch):
    backend = OpenAICompatibleProvider(builtin_providers()["ccswitch"])
    request = httpx.Request("POST", "http://127.0.0.1:15721/v1/responses")
    responses = iter(
        [
            httpx.Response(503, request=request, headers={"x-request-id": "upstream-1"}),
            httpx.Response(
                200,
                request=request,
                headers={"x-request-id": "upstream-2"},
                json={
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}],
                    "usage": {"input_tokens": 12, "output_tokens": 4},
                },
            ),
        ]
    )

    async def post(*_args, **_kwargs):
        return next(responses)

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(backend.client, "post", post)
    monkeypatch.setattr("app.providers.asyncio.sleep", no_sleep)
    try:
        generation = await backend.generate("question", "system", "gpt-5.6-sol")
    finally:
        await backend.aclose()

    assert generation.text == "done"
    assert [(item.attempt, item.status_code, item.upstream_request_id) for item in generation.attempts] == [
        (1, 503, "upstream-1"),
        (2, 200, "upstream-2"),
    ]


async def test_compatible_provider_bounds_oversized_upstream_request_id(monkeypatch):
    backend = OpenAICompatibleProvider(builtin_providers()["ccswitch"])
    request = httpx.Request("POST", "http://127.0.0.1:15721/v1/responses")
    oversized = "request-" + ("x" * 420)
    response = httpx.Response(
        200,
        request=request,
        headers={"x-request-id": oversized},
        json={
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )

    async def post(*_args, **_kwargs):
        return response

    monkeypatch.setattr(backend.client, "post", post)
    try:
        generation = await backend.generate("question", "system", "gpt-test")
    finally:
        await backend.aclose()

    request_id = generation.attempts[0].upstream_request_id
    assert request_id is not None
    assert len(request_id) == 300
    assert request_id.startswith("request-")
    assert request_id.endswith("x")


async def test_orchestrator_persists_non_sensitive_provider_attempts(tmp_path, monkeypatch):
    providers = builtin_providers()
    providers["ccswitch"].default_model = "gpt-test"
    store = Store(tmp_path / "attempts.sqlite3")
    calls = 0

    class Backend:
        async def generate(self, _prompt, system, model, temperature=0.2):
            nonlocal calls
            calls += 1
            return Generation(
                text="最终答案" if "记录员" in system else f"席位 {calls}",
                attempts=[
                    ProviderAttempt(
                        provider_id="ccswitch",
                        provider_name="CC Switch",
                        model=model,
                        endpoint="/responses",
                        attempt=1,
                        status_code=200,
                        duration_ms=12,
                        upstream_request_id=f"upstream-{calls}",
                    )
                ],
            )

        async def aclose(self):
            return None

    monkeypatch.setattr("app.orchestrator.build_backend", lambda _profile: Backend())
    orchestrator = Orchestrator(store, providers)
    try:
        run = await orchestrator.start(
            RunCreate(
                question="验证 Provider 请求审计是否保存到运行记录",
                mode="standard",
                provider_id="ccswitch",
                auto_summarize=True,
                limits=RunLimits(max_model_calls=5, max_tokens=100000, timeout_seconds=120),
            )
        )
        await orchestrator.tasks[run.id]
        saved = await store.get_run(run.id)
    finally:
        await orchestrator.shutdown()
        store.close()

    assert saved is not None
    assert saved.status == "completed"
    assert [(item.role, item.status_code, item.upstream_request_id) for item in saved.provider_attempts] == [
        ("analyst", 200, "upstream-1"),
        ("challenger", 200, "upstream-2"),
        ("builder", 200, "upstream-3"),
        ("observer", 200, "upstream-4"),
        ("finalizer", 200, "upstream-5"),
    ]
