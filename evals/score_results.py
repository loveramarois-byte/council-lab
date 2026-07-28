#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.scoring import SCORE_FIELDS, STRATEGIES, summarize_human_reviews


LABELS = {
    "direct": "单模型直接回答",
    "extended_direct": "单模型加强直接回答",
    "self_refine": "单模型自我修正",
    "same_model_council": "同模型四角色审议",
    "cross_model_council": "跨模型四席审议",
}


def markdown(summary: dict) -> str:
    lines = [
        "# Council Benchmark v1 · 评测摘要",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- 已盲评案例：{summary['reviewed_cases']}",
        f"- 允许质量结论：{'是' if summary['quality_claims_allowed'] else '否'}",
        "",
        "| 方案 | 完成/总数 | 失败率 | 调用 | Token | 估算成本 | 引用支持率 | 未支持主张 | 人类偏好 | 五项均分 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for strategy in STRATEGIES:
        execution = summary["execution"][strategy]
        quality = summary["quality"][strategy]
        values = [quality[field] for field in SCORE_FIELDS if quality[field] is not None]
        average = round(sum(values) / len(values), 3) if values else "—"
        tokens = execution["input_tokens"] + execution["output_tokens"]
        estimated_cost = f"${execution['estimated_cost']:.4f}" if execution.get("estimated_cost") is not None else "—"
        citation_accuracy = f"{quality['citation_accuracy']:.1%}" if quality.get("citation_accuracy") is not None else "—"
        unsupported = quality.get("unsupported_claims") if quality.get("unsupported_claims") is not None else "—"
        lines.append(
            f"| {LABELS[strategy]} | {execution['completed']}/{execution['cases']} | "
            f"{execution['failure_rate']:.1%} | {execution['model_calls']} | {tokens} | "
            f"{estimated_cost} | {citation_accuracy} | {unsupported} | {quality['preferred_cases']} | {average} |"
        )
    if not summary["quality_claims_allowed"]:
        lines.extend(["", "> 本次包含 Mock 或尚未完成有效盲评，不能据此宣称某种方案质量更高。"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总已完成的人类盲评")
    parser.add_argument("result", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    reviews = json.loads(args.reviews.read_text(encoding="utf-8"))
    summary = summarize_human_reviews(result, reviews)
    output = args.output or args.result.with_name(f"{args.result.stem}-summary.json")
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    output.with_suffix(".md").write_text(markdown(summary), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
