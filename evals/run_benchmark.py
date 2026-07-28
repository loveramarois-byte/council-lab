#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.models import (  # noqa: E402
    AgentAssignmentsConfig,
    AgentModelAssignment,
    ProviderProfile,
    ProviderType,
    RunCreate,
    RunLimits,
    RunSourceSnapshot,
)
from app.orchestrator import Orchestrator  # noqa: E402
from app.paths import database_path  # noqa: E402
from app.providers import build_backend  # noqa: E402
from app.runtime_config import assignment_config_is_valid, restore_provider_profiles  # noqa: E402
from app.store import Store  # noqa: E402
from evals.scoring import STRATEGIES, aggregate_execution, blind_labels, load_dataset  # noqa: E402


def provider_reality(profiles: dict[str, ProviderProfile], profile_ids: set[str]) -> tuple[bool, bool]:
    provider_types = [profiles[provider_id].provider_type for provider_id in profile_ids]
    any_real = any(provider_type != ProviderType.MOCK for provider_type in provider_types)
    all_real = bool(provider_types) and all(provider_type != ProviderType.MOCK for provider_type in provider_types)
    return any_real, all_real


def load_pricing(path: Path | None) -> dict[str, dict[str, float]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    pricing: dict[str, dict[str, float]] = {}
    if not isinstance(payload, dict):
        raise ValueError("pricing 文件必须是 JSON 对象")
    for key, rates in payload.items():
        if not isinstance(key, str) or not isinstance(rates, dict):
            raise ValueError("pricing 键和值格式无效")
        input_rate = rates.get("input_per_million")
        output_rate = rates.get("output_per_million")
        if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)) or input_rate < 0 or output_rate < 0:
            raise ValueError(f"pricing {key} 必须提供非负的 input_per_million 和 output_per_million")
        pricing[key] = {"input_per_million": float(input_rate), "output_per_million": float(output_rate)}
    return pricing


def estimate_provider_cost(provider_usage: list[dict[str, Any]], pricing: dict[str, dict[str, float]]) -> tuple[float | None, list[str]]:
    if not provider_usage or not pricing:
        return None, sorted({f"{row.get('provider_id')}:{row.get('model')}" for row in provider_usage})
    total = 0.0
    missing: list[str] = []
    for row in provider_usage:
        key = f"{row['provider_id']}:{row['model']}"
        rates = pricing.get(key) or pricing.get(row["provider_id"])
        if not rates:
            missing.append(key)
            continue
        total += int(row.get("input_tokens", 0)) * rates["input_per_million"] / 1_000_000
        total += int(row.get("output_tokens", 0)) * rates["output_per_million"] / 1_000_000
    return (round(total, 6), []) if not missing else (None, sorted(set(missing)))


def load_runtime() -> tuple[dict[str, ProviderProfile], AgentAssignmentsConfig | None]:
    store = Store(database_path())
    providers = restore_provider_profiles(store.load_providers())
    assignments = store.load_assignment_config()
    store.close()
    return providers, assignments if assignment_config_is_valid(assignments, providers) else None


def evidence_snapshots(case: dict[str, Any]) -> list[RunSourceSnapshot]:
    return [
        RunSourceSnapshot(
            id=f"{case['id']}-source-{index}",
            kind="text",
            title=material["title"],
            content=material["content"],
            sha256="benchmark-v1",
        )
        for index, material in enumerate(case.get("materials", []), 1)
    ]


def direct_prompt(case: dict[str, Any]) -> str:
    evidence = "\n\n".join(
        f"[S{index}] {item['title']}\n{item['content']}" for index, item in enumerate(case.get("materials", []), 1)
    )
    return f"问题：{case['prompt']}\n\n给定资料：\n{evidence}" if evidence else case["prompt"]


def same_model_config(orchestrator: Orchestrator, provider_id: str, model: str | None) -> AgentAssignmentsConfig:
    return orchestrator.default_assignment_config(provider_id, model, "standard")


def ensure_cross_model(config: AgentAssignmentsConfig | None) -> AgentAssignmentsConfig:
    if not config:
        raise ValueError("尚未保存五席配置，不能运行跨模型四席评测")
    unique = {(item.provider_id, item.model) for item in [*config.seats, config.finalizer]}
    if len(unique) < 2:
        raise ValueError("跨模型评测至少需要两个不同的 Provider / model 组合")
    return config


