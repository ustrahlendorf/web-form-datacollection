"""
Unit tests for token refresh and cache logic.

Tests refresh_access_token, load_token_cache, save_token_cache, and get_valid_token.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import backend.api_auth.auth as auth_mod
import backend.iot_data.get_iot_config as get_iot_mod


def _make_json_response(payload: dict, *, status_code: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(payload).encode("utf-8")  # noqa: SLF001
    resp.encoding = "utf-8"
    resp.url = "https://example.invalid/token"
    return resp


def _make_redirect_response(*, location: str, status_code: int = 302) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.headers["Location"] = location
    resp.url = "https://iam.viessmann.com/idp/v3/authorize"
    resp._content = b""  # noqa: SLF001
    return resp


def test_refresh_access_token_returns_token_response() -> None:
    """refresh_access_token returns TokenResponse with access_token, refresh_token, expires_in."""
    session = Mock()
    session.post.return_value = _make_json_response(
        {
            "access_token": "NEW_ACCESS_TOKEN",
            "refresh_token": "NEW_REFRESH_TOKEN",
            "expires_in": 1800,
        },
        status_code=200,
    )

    cfg = auth_mod.Config(
        client_id="client-id",
        email="user@example.com",
        password="pw",
        callback_uri="http://localhost:4200/",
        scope="IoT User",
        timeout_seconds=5.0,
        ssl_verify=True,
        pkce_method="S256",
        code_verifier="verifier",
    )
    log = logging.LoggerAdapter(logging.getLogger("test"), {})

    result = auth_mod.refresh_access_token(
        session=session,
        cfg=cfg,
        refresh_token="OLD_REFRESH_TOKEN",
        log=log,
    )

    assert result.access_token == "NEW_ACCESS_TOKEN"
    assert result.refresh_token == "NEW_REFRESH_TOKEN"
    assert result.expires_in == 1800

    # Verify POST was called with correct params
    call_args = session.post.call_args
    assert call_args[0][0] == auth_mod.TOKEN_URL
    params = call_args[1].get("params") or {}
    assert params.get("grant_type") == "refresh_token"
    assert params.get("refresh_token") == "OLD_REFRESH_TOKEN"
    assert params.get("client_id") == "client-id"


def test_load_token_cache_returns_none_when_file_missing(tmp_path: Path) -> None:
    """load_token_cache returns None when file does not exist."""
    result = get_iot_mod.load_token_cache(tmp_path / "nonexistent.json")
    assert result is None


def test_load_token_cache_returns_none_when_invalid(tmp_path: Path) -> None:
    """load_token_cache returns None when file is invalid JSON or missing required keys."""
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("not json")
    assert get_iot_mod.load_token_cache(invalid_file) is None

    invalid_file.write_text('{"foo": "bar"}')  # missing access_token, expires_at
    assert get_iot_mod.load_token_cache(invalid_file) is None


def test_save_and_load_token_cache_roundtrip(tmp_path: Path) -> None:
    """save_token_cache and load_token_cache roundtrip correctly."""
    cache_path = tmp_path / "tokens.json"
    data = {
        "access_token": "at",
        "refresh_token": "rt",
        "expires_at": int(time.time()) + 3600,
        "installation_id": "inst-1",
        "gateway_serial": "gw-1",
        "device_id": "dev-1",
    }

    get_iot_mod.save_token_cache(cache_path, data)
    loaded = get_iot_mod.load_token_cache(cache_path)

    assert loaded == data
    assert cache_path.stat().st_mode & 0o777 == 0o600


def test_get_valid_token_uses_cache_when_valid(tmp_path: Path, monkeypatch) -> None:
    """get_valid_token returns cached token when not expired."""
    monkeypatch.setenv("VIESSMANN_CLIENT_ID", "client-id")
    monkeypatch.setenv("VIESSMANN_EMAIL", "user@example.com")
    monkeypatch.setenv("VIESSMANN_PASSWORD", "pw")
    monkeypatch.setenv("VIESSMANN_CALLBACK_URI", "http://localhost:4200/")

    cache_path = tmp_path / "tokens.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    cache_path.write_text(
        json.dumps(
            {
                "access_token": "CACHED_TOKEN",
                "refresh_token": "CACHED_REFRESH",
                "expires_at": now + 3600,  # valid for 1h
                "installation_id": "inst-1",
                "gateway_serial": "gw-1",
                "device_id": "dev-1",
            }
        )
    )
    cache_path.chmod(0o600)

    args = get_iot_mod._build_auth_args(
        timeout_seconds=30.0,
        ssl_verify=True,
        token_cache_disabled=False,
    )
    cfg = auth_mod.load_config(args, log=logging.LoggerAdapter(logging.getLogger("test"), {}))
    session = Mock()

    access_token, refresh_token, inst_id, gw_serial, dev_id, expires_at = get_iot_mod.get_valid_token(
        session=session,
        cfg=cfg,
        log=logging.LoggerAdapter(logging.getLogger("test"), {}),
        auth_mod=auth_mod,
        cache_path=cache_path,
    )

    assert access_token == "CACHED_TOKEN"
    assert inst_id == "inst-1"
    assert gw_serial == "gw-1"
    assert dev_id == "dev-1"
    # No network calls
    session.post.assert_not_called()
    session.get.assert_not_called()


def test_get_valid_token_refreshes_when_expired(tmp_path: Path, monkeypatch) -> None:
    """get_valid_token calls refresh_access_token when cached token is expired."""
    monkeypatch.setenv("VIESSMANN_CLIENT_ID", "client-id")
    monkeypatch.setenv("VIESSMANN_EMAIL", "user@example.com")
    monkeypatch.setenv("VIESSMANN_PASSWORD", "pw")
    monkeypatch.setenv("VIESSMANN_CALLBACK_URI", "http://localhost:4200/")

    cache_path = tmp_path / "tokens.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    cache_path.write_text(
        json.dumps(
            {
                "access_token": "EXPIRED_TOKEN",
                "refresh_token": "VALID_REFRESH",
                "expires_at": now - 100,  # expired
                "installation_id": "inst-1",
                "gateway_serial": "gw-1",
                "device_id": "dev-1",
            }
        )
    )
    cache_path.chmod(0o600)

    session = Mock()
    session.post.return_value = _make_json_response(
        {
            "access_token": "REFRESHED_TOKEN",
            "refresh_token": "NEW_REFRESH",
            "expires_in": 1800,
        },
        status_code=200,
    )

    args = get_iot_mod._build_auth_args(
        timeout_seconds=30.0,
        ssl_verify=True,
        token_cache_disabled=False,
    )
    cfg = auth_mod.load_config(args, log=logging.LoggerAdapter(logging.getLogger("test"), {}))

    access_token, refresh_token, inst_id, gw_serial, dev_id, expires_at = get_iot_mod.get_valid_token(
        session=session,
        cfg=cfg,
        log=logging.LoggerAdapter(logging.getLogger("test"), {}),
        auth_mod=auth_mod,
        cache_path=cache_path,
    )

    assert access_token == "REFRESHED_TOKEN"
    assert inst_id == "inst-1"
    assert gw_serial == "gw-1"
    assert dev_id == "dev-1"
    # One POST for refresh
    assert session.post.call_count == 1
    params = session.post.call_args[1].get("params") or {}
    assert params.get("grant_type") == "refresh_token"

    # Cache should be updated
    loaded = get_iot_mod.load_token_cache(cache_path)
    assert loaded["access_token"] == "REFRESHED_TOKEN"


def test_get_valid_token_full_oauth_when_no_cache(tmp_path: Path, monkeypatch) -> None:
    """get_valid_token runs full OAuth when cache_path is None."""
    monkeypatch.setenv("VIESSMANN_CLIENT_ID", "client-id")
    monkeypatch.setenv("VIESSMANN_EMAIL", "user@example.com")
    monkeypatch.setenv("VIESSMANN_PASSWORD", "pw")
    monkeypatch.setenv("VIESSMANN_CALLBACK_URI", "http://localhost:4200/")

    session = Mock()
    session.post.side_effect = [
        _make_redirect_response(location="http://localhost:4200/?code=auth-code"),
        _make_json_response(
            {"access_token": "NEW_TOKEN", "refresh_token": "NEW_REFRESH", "expires_in": 3600},
            status_code=200,
        ),
    ]
    session.get.return_value = _make_json_response({"data": [{"id": "inst-1"}]})

    args = get_iot_mod._build_auth_args(
        timeout_seconds=30.0,
        ssl_verify=True,
        token_cache_disabled=True,
    )
    cfg = auth_mod.load_config(args, log=logging.LoggerAdapter(logging.getLogger("test"), {}))

    access_token, refresh_token, inst_id, gw_serial, dev_id, expires_at = get_iot_mod.get_valid_token(
        session=session,
        cfg=cfg,
        log=logging.LoggerAdapter(logging.getLogger("test"), {}),
        auth_mod=auth_mod,
        cache_path=None,
    )

    assert access_token == "NEW_TOKEN"
    assert refresh_token == "NEW_REFRESH"
    assert inst_id is None
    assert gw_serial is None
    assert dev_id is None
    assert session.post.call_count == 2  # authorize + token exchange
