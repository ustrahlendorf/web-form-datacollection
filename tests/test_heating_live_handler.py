"""Tests for the heating live Lambda handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.handlers import heating_live_handler as mod


def test_extract_user_id_success() -> None:
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": "user-123"}},
            },
        },
    }
    assert mod.extract_user_id(event) == "user-123"


def test_extract_user_id_legacy_claims() -> None:
    event = {
        "requestContext": {
            "authorizer": {"claims": {"sub": "user-456"}},
        },
    }
    assert mod.extract_user_id(event) == "user-456"


def test_extract_user_id_missing_raises() -> None:
    event = {"requestContext": {"authorizer": {"claims": {}}}}
    with pytest.raises(KeyError):
        mod.extract_user_id(event)


def test_format_error_response() -> None:
    resp = mod.format_error_response(500, "Server error")
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body["error"] == "Server error"
    assert resp["headers"]["Content-Type"] == "application/json"


def test_format_success_response() -> None:
    data = {"gas_consumption_m3_today": 5.5, "gas_consumption_m3_yesterday": 8.3, "betriebsstunden": 1234}
    resp = mod.format_success_response(data)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["gas_consumption_m3_today"] == 5.5
    assert body["gas_consumption_m3_yesterday"] == 8.3
    assert body["betriebsstunden"] == 1234


def test_lambda_handler_unauthorized_when_no_sub() -> None:
    event = {"requestContext": {"authorizer": {"claims": {}}}}
    result = mod.lambda_handler(event, None)
    assert result["statusCode"] == 401
    body = json.loads(result["body"])
    assert "error" in body


def test_lambda_handler_returns_500_when_secret_not_configured() -> None:
    event = {
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"sub": "user-1"}}},
        },
    }
    import os
    with patch.dict(os.environ, {"VIESSMANN_CREDENTIALS_SECRET_ARN": ""}, clear=False):
        result = mod.lambda_handler(event, None)
    assert result["statusCode"] == 500