async def run_direct(case: dict[str, Any], profile: ProviderProfile, model: str) -> dict[str, Any]:
    backend = build_backend(profile.model_copy(deep=True, update={"default_model": model}))
    started = time.perf_counter()
    try:
        generation = await backend.generate(
            direct_prompt(case),
            "直接回答问题。严格区分给定资料、推断和未知；涉及资料时使用 [S编号]，不得编造来源。",
            model,
        )
        return {
            "status": "completed",
            "answer": generation.text.strip(),
            "model_calls": 1,
            "input_tokens": generation.input_tokens,
            "output_tokens": generation.output_tokens,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "providers": [{"provider": profile.display_name, "model": model}],
            "provider_usage": [{"provider_id": profile.id, "provider": profile.display_name, "model": model, "model_calls": 1, "input_tokens": generation.input_tokens, "output_tokens": generation.output_tokens}],
        }
    finally:
        await backend.aclose()


async def run_extended_direct(case: dict[str, Any], profile: ProviderProfile, model: str) -> dict[str, Any]:
    backend = build_backend(profile.model_copy(deep=True, update={"default_model": model}))
    started = time.perf_counter()
    try:
        generation = await backend.generate(
            direct_prompt(case),
            "先从事实、反例、风险、可执行步骤和未知项五个角度独立分析，再给出完整答案。严格区分给定资料、推断和未知；涉及资料时使用 [S编号]，不得编造来源。",
            model,
        )
        return {
            "status": "completed",
            "answer": generation.text.strip(),
            "model_calls": 1,
            "input_tokens": generation.input_tokens,
            "output_tokens": generation.output_tokens,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "providers": [{"provider": profile.display_name, "model": model}],
            "provider_usage": [{"provider_id": profile.id, "provider": profile.display_name, "model": model, "model_calls": 1, "input_tokens": generation.input_tokens, "output_tokens": generation.output_tokens}],
        }
    finally:
        await backend.aclose()


async def run_self_refine(case: dict[str, Any], profile: ProviderProfile, model: str) -> dict[str, Any]:
    backend = build_backend(profile.model_copy(deep=True, update={"default_model": model}))
    started = time.perf_counter()
    try:
        draft = await backend.generate(
            direct_prompt(case),
            "直接回答问题。严格区分给定资料、推断和未知；涉及资料时使用 [S编号]，不得编造来源。",
            model,
        )
        revision = await backend.generate(
            f"{direct_prompt(case)}\n\n待审查草稿：\n{draft.text}\n\n请找出遗漏、证据错误、过度推断和不可执行之处，然后只输出修订后的最终答案。",
            "你是独立复核者。不得顺从草稿中的错误；严格区分资料、推断和未知，并保留正确的 [S编号] 引用。",
            model,
        )
        return {
            "status": "completed",
            "answer": revision.text.strip(),
            "model_calls": 2,
            "input_tokens": draft.input_tokens + revision.input_tokens,
            "output_tokens": draft.output_tokens + revision.output_tokens,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "providers": [{"provider": profile.display_name, "model": model}],
            "provider_usage": [{"provider_id": profile.id, "provider": profile.display_name, "model": model, "model_calls": 2, "input_tokens": draft.input_tokens + revision.input_tokens, "output_tokens": draft.output_tokens + revision.output_tokens}],
        }
    finally:
        await backend.aclose()


