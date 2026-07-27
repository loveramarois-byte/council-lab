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
        aggregate[strategy] = {
            "cases": len(rows),
            "completed": len(completed),
            "failures": len(rows) - len(completed),
            "failure_rate": round((len(rows) - len(completed)) / len(rows), 4) if rows else 0,
            "model_calls": sum(int(row.get("model_calls", 0)) for row in rows),
            "input_tokens": sum(int(row.get("input_tokens", 0)) for row in rows),
            "output_tokens": sum(int(row.get("output_tokens", 0)) for row in rows),
            "duration_ms": sum(int(row.get("duration_ms", 0)) for row in rows),
        }
    return aggregate


def summarize_human_reviews(result: dict[str, Any], reviews: dict[str, Any]) -> dict[str, Any]:
    if reviews.get("run_id") != result.get("run_id"):
        raise ValueError("盲评文件与结果 run_id 不一致")
    case_lookup = {case["id"]: case for case in result.get("cases", [])}
    totals = {strategy: {field: [] for field in SCORE_FIELDS} for strategy in STRATEGIES}
    preferences = {strategy: 0 for strategy in STRATEGIES}
    reviewed_cases = 0
    for review in reviews.get("reviews", []):
        case = case_lookup.get(review.get("case_id"))
        if not case:
            raise ValueError(f"盲评包含未知案例：{review.get('case_id')}")
        label_to_strategy = {variant["blind_label"]: variant["strategy"] for variant in case.get("variants", [])}
        for label, scores in review.get("scores", {}).items():
            strategy = label_to_strategy.get(label)
            if not strategy:
                raise ValueError(f"案例 {case['id']} 包含未知匿名标签：{label}")
            for field in SCORE_FIELDS:
                value = scores.get(field)
                if not isinstance(value, (int, float)) or not 1 <= value <= 5:
                    raise ValueError(f"案例 {case['id']} 的 {label}.{field} 必须为 1-5")
                totals[strategy][field].append(float(value))
        preferred = review.get("preferred")
        if preferred:
            strategy = label_to_strategy.get(preferred)
            if not strategy:
                raise ValueError(f"案例 {case['id']} 的偏好标签无效")
            preferences[strategy] += 1
        reviewed_cases += 1
    quality = {}
    for strategy, fields in totals.items():
        quality[strategy] = {
            **{field: round(sum(values) / len(values), 3) if values else None for field, values in fields.items()},
            "preferred_cases": preferences[strategy],
        }
    return {
        "schema_version": 1,
        "benchmark_version": result.get("benchmark_version"),
        "run_id": result.get("run_id"),
        "quality_scored": reviewed_cases > 0,
        "reviewed_cases": reviewed_cases,
        "quality": quality,
        "execution": aggregate_execution(result.get("cases", [])),
        "quality_claims_allowed": bool(result.get("quality_claims_allowed") and reviewed_cases > 0),
    }
