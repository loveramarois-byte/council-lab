#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
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
from app.provider_catalog import CATALOG_FIELDS, builtin_providers  # noqa: E402
from app.providers import build_backend  # noqa: E402
from app.store import Store  # noqa: E402
from evals.scoring import STRATEGIES, aggregate_execution, blind_labels, load_dataset  # noqa: E402


def load_runtime() -> tuple[dict[str, ProviderProfile], AgentAssignmentsConfig | None]:
    store = Store(database_path())
    providers = builtin_providers()
    for saved in store.load_providers():
        if saved.id == "mock":
            continue
        catalog = providers.get(saved.id)
        if catalog:
            for field in CATALOG_FIELDS:
                setattr(saved, field, getattr(catalog, field))
            saved.api_key_reference = saved.api_key_reference or catalog.api_key_reference
            saved.requires_api_key = catalog.requires_api_key
            if not saved.available_models:
                saved.available_models = catalog.available_models
        providers[saved.id] = saved
    assignments = store.load_assignment_config()
    store.close()
    return providers, assignments


def evidence_snapshots(case: dict[str, Any]) -> list[RunSourceSnapshot]:
    return [
        RunSourceSnapshot(
            id=f"{case['id']}-source-{index}",
            kind="text",
            title=material["title"],
            excerpt=material["content"],
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
            {"role": assignment.role, "provider": assignment.provider_name, "model": assignment.model}
            for assignment in [*current.seat_assignments, current.finalizer_assignment]
            if assignment
        ]
        return {
            "status": "completed",
            "answer": current.final_decision.final_answer,
            "model_calls": current.usage.model_calls,
            "input_tokens": current.usage.input_tokens,
            "output_tokens": current.usage.output_tokens,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "providers": providers,
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
        cross_config = ensure_cross_model(saved_config) if "cross_model_council" in strategies else None
        await helper.shutdown()

        profile_ids = {profile.id}
        if cross_config:
            profile_ids.update(item.provider_id for item in [*cross_config.seats, cross_config.finalizer])
        uses_real_provider = any(profiles[item].provider_type != ProviderType.MOCK for item in profile_ids)
        planned_calls = len(cases) * sum(1 if strategy == "direct" else 5 for strategy in strategies)
        if uses_real_provider and not args.confirm_cost:
            raise ValueError(
                f"本次最多会发起 {planned_calls} 次真实模型请求。确认费用后重新运行并添加 --confirm-cost。"
            )

        run_id = str(uuid.uuid4())
        result_cases = []
        for case in cases:
            labels = blind_labels(run_id, case["id"], strategies)
            variants = []
            for strategy in strategies:
                try:
                    if strategy == "direct":
                        outcome = await asyncio.wait_for(run_direct(case, profile, model), timeout=args.case_timeout)
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
                    }
                variants.append({"strategy": strategy, "blind_label": labels[strategy], **outcome})
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
        "quality_scored": False,
        "quality_claims_allowed": uses_real_provider,
        "mock_workflow_only": not uses_real_provider,
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
        lines.extend(["评分：A / B / C（按实际答案数量填写）；偏好：____；备注：____", "", "---", ""])
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
    parser.add_argument("--confirm-cost", action="store_true", help="确认真实 Provider 调用可能产生费用")
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
        case["id"]: {variant["blind_label"]: variant["strategy"] for variant in case["variants"]}
        for case in result["cases"]
    }
    Path(f"{stem}-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(stem.with_suffix(".json"))
    print(f"执行数据已记录；质量分仍为空。先完成 {stem}-blind.md，再填写 {stem}-reviews.json。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