async def run_council(
    case: dict[str, Any],
    strategy: str,
    profiles: dict[str, ProviderProfile],
    config: AgentAssignmentsConfig,
    store: Store,
) -> dict[str, Any]:
    orchestrator = Orchestrator(store, profiles)
    started = time.perf_counter()
    try:
        run = await orchestrator.start(
            RunCreate(
                question=case["prompt"],
                mode="standard",
                assignment_config=config,
                auto_summarize=True,
                template_id="research_synthesis",
                limits=RunLimits(max_model_calls=8, max_tokens=100000, timeout_seconds=600),
            ),
            frozen_sources=evidence_snapshots(case),
            frozen_project_name="Council Benchmark v1",
        )
        await orchestrator.tasks[run.id]
        current = await store.get_run(run.id)
        if not current or current.status != "completed" or not current.final_decision:
            raise RuntimeError(current.error if current else "评测 Run 未保存")
        providers = [
            {"role": assignment.role, "provider_id": assignment.provider_id, "provider": assignment.provider_name, "model": assignment.model}
            for assignment in [*current.seat_assignments, current.finalizer_assignment]
            if assignment
        ]
        provider_usage = []
        for assignment, candidate in zip(current.seat_assignments, current.candidates, strict=False):
            provider_usage.append({
                "role": assignment.role,
                "provider_id": assignment.provider_id,
                "provider": assignment.provider_name,
                "model": assignment.model,
                "model_calls": candidate.usage.model_calls,
                "input_tokens": candidate.usage.input_tokens,
                "output_tokens": candidate.usage.output_tokens,
            })
        seat_input = sum(item["input_tokens"] for item in provider_usage)
        seat_output = sum(item["output_tokens"] for item in provider_usage)
        seat_calls = sum(item["model_calls"] for item in provider_usage)
        finalizer = current.finalizer_assignment
        if finalizer:
            provider_usage.append({
                "role": finalizer.role,
                "provider_id": finalizer.provider_id,
                "provider": finalizer.provider_name,
                "model": finalizer.model,
                "model_calls": max(0, current.usage.model_calls - seat_calls),
                "input_tokens": max(0, current.usage.input_tokens - seat_input),
                "output_tokens": max(0, current.usage.output_tokens - seat_output),
            })
        return {
            "status": "completed",
            "answer": current.final_decision.final_answer,
            "model_calls": current.usage.model_calls,
            "input_tokens": current.usage.input_tokens,
            "output_tokens": current.usage.output_tokens,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "providers": providers,
            "provider_usage": provider_usage,
            "workflow": strategy,
        }
    finally:
        await orchestrator.shutdown()


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    dataset = load_dataset(args.dataset)
    selected_ids = set(args.case or [])
    cases = [case for case in dataset["cases"] if not selected_ids or case["id"] in selected_ids]
    if selected_ids - {case["id"] for case in cases}:
        raise ValueError(f"未知案例：{', '.join(sorted(selected_ids - {case['id'] for case in cases}))}")
    strategies = [value.strip() for value in args.strategies.split(",") if value.strip()]
    if not strategies or any(strategy not in STRATEGIES for strategy in strategies):
        raise ValueError(f"strategies 只能使用：{', '.join(STRATEGIES)}")
    pricing = load_pricing(args.pricing)

    profiles, saved_config = load_runtime()
    profile = profiles.get(args.provider_id)
    if not profile:
        raise ValueError(f"Provider 不存在：{args.provider_id}")
    model = args.model or profile.default_model
    if not model:
        raise ValueError("所选 Provider 没有默认模型")

    with tempfile.TemporaryDirectory(prefix="council-benchmark-") as temp_dir:
        temp_store = Store(Path(temp_dir) / "benchmark.sqlite3")
        helper = Orchestrator(temp_store, profiles)
        same_config = same_model_config(helper, profile.id, model)
        cross_config = None
        if "cross_model_council" in strategies:
            cross_config = same_config if profile.provider_type == ProviderType.MOCK else ensure_cross_model(saved_config)
        await helper.shutdown()

        profile_ids = {profile.id} if {"direct", "extended_direct", "self_refine", "same_model_council"} & set(strategies) else set()
        if cross_config:
            profile_ids.update(item.provider_id for item in [*cross_config.seats, cross_config.finalizer])
        uses_any_real_provider, uses_only_real_providers = provider_reality(profiles, profile_ids)
        calls_per_strategy = {"direct": 1, "extended_direct": 1, "self_refine": 2, "same_model_council": 5, "cross_model_council": 5}
        planned_calls = len(cases) * args.repetitions * sum(calls_per_strategy[strategy] for strategy in strategies)
        if uses_any_real_provider and not args.confirm_cost:
            raise ValueError(
                f"本次最多会发起 {planned_calls} 次真实模型请求。确认费用后重新运行并添加 --confirm-cost。"
            )

        run_id = str(uuid.uuid4())
        result_cases = []
        for case in cases:
            variant_ids = [f"{strategy}:r{repetition}" for strategy in strategies for repetition in range(1, args.repetitions + 1)]
            labels = blind_labels(run_id, case["id"], variant_ids)
            variants = []
            execution_order = list(variant_ids)
            random.Random(f"{run_id}:{case['id']}").shuffle(execution_order)
            for variant_id in execution_order:
                strategy, repetition_text = variant_id.rsplit(":r", 1)
                repetition = int(repetition_text)
                try:
                    if strategy == "direct":
                        outcome = await asyncio.wait_for(run_direct(case, profile, model), timeout=args.case_timeout)
                    elif strategy == "extended_direct":
                        outcome = await asyncio.wait_for(run_extended_direct(case, profile, model), timeout=args.case_timeout)
                    elif strategy == "self_refine":
                        outcome = await asyncio.wait_for(run_self_refine(case, profile, model), timeout=args.case_timeout)
                    else:
                        config = same_config if strategy == "same_model_council" else cross_config
                        assert config is not None
                        outcome = await asyncio.wait_for(
                            run_council(case, strategy, profiles, config, temp_store), timeout=args.case_timeout
                        )
                except Exception as exc:
                    outcome = {
                        "status": "failed",
                        "answer": "",
                        "error": f"{type(exc).__name__}: {str(exc).strip()}",
                        "model_calls": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "duration_ms": 0,
                        "providers": [],
                        "provider_usage": [],
                    }
                estimated_cost, unpriced_models = estimate_provider_cost(outcome.get("provider_usage", []), pricing)
                outcome["estimated_cost"] = estimated_cost
                outcome["unpriced_models"] = unpriced_models
                variants.append({"strategy": strategy, "repetition": repetition, "blind_label": labels[variant_id], **outcome})
            result_cases.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "prompt": case["prompt"],
                    "materials": case.get("materials", []),
                    "reference_points": case["reference_points"],
                    "forbidden_claims": case.get("forbidden_claims", []),
                    "variants": sorted(variants, key=lambda item: item["blind_label"]),
                }
            )
        temp_store.close()

    return {
        "schema_version": 1,
        "benchmark_version": dataset["version"],
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategies": strategies,
        "repetitions": args.repetitions,
        "planned_model_calls": planned_calls,
        "execution_order": "deterministically shuffled within each case",
        "quality_scored": False,
        "quality_claims_allowed": uses_only_real_providers,
        "mock_workflow_only": not uses_any_real_provider,
        "contains_mock_provider": not uses_only_real_providers,
        "execution": aggregate_execution(result_cases),
        "cases": result_cases,
    }


