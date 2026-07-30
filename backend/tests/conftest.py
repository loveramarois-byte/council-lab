from __future__ import annotations

import os


TEST_INTERNAL_API_TOKEN = "council-test-internal-token-32-bytes"
os.environ["COUNCIL_INTERNAL_API_TOKEN"] = TEST_INTERNAL_API_TOKEN


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "security_boundary: browser-to-loopback request-boundary regression",
    )
