"""Unit tests for auto-retrieval AppConfig management API handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from lambdas.auto_retrieval_config.handler import lambda_handler


def _authorized_event(
    method: str,
    body: dict | None = None,
    raw_path: str = "/config/auto-retrieval",
    query_params: dict | None = None,
) -> dict:
    event: dict = {
        "rawPath": raw_path,
        "requestContext": {
            "http": {"method": method, "path": raw_path},
            "authorizer": {"jwt": {"claims": {"sub": "user-123"}}},
        }
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if query_params is not None:
        event["queryStringParameters"] = query_params
    return event


@patch("lambdas.auto_retrieval_config.handler._get_events_client")
@patch("lambdas.auto_retrieval_config.handler._get_appconfig_data_client")
def test_get_auto_retrieval_config_returns_current_payload(
    mock_get_appconfig_data_client: MagicMock,
    mock_get_events_client: MagicMock,
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
    events_client = MagicMock()
    events_client.describe_rule.return_value = {
        "ScheduleExpression": "cron(0/15 * * * ? *)",
    }
    mock_get_events_client.return_value = events_client

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
            "AUTO_RETRIEVAL_FREQUENT_RULE_NAME": "heating-auto-retrieval-frequent-dev",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("GET"), None)

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["config"] == payload
    assert response_body["versionLabel"] == "7"
    assert response_body["scheduler"] == {
        "frequentRuleName": "heating-auto-retrieval-frequent-dev",
        "frequentScheduleCron": "0/15 * * * ? *",
        "frequentScheduleExpression": "cron(0/15 * * * ? *)",
        "frequentIntervalMinutes": 15,
        "source": "eventbridge",
        "available": True,
    }


@patch("lambdas.auto_retrieval_config.handler._get_events_client")
@patch("lambdas.auto_retrieval_config.handler._get_appconfig_data_client")
def test_get_auto_retrieval_config_scheduler_unavailable_when_describe_rule_fails(
    mock_get_appconfig_data_client: MagicMock,
    mock_get_events_client: MagicMock,
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
    events_client = MagicMock()
    events_client.describe_rule.side_effect = RuntimeError("boom")
    mock_get_events_client.return_value = events_client

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
            "AUTO_RETRIEVAL_FREQUENT_RULE_NAME": "heating-auto-retrieval-frequent-dev",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("GET"), None)

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["config"] == payload
    assert response_body["scheduler"] == {
        "frequentRuleName": "heating-auto-retrieval-frequent-dev",
        "frequentScheduleCron": None,
        "frequentScheduleExpression": None,
        "frequentIntervalMinutes": None,
        "source": "eventbridge",
        "available": False,
    }


@patch("lambdas.auto_retrieval_config.handler._get_events_client")
@patch("lambdas.auto_retrieval_config.handler._get_appconfig_data_client")
def test_get_auto_retrieval_config_includes_scheduler_metadata_when_available(
    mock_get_appconfig_data_client: MagicMock,
    mock_get_events_client: MagicMock,
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
        "VersionLabel": "9",
    }
    mock_get_appconfig_data_client.return_value = appconfig_data_client

    events_client = MagicMock()
    events_client.describe_rule.return_value = {
        "ScheduleExpression": "cron(0/15 * * * ? *)"
    }
    mock_get_events_client.return_value = events_client

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
            "AUTO_RETRIEVAL_FREQUENT_RULE_NAME": "heating-auto-retrieval-frequent-dev",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("GET"), None)

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["scheduler"] == {
        "frequentRuleName": "heating-auto-retrieval-frequent-dev",
        "frequentScheduleCron": "0/15 * * * ? *",
        "frequentScheduleExpression": "cron(0/15 * * * ? *)",
        "frequentIntervalMinutes": 15,
        "source": "eventbridge",
        "available": True,
    }
    events_client.describe_rule.assert_called_once_with(
        Name="heating-auto-retrieval-frequent-dev"
    )


@patch("lambdas.auto_retrieval_config.handler._get_events_client")
@patch("lambdas.auto_retrieval_config.handler._get_appconfig_data_client")
def test_get_auto_retrieval_config_keeps_success_response_when_scheduler_unavailable(
    mock_get_appconfig_data_client: MagicMock,
    mock_get_events_client: MagicMock,
) -> None:
    appconfig_data_client = MagicMock()
    appconfig_data_client.start_configuration_session.return_value = {
        "InitialConfigurationToken": "token"
    }
    appconfig_data_client.get_latest_configuration.return_value = {
        "Configuration": MagicMock(read=MagicMock(return_value=b"{}")),
        "VersionLabel": "10",
    }
    mock_get_appconfig_data_client.return_value = appconfig_data_client

    events_client = MagicMock()
    events_client.describe_rule.side_effect = RuntimeError("EventBridge unavailable")
    mock_get_events_client.return_value = events_client

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
            "AUTO_RETRIEVAL_FREQUENT_RULE_NAME": "heating-auto-retrieval-frequent-dev",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("GET"), None)

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["scheduler"] == {
        "frequentRuleName": "heating-auto-retrieval-frequent-dev",
        "frequentScheduleCron": None,
        "frequentScheduleExpression": None,
        "frequentIntervalMinutes": None,
        "source": "eventbridge",
        "available": False,
    }


@patch("lambdas.auto_retrieval_config.handler._get_events_client")
@patch("lambdas.auto_retrieval_config.handler._get_appconfig_data_client")
def test_get_auto_retrieval_config_scheduler_unavailable_when_rule_env_missing(
    mock_get_appconfig_data_client: MagicMock,
    mock_get_events_client: MagicMock,
) -> None:
    appconfig_data_client = MagicMock()
    appconfig_data_client.start_configuration_session.return_value = {
        "InitialConfigurationToken": "token"
    }
    appconfig_data_client.get_latest_configuration.return_value = {
        "Configuration": MagicMock(read=MagicMock(return_value=b"{}")),
        "VersionLabel": "10",
    }
    mock_get_appconfig_data_client.return_value = appconfig_data_client

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
            "AUTO_RETRIEVAL_FREQUENT_RULE_NAME": "",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("GET"), None)

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["scheduler"] == {
        "frequentRuleName": None,
        "frequentScheduleCron": None,
        "frequentScheduleExpression": None,
        "frequentIntervalMinutes": None,
        "source": "eventbridge",
        "available": False,
    }
    mock_get_events_client.assert_not_called()


@patch("lambdas.auto_retrieval_config.handler._get_events_client")
@patch("lambdas.auto_retrieval_config.handler._get_appconfig_data_client")
def test_get_auto_retrieval_config_scheduler_interval_null_for_non_derivable_cron(
    mock_get_appconfig_data_client: MagicMock,
    mock_get_events_client: MagicMock,
) -> None:
    appconfig_data_client = MagicMock()
    appconfig_data_client.start_configuration_session.return_value = {
        "InitialConfigurationToken": "token"
    }
    appconfig_data_client.get_latest_configuration.return_value = {
        "Configuration": MagicMock(read=MagicMock(return_value=b"{}")),
        "VersionLabel": "10",
    }
    mock_get_appconfig_data_client.return_value = appconfig_data_client

    events_client = MagicMock()
    events_client.describe_rule.return_value = {
        "ScheduleExpression": "cron(5 6 * * ? *)",
    }
    mock_get_events_client.return_value = events_client

    with patch.dict(
        "os.environ",
        {
            "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": "app-id",
            "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": "env-id",
            "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": "profile-id",
            "AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID": "strategy-id",
            "AUTO_RETRIEVAL_FREQUENT_RULE_NAME": "heating-auto-retrieval-frequent-dev",
        },
        clear=False,
    ):
        response = lambda_handler(_authorized_event("GET"), None)

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["scheduler"] == {
        "frequentRuleName": "heating-auto-retrieval-frequent-dev",
        "frequentScheduleCron": "5 6 * * ? *",
        "frequentScheduleExpression": "cron(5 6 * * ? *)",
        "frequentIntervalMinutes": None,
        "source": "eventbridge",
        "available": True,
    }


@patch("lambdas.auto_retrieval_config.handler._get_appconfig_client")
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
    appconfig_client.create_hosted_configuration_version.assert_called_once_with(
        ApplicationId="app-id",
        ConfigurationProfileId="profile-id",
        ContentType="application/json",
        Content=json.dumps(new_config, separators=(",", ":")).encode("utf-8"),
    )
    appconfig_client.start_deployment.assert_called_once_with(
        ApplicationId="app-id",
        EnvironmentId="env-id",
        DeploymentStrategyId="strategy-id",
        ConfigurationProfileId="profile-id",
        ConfigurationVersion="11",
        Description="Config update via API by user user-123",
    )


@patch("lambdas.auto_retrieval_config.handler._get_appconfig_client")
def test_get_deployment_status_returns_latest_deployment(
    mock_get_appconfig_client: MagicMock,
) -> None:
    appconfig_client = MagicMock()
    appconfig_client.list_deployments.return_value = {
        "Items": [
            {
                "DeploymentNumber": 7,
                "State": "DEPLOYING",
                "ConfigurationVersion": "11",
                "PercentageComplete": 35.0,
            }
        ]
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
        response = lambda_handler(
            _authorized_event("GET", raw_path="/config/auto-retrieval/deployment-status"),
            None,
        )

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["deployment"]["deploymentNumber"] == 7
    assert response_body["deployment"]["state"] == "DEPLOYING"
    assert response_body["deployment"]["configurationVersion"] == "11"
    assert response_body["deployment"]["percentageComplete"] == 35.0
    appconfig_client.list_deployments.assert_called_once_with(
        ApplicationId="app-id",
        EnvironmentId="env-id",
        MaxResults=1,
    )


@patch("lambdas.auto_retrieval_config.handler._get_appconfig_client")
def test_get_deployment_status_returns_specific_deployment_when_number_provided(
    mock_get_appconfig_client: MagicMock,
) -> None:
    appconfig_client = MagicMock()
    appconfig_client.get_deployment.return_value = {
        "Deployment": {
            "DeploymentNumber": 9,
            "State": "COMPLETE",
            "ConfigurationVersion": "12",
        }
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
        response = lambda_handler(
            _authorized_event(
                "GET",
                raw_path="/config/auto-retrieval/deployment-status",
                query_params={"deploymentNumber": "9"},
            ),
            None,
        )

    assert response["statusCode"] == 200
    response_body = json.loads(response["body"])
    assert response_body["deployment"]["deploymentNumber"] == 9
    assert response_body["deployment"]["state"] == "COMPLETE"
    appconfig_client.get_deployment.assert_called_once_with(
        ApplicationId="app-id",
        EnvironmentId="env-id",
        DeploymentNumber=9,
    )


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
    event = _authorized_event("POST", raw_path="/config/auto-retrieval")
    response = lambda_handler(event, None)
    assert response["statusCode"] == 405
