"""Unit tests for AppConfig auto-retrieval validator Lambda."""

from __future__ import annotations

import base64
import json

import pytest

from src.handlers.auto_retrieval_config_validator import lambda_handler


def _valid_config() -> dict:
    return {
        "schemaVersion": 1,
        "maxRetries": 5,
        "retryDelaySeconds": 300,
        "userId": "53e4e8d2-0061-7063-6f27-aeb8e89b9515",
        "frequentActiveWindows": [{"start": "21:00", "stop": "23:55"}],
    }


def test_validator_accepts_base64_encoded_json_content() -> None:
    payload = json.dumps(_valid_config(), separators=(",", ":")).encode("utf-8")
    event = {"content": base64.b64encode(payload).decode("ascii")}

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    assert response["message"] == "Configuration is valid."


def test_validator_accepts_plain_json_content_for_backward_compatibility() -> None:
    event = {"content": json.dumps(_valid_config())}

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    assert response["message"] == "Configuration is valid."


def test_validator_rejects_invalid_content() -> None:
    event = {"content": "not-json-and-not-base64"}

    with pytest.raises(ValueError, match="Configuration content is not valid JSON."):
        lambda_handler(event, None)
