from __future__ import annotations

import multiprocessing

import uvicorn

from app.main import app


def main() -> None:
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
