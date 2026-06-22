"""
Lambda handler for heating live data and mode control endpoints.

Handles:
  GET  /heating/live  — fetch current heating values (consumption, temps, operating_mode)
  POST /heating/mode  — set the operating mode ("heating" or "standby")

Credentials are read from AWS Secrets Manager.
"""

import json
import os
from typing import Any, Dict

# Lazily initialized Secrets Manager client.
_secrets_client = None


def _get_secrets_client():
    """Get boto3 Secrets Manager client (lazy init for tests)."""
    global _secrets_client
    if _secrets_client is None:
        import boto3
        _secrets_client = boto3.client("secretsmanager")
    return _secrets_client


def _load_viessmann_credentials() -> Dict[str, str]:
    """
    Load Viessmann credentials from AWS Secrets Manager.

    Expects secret with keys: VIESSMANN_CLIENT_ID, VIESSMANN_EMAIL, VIESSMANN_PASSWORD.
    Secret name from env VIESSMANN_CREDENTIALS_SECRET_ARN or default.
    """
    secret_arn = os.environ.get("VIESSMANN_CREDENTIALS_SECRET_ARN")
    if not secret_arn:
        raise ValueError(
            "VIESSMANN_CREDENTIALS_SECRET_ARN environment variable is not set. "
            "Create a secret in Secrets Manager with keys: VIESSMANN_CLIENT_ID, "
            "VIESSMANN_EMAIL, VIESSMANN_PASSWORD."
        )
    client = _get_secrets_client()
    response = client.get_secret_value(SecretId=secret_arn)
    secret_str = response.get("SecretString")
    if not secret_str:
        raise ValueError("Secret has no SecretString")
    data = json.loads(secret_str)
    for key in ("VIESSMANN_CLIENT_ID", "VIESSMANN_EMAIL", "VIESSMANN_PASSWORD"):
        if not data.get(key):
            raise ValueError(f"Secret missing required key: {key}")
    return data


def extract_user_id(event: Dict[str, Any]) -> str:
    """
    Extract user_id from JWT claims in the Lambda event.

    Args:
        event: Lambda event containing request context with JWT claims

    Returns:
        The user_id (Cognito subject identifier)

    Raises:
        KeyError: If user_id cannot be extracted from JWT claims
    """
    try:
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
        if not user_id:
            raise KeyError("sub claim missing")
        return user_id
    except Exception as e:
        raise KeyError(f"Could not extract user_id from JWT claims: {e}") from e


def format_error_response(status_code: int, error_message: str) -> Dict[str, Any]:
    """Format an error response for the API."""
    return {
        "statusCode": status_code,
        "body": json.dumps({"error": error_message}),
        "headers": {"Content-Type": "application/json"},
    }


def format_success_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """Format a success response for the API."""
    return {
        "statusCode": 200,
        "body": json.dumps(data),
        "headers": {"Content-Type": "application/json"},
    }


def _load_credentials_into_env() -> None:
    creds = _load_viessmann_credentials()
    os.environ["VIESSMANN_CLIENT_ID"] = creds["VIESSMANN_CLIENT_ID"]
    os.environ["VIESSMANN_EMAIL"] = creds["VIESSMANN_EMAIL"]
    os.environ["VIESSMANN_PASSWORD"] = creds["VIESSMANN_PASSWORD"]


def _handle_get_live(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        extract_user_id(event)
    except KeyError:
        return format_error_response(401, "Unauthorized")

    _load_credentials_into_env()

    from backend.heating.iot_data.get_iot_config import get_iot_config
    from backend.heating.iot_data.heating_values import get_heating_values

    iot_config = get_iot_config(timeout_seconds=30.0, ssl_verify=True)
    values = get_heating_values(iot_config, timeout_seconds=30.0, ssl_verify=True)
    return format_success_response(values)


def _handle_post_mode(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        extract_user_id(event)
    except KeyError:
        return format_error_response(401, "Unauthorized")

    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError:
        return format_error_response(400, "Invalid JSON body")

    mode = body.get("mode")
    if mode not in ("heating", "standby"):
        return format_error_response(400, "Invalid mode; must be 'heating' or 'standby'")

    _load_credentials_into_env()

    from backend.heating.iot_data.get_iot_config import get_iot_config
    from backend.heating.iot_data.heating_values import set_heating_mode

    iot_config = get_iot_config(timeout_seconds=30.0, ssl_verify=True)
    set_heating_mode(mode, iot_config, timeout_seconds=30.0, ssl_verify=True)
    print(f"Heating mode set to '{mode}'")
    return format_success_response({"mode": mode})


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Dispatch GET /heating/live and POST /heating/mode requests.

    Args:
        event: Lambda event from API Gateway HTTP API (payload format 2.0)
        context: Lambda context object

    Returns:
        API Gateway response with statusCode and body
    """
    route_key = event.get("routeKey", "")
    try:
        if route_key == "GET /heating/live":
            return _handle_get_live(event)
        elif route_key == "POST /heating/mode":
            return _handle_post_mode(event)
        else:
            return format_error_response(404, "Not found")
    except ValueError as e:
        print(f"Heating handler error: {e}")
        return format_error_response(500, "Configuration error")
    except Exception as e:
        print(f"Heating handler error: {e}")
        return format_error_response(500, "Internal server error")
