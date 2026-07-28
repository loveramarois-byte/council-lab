#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def read_text(root: Path, relative_path: str, errors: list[str]) -> str:
    path = root / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{relative_path}: cannot read file ({exc})")
        return ""


def check(root: Path) -> list[str]:
    errors: list[str] = []
    version = read_text(root, "VERSION", errors).strip()
    if not SEMVER.fullmatch(version):
        errors.append(f"VERSION: expected semantic version, got {version!r}")

    for relative_path in ("frontend/package.json", "frontend/package-lock.json"):
        raw = read_text(root, relative_path, errors)
        if not raw:
            continue
        try:
            package_version = json.loads(raw).get("version")
        except json.JSONDecodeError as exc:
            errors.append(f"{relative_path}: invalid JSON ({exc})")
            continue
        if package_version != version:
            errors.append(f"{relative_path}: version {package_version!r} does not match VERSION {version!r}")

    documents = {
        "README.md": rf"当前版本为 `{re.escape(version)}`",
        "README.en.md": rf"Version `{re.escape(version)}`",
        "CHANGELOG.md": rf"^## \[{re.escape(version)}\]",
    }
    for relative_path, pattern in documents.items():
        content = read_text(root, relative_path, errors)
        if content and not re.search(pattern, content, re.MULTILINE):
            errors.append(f"{relative_path}: does not declare current version {version}")

    updater = read_text(root, "backend/app/updater.py", errors)
    if updater and not ("def current_version" in updater and '/ "VERSION"' in updater):
        errors.append("backend/app/updater.py: packaged version must be read from a VERSION file")

    architecture = read_text(root, "docs/ARCHITECTURE.md", errors)
    for marker in (
        "## Feature status",
        "Run event replay",
        "Mobile access",
        "Legacy workspace",
    ):
        if architecture and marker not in architecture:
            errors.append(f"docs/ARCHITECTURE.md: missing feature-status marker {marker!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check release version and feature-document consistency.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = check(args.root.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    version = (args.root / "VERSION").read_text(encoding="utf-8").strip()
    print(f"release consistency: {version} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
