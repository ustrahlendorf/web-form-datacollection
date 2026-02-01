"""
Unit tests for PKCE helper functions in `vis-connect/python-auth/auth.py`.

These tests are intentionally offline (no network calls).
They validate deterministic S256 computation and basic verifier invariants.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_vis_connect_auth_module():
    """
    Load the CLI module by file path.

    The directory name `vis-connect/` contains a hyphen, so it is not a valid
    Python package import path. For tests we load the module directly.
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


def test_pkce_s256_matches_rfc7636_example(vis_auth) -> None:
    """
    RFC 7636 (PKCE) includes a well-known example:

    code_verifier:
      dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk
    code_challenge (S256):
      E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM
    """
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

    assert vis_auth.code_challenge_s256(verifier) == expected


def test_pkce_plain_is_identity(vis_auth) -> None:
    verifier = "any-verifier-string"
    assert vis_auth.code_challenge_plain(verifier) == verifier


def test_generate_code_verifier_enforces_length_range(vis_auth) -> None:
    """
    RFC 7636 requires 43..128 chars for the verifier.
    """
    with pytest.raises(ValueError):
        vis_auth.generate_code_verifier(42)
    with pytest.raises(ValueError):
        vis_auth.generate_code_verifier(129)


def test_generate_code_verifier_returns_requested_length(vis_auth) -> None:
    """
    The verifier is random, but should respect requested length and be ASCII.
    """
    v = vis_auth.generate_code_verifier(64)
    assert isinstance(v, str)
    assert len(v) == 64
    v.encode("ascii")  # should not raise

