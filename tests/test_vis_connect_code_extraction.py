"""
Unit tests for authorization-code extraction in `vis-connect/python-auth/auth.py`.

No network calls are performed. We validate extraction from:
- Redirect Location header (preferred)
- Final URL
- Response body fallback regex (code=...)
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest


def _load_vis_connect_auth_module():
    """
    Load the CLI module by file path because `vis-connect/` is not importable.
    """
    repo_root = Path(__file__).resolve().parents[1]  # web-form-verbrauch/
    auth_path = repo_root / "vis-connect" / "python-auth" / "auth.py"
    spec = importlib.util.spec_from_file_location("vis_connect_python_auth", auth_path)
    assert spec and spec.loader, f"Failed to create import spec for {auth_path}"
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so dataclasses (with postponed annotations)
    # can resolve cls.__module__ reliably on Python 3.12+.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


@pytest.fixture(scope="session")
def vis_auth():
    return _load_vis_connect_auth_module()


@dataclass
class FakeResponse:
    """
    Minimal duck-typed stand-in for `requests.Response`.

    `extract_authorization_code()` only reads `.headers`, `.url`, and `.text`.
    """

    headers: dict = field(default_factory=dict)
    url: str = ""
    text: str = ""


def test_extracts_code_from_location_header_preferred(vis_auth) -> None:
    resp = FakeResponse(
        headers={"Location": "http://localhost:4200/?code=from_location&state=xyz"},
        url="http://localhost:4200/?code=from_url",
        text="code=from_body",
    )
    assert vis_auth.extract_authorization_code(response=resp) == "from_location"


def test_extracts_code_from_lowercase_location_header(vis_auth) -> None:
    resp = FakeResponse(headers={"location": "http://localhost:4200/?code=abc123"})
    assert vis_auth.extract_authorization_code(response=resp) == "abc123"


def test_extracts_code_from_final_url_when_no_location(vis_auth) -> None:
    resp = FakeResponse(url="http://localhost:4200/cb?foo=1&code=from_url&bar=2")
    assert vis_auth.extract_authorization_code(response=resp) == "from_url"


def test_extracts_code_from_body_fallback_stops_at_quote(vis_auth) -> None:
    # Similar to legacy PHP: code=(.*)"
    resp = FakeResponse(text='<a href="http://localhost:4200/?code=from_body">continue</a>')
    assert vis_auth.extract_authorization_code(response=resp) == "from_body"


def test_extracts_code_from_body_fallback_stops_at_ampersand(vis_auth) -> None:
    resp = FakeResponse(text="... code=from_body&state=zzz ...")
    assert vis_auth.extract_authorization_code(response=resp) == "from_body"


def test_raises_cli_error_when_code_missing(vis_auth) -> None:
    resp = FakeResponse(headers={}, url="http://localhost:4200/?nope=1", text="no code here")
    with pytest.raises(vis_auth.CliError):
        vis_auth.extract_authorization_code(response=resp)

