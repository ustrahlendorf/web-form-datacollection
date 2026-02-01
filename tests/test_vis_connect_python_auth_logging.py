import importlib.util
import json
import logging
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests


@pytest.fixture(scope="module")
def auth_module():
    """
    Load the CLI script as a module (path contains hyphens, so normal import won't work).
    """
    auth_path = Path(__file__).resolve().parent.parent / "vis-connect/python-auth/auth.py"
    spec = importlib.util.spec_from_file_location("vis_connect_python_auth_script", auth_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register module so dataclasses can resolve string annotations (Py 3.12+).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_json_response(payload: dict, *, status_code: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(payload).encode("utf-8")  # noqa: SLF001 - requests.Response test helper
    resp.encoding = "utf-8"
    resp.url = "https://example.invalid/token"
    return resp


def test_sanitize_obj_redacts_tokens_deep(auth_module) -> None:
    raw = {
        "access_token": "ACCESS_TOKEN_SHOULD_NOT_LEAK",
        "refresh_token": "REFRESH_TOKEN_SHOULD_NOT_LEAK",
        "nested": {
            "id_token": "ID_TOKEN_SHOULD_NOT_LEAK",
            "ok": 123,
        },
        "list": [{"access_token": "X"}],
    }

    sanitized = auth_module._sanitize_obj(raw)

    assert sanitized["access_token"] == "<redacted>"
    assert sanitized["refresh_token"] == "<redacted>"
    assert sanitized["nested"]["id_token"] == "<redacted>"
    assert sanitized["nested"]["ok"] == 123
    assert sanitized["list"][0]["access_token"] == "<redacted>"


def test_exchange_code_for_token_logs_sanitized_response(auth_module, caplog) -> None:
    # Arrange
    session = Mock()
    session.post.return_value = _make_json_response(
        {
            "access_token": "ACCESS_TOKEN_SHOULD_NOT_APPEAR_IN_LOGS",
            "refresh_token": "REFRESH_TOKEN_SHOULD_NOT_APPEAR_IN_LOGS",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
        status_code=200,
    )

    cfg = auth_module.Config(
        client_id="client-id",
        email="user@example.com",
        password="password",
        callback_uri="http://localhost:4200/",
        scope="IoT User",
        timeout_seconds=5.0,
        ssl_verify=True,
        pkce_method="S256",
        code_verifier="code-verifier",
    )

    log = logging.LoggerAdapter(logging.getLogger("vis_connect.python_auth.test"), {})
    caplog.set_level(logging.DEBUG)

    # Act
    token = auth_module.exchange_code_for_token(session=session, cfg=cfg, code="auth-code", log=log)

    # Assert: function returns the actual token value, but logs must not contain it.
    assert token == "ACCESS_TOKEN_SHOULD_NOT_APPEAR_IN_LOGS"
    assert "ACCESS_TOKEN_SHOULD_NOT_APPEAR_IN_LOGS" not in caplog.text
    assert "REFRESH_TOKEN_SHOULD_NOT_APPEAR_IN_LOGS" not in caplog.text

