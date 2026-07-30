#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
from pathlib import Path


INSTALL_NOTES = """## 安装与升级

- macOS：下载 macOS ZIP，解压后双击 `Council.app`。
- Windows：下载 Windows ZIP，完整解压后双击 `Start Council.cmd`。
- 手机端：电脑启动后打开“设置 → 手机连接”，在同一可信 Wi-Fi 下扫码配对。
- 两个安装包均内置运行环境，不需要另行安装 Python 或 Node.js。
- 当前开源构建未做 Apple notarization 或 Windows 商业代码签名，请仅从本仓库 Release 下载。
"""


def release_section(changelog: str, version: str) -> str:
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(changelog)
    if not match:
        raise ValueError(f"CHANGELOG.md does not contain a {version} release section")
    return f"## Council v{version} 更新内容\n\n{match.group('body').strip()}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build detailed GitHub Release notes from CHANGELOG.md.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    version = (args.root / "VERSION").read_text(encoding="utf-8").strip()
    changelog = (args.root / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = f"{release_section(changelog, version)}\n{INSTALL_NOTES}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(notes, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
