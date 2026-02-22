"""
Pytest configuration for the `web-form-verbrauch` test suite.

We keep tests importing `backend...` normally (no importlib file loaders).
To make that work in a fresh checkout without requiring an editable install,
we add the local `backend/src` directory to `sys.path`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure() -> None:
    """
    Ensure local `backend` package is importable for tests.

    This is intentionally minimal and only affects the test runtime.
    """

    web_form_root = Path(__file__).resolve().parent.parent  # .../web-form-verbrauch
    backend_src = web_form_root / "backend" / "src"

    if backend_src.is_dir():
        # Prepend so local sources win over any globally installed package.
        sys.path.insert(0, str(backend_src))
