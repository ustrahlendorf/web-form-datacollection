"""
Lambda handler for auto-retrieval configuration management endpoints.

Implements:
- GET /config/auto-retrieval
- PUT /config/auto-retrieval
"""

from __future__ import annotations

import json
import os
from typing import Any

from src.handlers.auto_retrieval_config_validator import _validate_config

_appconfig_client = None
_appconfig_data_client = None


def _get_appconfig_client():
    """Get boto3 AppConfig client (lazy init for tests)."""
    global _appconfig_client
    if _appconfig_client is None:
        import boto3

        _appconfig_client = boto3.client("appconfig")
    return _appconfig_client


def _get_appconfig_data_client():
    """Get boto3 AppConfigData client (lazy init for tests)."""
    global _appconfig_data_client
    if _appconfig_data_client is None:
        import boto3

        _appconfig_data_client = boto3.client("appconfigdata")
    return _appconfig_data_client


def _extract_user_id(event: dict[str, Any]) -> str:
    """Extract authenticated Cognito user id (sub) from HTTP API JWT claims."""
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}

    claims = None
    jwt_block = authorizer.get("jwt")
    if isinstance(jwt_block, dict):
        claims = jwt_block.get("claims")
    if not isinstance(claims, dict):
        claims = authorizer.get("claims")
    if not isinstance(claims, dict):
        claims = {}

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise KeyError("Missing JWT 'sub' claim.")
    return user_id


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "body": json.dumps(body),
        "headers": {"Content-Type": "application/json"},
    }


def _get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise KeyError(f"Missing required environment variable: {name}")
    return value


def _resolve_identifiers() -> tuple[str, str, str, str]:
    app_id = _get_required_env("AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID")
    env_id = _get_required_env("AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID")
    profile_id = _get_required_env("AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID")
    strategy_id = _get_required_env("AUTO_RETRIEVAL_APPCONFIG_DEPLOYMENT_STRATEGY_ID")
    return app_id, env_id, profile_id, strategy_id


def _parse_put_body(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body")
    if raw_body is None:
        raise ValueError("Missing request body.")

    try:
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON in request body.") from exc

    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    return body


def _get_current_config(
    app_id: str, env_id: str, profile_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch current effective AppConfig document using AppConfigData."""
    data_client = _get_appconfig_data_client()
    session_response = data_client.start_configuration_session(
        ApplicationIdentifier=app_id,
        EnvironmentIdentifier=env_id,
        ConfigurationProfileIdentifier=profile_id,
    )
    token = session_response.get("InitialConfigurationToken")
    if not token:
        return None, None

    latest_response = data_client.get_latest_configuration(ConfigurationToken=token)
    payload_stream = latest_response.get("Configuration")
    if payload_stream is None:
        return None, None

    payload = payload_stream.read() if hasattr(payload_stream, "read") else payload_stream
    if not payload:
        return None, latest_response.get("VersionLabel")

    decoded = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
    parsed = json.loads(decoded)
    if not isinstance(parsed, dict):
        raise ValueError("Effective AppConfig payload is not a JSON object.")
    return parsed, latest_response.get("VersionLabel")


def _handle_get(_event: dict[str, Any]) -> dict[str, Any]:
    app_id, env_id, profile_id, _strategy_id = _resolve_identifiers()
    current_config, version_label = _get_current_config(app_id, env_id, profile_id)
    return _json_response(
        200,
        {
            "config": current_config,
            "versionLabel": version_label,
        },
    )


def _handle_put(event: dict[str, Any]) -> dict[str, Any]:
    app_id, env_id, profile_id, strategy_id = _resolve_identifiers()
    new_config = _parse_put_body(event)
    _validate_config(new_config)

    appconfig_client = _get_appconfig_client()
    content = json.dumps(new_config, separators=(",", ":")).encode("utf-8")

    version_response = appconfig_client.create_hosted_configuration_version(
        ApplicationId=app_id,
        ConfigurationProfileId=profile_id,
        ContentType="application/json",
        Content=content,
    )
    version_number = int(version_response["VersionNumber"])

    deployment_response = appconfig_client.start_deployment(
        ApplicationId=app_id,
        EnvironmentId=env_id,
        DeploymentStrategyId=strategy_id,
        ConfigurationProfileId=profile_id,
        ConfigurationVersion=str(version_number),
        Description=f"Config update via API by user {_extract_user_id(event)}",
    )

    return _json_response(
        200,
        {
            "versionNumber": version_number,
            "deploymentNumber": deployment_response.get("DeploymentNumber"),
            "state": deployment_response.get("State"),
        },
    )


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        _extract_user_id(event)
    except KeyError:
        return _json_response(401, {"error": "Unauthorized"})

    try:
        method = ((event.get("requestContext") or {}).get("http") or {}).get("method")
        if method == "GET":
            return _handle_get(event)
        if method == "PUT":
            return _handle_put(event)
        return _json_response(405, {"error": "Method not allowed"})
    except ValueError as exc:
        return _json_response(400, {"error": str(exc)})
    except KeyError as exc:
        print(f"Configuration error: {exc}")
        return _json_response(500, {"error": "Service configuration error"})
    except Exception as exc:  # pragma: no cover - defensive catch for Lambda runtime
        print(f"Unexpected config API error: {exc}")
        return _json_response(500, {"error": "Internal server error"})
