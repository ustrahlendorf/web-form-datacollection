"""
Pytest configuration for the `web-form-verbrauch` test suite.

We keep tests importing `vis_connect...` normally (no importlib file loaders).
To make that work in a fresh checkout without requiring an editable install,
we add the local `vis-connect/src` directory to `sys.path`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure() -> None:
    """
    Ensure local `vis_connect` package is importable for tests.

    This is intentionally minimal and only affects the test runtime.
    """

    web_form_root = Path(__file__).resolve().parent.parent  # .../web-form-verbrauch
    vis_connect_src = web_form_root / "vis-connect" / "src"

    if vis_connect_src.is_dir():
        # Prepend so local sources win over any globally installed package.
        sys.path.insert(0, str(vis_connect_src))