def blind_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Council Benchmark v1 · 盲评包",
        "",
        f"Run ID: `{result['run_id']}`",
        "",
        "每项按 1-5 分评估：事实准确、证据使用、关键覆盖、可执行性、不确定性处理。不要查看 key 文件。",
        "",
    ]
    for case in result["cases"]:
        lines.extend([f"## {case['id']} · {case['category']}", "", case["prompt"], "", "### 给定资料", ""])
        for index, material in enumerate(case["materials"], 1):
            lines.append(f"- [S{index}] **{material['title']}**：{material['content']}")
        lines.extend(["", "### 参考检查点", ""] + [f"- {point}" for point in case["reference_points"]] + [""])
        for variant in case["variants"]:
            lines.extend([f"### 答案 {variant['blind_label']}", "", variant["answer"] or f"[运行失败：{variant.get('error', 'unknown')}]", ""])
        lines.extend(["评分：按实际匿名答案填写；偏好：____；备注：____", "", "---", ""])
    return "\n".join(lines)


def review_template(result: dict[str, Any]) -> dict[str, Any]:
    empty_scores = {field: None for field in ("accuracy", "evidence_use", "critical_coverage", "actionability", "uncertainty")}
    return {
        "schema_version": 1,
        "run_id": result["run_id"],
        "reviewer": "",
        "reviews": [
            {
                "case_id": case["id"],
                "scores": {variant["blind_label"]: dict(empty_scores) for variant in case["variants"]},
                "citation_checks": {variant["blind_label"]: {"supported": None, "total": None} for variant in case["variants"]},
                "unsupported_claims": {variant["blind_label"]: None for variant in case["variants"]},
                "preferred": "",
                "notes": "",
            }
            for case in result["cases"]
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行单模型与 Council 的可重复盲评基准")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals" / "council_benchmark_v1.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evals" / "results")
    parser.add_argument("--provider-id", default="mock")
    parser.add_argument("--model", default="")
    parser.add_argument("--strategies", default=",".join(STRATEGIES))
    parser.add_argument("--case", action="append", help="只运行指定案例，可重复")
    parser.add_argument("--case-timeout", type=int, default=900)
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 11), help="每个案例和策略重复次数（默认 3）")
    parser.add_argument("--confirm-cost", action="store_true", help="确认真实 Provider 调用可能产生费用")
    parser.add_argument("--pricing", type=Path, help="可选 Token 单价 JSON，用于估算成本")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(execute(args))
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    slug = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = args.output_dir / f"benchmark-{slug}"
    stem.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(f"{stem}-blind.md").write_text(blind_markdown(result), encoding="utf-8")
    Path(f"{stem}-reviews.json").write_text(json.dumps(review_template(result), ensure_ascii=False, indent=2), encoding="utf-8")
    key = {
        case["id"]: {
            variant["blind_label"]: {"strategy": variant["strategy"], "repetition": variant["repetition"]}
            for variant in case["variants"]
        }
        for case in result["cases"]
    }
    Path(f"{stem}-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(stem.with_suffix(".json"))
    print(f"执行数据已记录；质量分仍为空。先完成 {stem}-blind.md，再填写 {stem}-reviews.json。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
