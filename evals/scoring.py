from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


STRATEGIES = ("direct", "same_model_council", "cross_model_council")
SCORE_FIELDS = ("accuracy", "evidence_use", "critical_coverage", "actionability", "uncertainty")


def load_dataset(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_dataset(payload)
    return payload


def validate_dataset(payload: dict[str, Any]) -> None:
    if payload.get("version") != "council-benchmark-v1":
        raise ValueError("评测集版本必须是 council-benchmark-v1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 12:
        raise ValueError("评测集至少需要 12 个案例")
    ids = [case.get("id") for case in cases]
    if len(set(ids)) != len(ids) or any(not value for value in ids):
        raise ValueError("评测案例 ID 必须存在且唯一")
    categories = {case.get("category") for case in cases}
    required = {"decision", "fact_check", "risk", "planning"}
    if not required.issubset(categories):
        raise ValueError("评测集必须覆盖 decision、fact_check、risk、planning")
    for case in cases:
        if not case.get("prompt") or not case.get("reference_points"):
            raise ValueError(f"案例 {case.get('id')} 缺少问题或参考要点")
        if not isinstance(case.get("materials", []), list):
            raise ValueError(f"案例 {case.get('id')} 的 materials 必须是列表")


def blind_labels(run_id: str, case_id: str, strategies: list[str]) -> dict[str, str]:
    ordered = sorted(
        strategies,
        key=lambda strategy: hashlib.sha256(f"{run_id}:{case_id}:{strategy}".encode()).hexdigest(),
    )
    return {strategy: chr(65 + index) for index, strategy in enumerate(ordered)}


def aggregate_execution(cases: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    aggregate: dict[str, dict[str, float | int]] = {}
    for strategy in STRATEGIES:
        rows = [variant for case in cases for variant in case.get("variants", []) if variant.get("strategy") == strategy]
        completed = [row for row in rows if row.get("status") == "completed"]
        priced = [float(row["estimated_cost"]) for row in completed if row.get("estimated_cost") is not None]
        aggregate[strategy] = {
            "cases": len(rows),
            "completed": len(completed),
            "failures": len(rows) - len(completed),
            "failure_rate": round((len(rows) - len(completed)) / len(rows), 4) if rows else 0,
            "model_calls": sum(int(row.get("model_calls", 0)) for row in rows),
            "input_tokens": sum(int(row.get("input_tokens", 0)) for row in rows),
            "output_tokens": sum(int(row.get("output_tokens", 0)) for row in rows),
            "duration_ms": sum(int(row.get("duration_ms", 0)) for row in rows),
            "estimated_cost": round(sum(priced), 6) if completed and len(priced) == len(completed) else None,
            "cost_coverage": round(len(priced) / len(completed), 4) if completed else 0,
        }
    return aggregate


def summarize_human_reviews(result: dict[str, Any], reviews: dict[str, Any]) -> dict[str, Any]:
    if reviews.get("run_id") != result.get("run_id"):
        raise ValueError("盲评文件与结果 run_id 不一致")
    case_lookup = {case["id"]: case for case in result.get("cases", [])}
    totals = {strategy: {field: [] for field in SCORE_FIELDS} for strategy in STRATEGIES}
    preferences = {strategy: 0 for strategy in STRATEGIES}
    citation_totals = {strategy: {"supported": 0, "total": 0, "reported": False} for strategy in STRATEGIES}
    unsupported_claims = {strategy: {"count": 0, "reported": False} for strategy in STRATEGIES}
    reviewed_case_ids: set[str] = set()
    complete_score_sets = True
    complete_review_metrics = True
    for review in reviews.get("reviews", []):
        case = case_lookup.get(review.get("case_id"))
        if not case:
            raise ValueError(f"盲评包含未知案例：{review.get('case_id')}")
        if case["id"] in reviewed_case_ids:
            raise ValueError(f"案例 {case['id']} 被重复评审")
        reviewed_case_ids.add(case["id"])
        label_to_strategy = {variant["blind_label"]: variant["strategy"] for variant in case.get("variants", [])}
        if set(review.get("scores", {})) != set(label_to_strategy):
            complete_score_sets = False
        if set(review.get("citation_checks", {})) != set(label_to_strategy):
            complete_review_metrics = False
        if set(review.get("unsupported_claims", {})) != set(label_to_strategy):
            complete_review_metrics = False
        for label, scores in review.get("scores", {}).items():
            strategy = label_to_strategy.get(label)
            if not strategy:
                raise ValueError(f"案例 {case['id']} 包含未知匿名标签：{label}")
            for field in SCORE_FIELDS:
                value = scores.get(field)
                if not isinstance(value, (int, float)) or not 1 <= value <= 5:
                    raise ValueError(f"案例 {case['id']} 的 {label}.{field} 必须为 1-5")
                totals[strategy][field].append(float(value))
        for label, checks in review.get("citation_checks", {}).items():
            strategy = label_to_strategy.get(label)
            if not strategy:
                raise ValueError(f"案例 {case['id']} 包含未知引用标签：{label}")
            supported = checks.get("supported") if isinstance(checks, dict) else None
            total = checks.get("total") if isinstance(checks, dict) else None
            if supported is None and total is None:
                complete_review_metrics = False
                continue
            if not isinstance(supported, int) or not isinstance(total, int) or supported < 0 or total < 0 or supported > total:
                raise ValueError(f"案例 {case['id']} 的 {label} 引用计数无效")
            citation_totals[strategy]["supported"] += supported
            citation_totals[strategy]["total"] += total
            citation_totals[strategy]["reported"] = True
        for label, count in review.get("unsupported_claims", {}).items():
            strategy = label_to_strategy.get(label)
            if not strategy:
                raise ValueError(f"案例 {case['id']} 包含未知主张标签：{label}")
            if count is None:
                complete_review_metrics = False
                continue
            if not isinstance(count, int) or count < 0:
                raise ValueError(f"案例 {case['id']} 的 {label} 未经支持主张数量无效")
            unsupported_claims[strategy]["count"] += count
            unsupported_claims[strategy]["reported"] = True
        preferred = review.get("preferred")
        if preferred:
            strategy = label_to_strategy.get(preferred)
            if not strategy:
                raise ValueError(f"案例 {case['id']} 的偏好标签无效")
            preferences[strategy] += 1
        else:
            complete_review_metrics = False
    reviewed_cases = len(reviewed_case_ids)
    quality = {}
    for strategy, fields in totals.items():
        quality[strategy] = {
            **{field: round(sum(values) / len(values), 3) if values else None for field, values in fields.items()},
            "preferred_cases": preferences[strategy],
            "citation_accuracy": (
                round(citation_totals[strategy]["supported"] / citation_totals[strategy]["total"], 4)
                if citation_totals[strategy]["reported"] and citation_totals[strategy]["total"]
                else None
            ),
            "citation_checks": citation_totals[strategy]["total"] if citation_totals[strategy]["reported"] else None,
            "unsupported_claims": unsupported_claims[strategy]["count"] if unsupported_claims[strategy]["reported"] else None,
        }
    all_variants_completed = bool(case_lookup) and all(
        {variant.get("strategy") for variant in case.get("variants", [])} == set(STRATEGIES)
        and all(variant.get("status") == "completed" and str(variant.get("answer", "")).strip() for variant in case.get("variants", []))
        for case in case_lookup.values()
    )
    complete_blind_review = (
        bool(case_lookup)
        and reviewed_case_ids == set(case_lookup)
        and complete_score_sets
        and complete_review_metrics
        and all_variants_completed
    )
    return {
        "schema_version": 1,
        "benchmark_version": result.get("benchmark_version"),
        "run_id": result.get("run_id"),
        "quality_scored": reviewed_cases > 0,
        "reviewed_cases": reviewed_cases,
        "all_variants_completed": all_variants_completed,
        "complete_review_metrics": complete_review_metrics,
        "complete_blind_review": complete_blind_review,
        "quality": quality,
        "execution": aggregate_execution(result.get("cases", [])),
        "quality_claims_allowed": bool(result.get("quality_claims_allowed") and complete_blind_review),
    }
