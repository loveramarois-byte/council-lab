from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Council"


def data_dir() -> Path:
    override = os.getenv("COUNCIL_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME / "data"
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / APP_NAME / "data"
    root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "council" / "data"


def database_path() -> Path:
    return data_dir() / "council.sqlite3"
