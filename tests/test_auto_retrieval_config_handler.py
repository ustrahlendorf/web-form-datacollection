"""Unit tests for auto-retrieval AppConfig management API handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.handlers.auto_retrieval_config_handler import lambda_handler


def _authorized_event(method: str, body: dict | None = None) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": {"sub": "user-123"}}},
        }
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


@patch("src.handlers.auto_retrieval_config_handler._get_appconfig_data_client")
def test_get_auto_retrieval_config_returns_current_payload(
    mock_get_appconfig_data_client: MagicMock,
) -> None:
    payload = {
        "schemaVersion": 1,
        "maxRetries": 5,
        "retryDelaySeconds": 300,
        "userId": "test-user",
        "frequentActiveWindows": [{"start": "00:00", "stop": "24:00"}],
    }

    appconfig_data_client = MagicMock()
    appconfig_data_client.start_configuration_session.return_value = {
        "InitialConfigurationToken": "token"
    }
    appconfig_data_client.get_latest_configuration.return_value = {
        "Configuration": MagicMock(
            read=MagicMock(return_value=json.dumps(payload).encode("utf-8"))
        ),
        "VersionLabel": "7",
    }
    mock_get_appconfig_data_client.return_value = appconfig_data_client

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("GET"), None)

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["config"] == payload
    assert response_body["versionLabel"] == "7"


@patch("src.handlers.auto_retrieval_config_handler._get_appconfig_client")
def test_put_auto_retrieval_config_creates_version_and_starts_deployment(
    mock_get_appconfig_client: MagicMock,
) -> None:
    new_config = {
        "schemaVersion": 1,
        "maxRetries": 2,
        "retryDelaySeconds": 120,
        "userId": "operator-user",
        "frequentActiveWindows": [{"start": "08:00", "stop": "12:00"}],
    }

    appconfig_client = MagicMock()
    appconfig_client.create_hosted_configuration_version.return_value = {
        "VersionNumber": 11
    }
    appconfig_client.start_deployment.return_value = {
        "DeploymentNumber": 3,
        "State": "DEPLOYING",
    }
    mock_get_appconfig_client.return_value = appconfig_client

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("PUT", body=new_config), None)

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["versionNumber"] == 11
    assert response_body["deploymentNumber"] == 3
    assert response_body["state"] == "DEPLOYING"
    appconfig_client.create_hosted_configuration_version.assert_called_once()
    appconfig_client.start_deployment.assert_called_once()


def test_put_auto_retrieval_config_rejects_invalid_payload() -> None:
    invalid_config = {
        "schemaVersion": 1,
        "maxRetries": 2,
        "retryDelaySeconds": 120,
        "userId": "operator-user",
        "frequentActiveWindows": [{"start": "12:00", "stop": "08:00"}],
    }

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("PUT", body=invalid_config), None)

    assert response["statusCode"] == 400
    response_body = json.loads(response["body"])
    assert "must satisfy start < stop" in response_body["error"]


def test_auto_retrieval_config_requires_jwt_claims() -> None:
    event = {"requestContext": {"http": {"method": "GET"}, "authorizer": {"jwt": {"claims": {}}}}}
    response = lambda_handler(event, None)
    assert response["statusCode"] == 401


def test_put_auto_retrieval_config_rejects_invalid_json_body() -> None:
    event = _authorized_event("PUT")
    event["body"] = "{invalid-json"

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
        },
        clear=False,
    ):
        response = lambda_handler(event, None)

    assert response["statusCode"] == 400
    response_body = json.loads(response["body"])
    assert response_body["error"] == "Invalid JSON in request body."


def test_put_auto_retrieval_config_returns_500_when_env_not_set() -> None:
    valid_payload = {
        "schemaVersion": 1,
        "maxRetries": 2,
        "retryDelaySeconds": 120,
        "userId": "operator-user",
        "frequentActiveWindows": [{"start": "08:00", "stop": "12:00"}],
    }
    response = lambda_handler(_authorized_event("PUT", body=valid_payload), None)
    assert response["statusCode"] == 500
    response_body = json.loads(response["body"])
    assert response_body["error"] == "Service configuration error"


def test_auto_retrieval_config_rejects_unsupported_method() -> None:
    event = _authorized_event("POST")
    response = lambda_handler(event, None)
    assert response["statusCode"] == 405
