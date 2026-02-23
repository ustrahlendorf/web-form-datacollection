"""
Lambda handler for scheduled automatic Viessmann data retrieval.

Triggered by EventBridge Rule (cron). Fetches heating values from Viessmann API,
stores in DynamoDB. Retries on connection failure (configurable via SSM).
Publishes to SNS on final failure.
"""

import json
import os
import time
from typing import Any, Dict

# Lazily initialized clients
_secrets_client = None
_ssm_client = None
_sns_client = None
_dynamodb = None


def _get_secrets_client():
    """Get boto3 Secrets Manager client (lazy init for tests)."""
    global _secrets_client
    if _secrets_client is None:
        import boto3
        _secrets_client = boto3.client("secretsmanager")
    return _secrets_client


def _get_ssm_client():
    """Get boto3 SSM client (lazy init for tests)."""
    global _ssm_client
    if _ssm_client is None:
        import boto3
        _ssm_client = boto3.client("ssm")
    return _ssm_client


def _get_sns_client():
    """Get boto3 SNS client (lazy init for tests)."""
    global _sns_client
    if _sns_client is None:
        import boto3
        _sns_client = boto3.client("sns")
    return _sns_client


def _get_dynamodb_table():
    """Get DynamoDB table for submissions."""
    global _dynamodb
    if _dynamodb is None:
        import boto3
        _dynamodb = boto3.resource("dynamodb")
    table_name = os.environ.get("SUBMISSIONS_TABLE")
    if not table_name:
        raise ValueError("SUBMISSIONS_TABLE environment variable not set")
    return _dynamodb.Table(table_name)


def _load_viessmann_credentials() -> Dict[str, str]:
    """Load Viessmann credentials from AWS Secrets Manager."""
    secret_arn = os.environ.get("VIESSMANN_CREDENTIALS_SECRET_ARN")
    if not secret_arn:
        raise ValueError("VIESSMANN_CREDENTIALS_SECRET_ARN environment variable is not set")
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


def _get_ssm_param(name: str, default: str = "") -> str:
    """Get SSM parameter value."""
    ssm_prefix = os.environ.get("AUTO_RETRIEVAL_SSM_PREFIX", "/HeatingDataCollection/AutoRetrieval")
    path = f"{ssm_prefix}/{name}"
    try:
        client = _get_ssm_client()
        resp = client.get_parameter(Name=path, WithDecryption=False)
        return (resp.get("Parameter") or {}).get("Value") or default
    except Exception as e:
        print(f"SSM get_parameter {path} failed: {e}")
        return default


def _load_config() -> Dict[str, Any]:
    """Load auto-retrieval config from SSM."""
    max_retries_str = _get_ssm_param("MaxRetries", "5")
    retry_delay_str = _get_ssm_param("RetryDelaySeconds", "300")
    user_id = _get_ssm_param("UserId", "SET_ME")

    try:
        max_retries = int(max_retries_str)
    except ValueError:
        max_retries = 5
    try:
        retry_delay_seconds = int(retry_delay_str)
    except ValueError:
        retry_delay_seconds = 300

    return {
        "max_retries": max(1, max_retries),
        "retry_delay_seconds": max(60, retry_delay_seconds),
        "user_id": user_id.strip(),
    }


def _publish_failure_alert(error_message: str, attempt: int, max_retries: int) -> None:
    """Publish failure notification to SNS topic."""
    topic_arn = os.environ.get("AUTO_RETRIEVAL_FAILURE_TOPIC_ARN")
    if not topic_arn:
        print("AUTO_RETRIEVAL_FAILURE_TOPIC_ARN not set, skipping SNS notification")
        return
    try:
        client = _get_sns_client()
        subject = "Auto-retrieval Viessmann data failed"
        body = (
            f"Automatic Viessmann data retrieval failed after {attempt}/{max_retries} attempts.\n\n"
            f"Error: {error_message}"
        )
        client.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=body,
        )
        print("Published failure alert to SNS")
    except Exception as e:
        print(f"Failed to publish SNS alert: {e}")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle scheduled auto-retrieval of Viessmann heating data.

    Loads config from SSM, fetches from Viessmann API with retries,
    stores in DynamoDB. On final failure, publishes to SNS.
    """
    config = _load_config()
    user_id = config["user_id"]
    max_retries = config["max_retries"]
    retry_delay_seconds = config["retry_delay_seconds"]

    if not user_id or user_id == "SET_ME":
        msg = "AutoRetrieval/UserId not configured. Set /HeatingDataCollection/AutoRetrieval/UserId in SSM."
        print(msg)
        _publish_failure_alert(msg, 0, max_retries)
        return {"statusCode": 500, "body": msg}

    creds = _load_viessmann_credentials()
    os.environ["VIESSMANN_CLIENT_ID"] = creds["VIESSMANN_CLIENT_ID"]
    os.environ["VIESSMANN_EMAIL"] = creds["VIESSMANN_EMAIL"]
    os.environ["VIESSMANN_PASSWORD"] = creds["VIESSMANN_PASSWORD"]

    from backend.iot_data.get_iot_config import get_iot_config
    from backend.iot_data.heating_values import get_heating_values

    from src.viessmann_submit import store_viessmann_submission

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            iot_config = get_iot_config(timeout_seconds=30.0, ssl_verify=True)
            values = get_heating_values(iot_config, timeout_seconds=30.0, ssl_verify=True)

            # Validate we have minimum required data
            if values.get("betriebsstunden") is None and values.get("starts") is None:
                raise ValueError("Viessmann API returned no betriebsstunden or starts")

            table = _get_dynamodb_table()
            stored, submission_id = store_viessmann_submission(
                user_id=user_id,
                values=values,
                table=table,
                skip_if_duplicate=True,
            )

            if stored:
                print(f"Stored submission {submission_id}")
                return {"statusCode": 200, "body": json.dumps({"submission_id": submission_id})}
            else:
                print("Skipped (duplicate datum_iso)")
                return {"statusCode": 200, "body": json.dumps({"skipped": "duplicate"})}

        except Exception as e:
            last_error = str(e)
            print(f"Attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                print(f"Retrying in {retry_delay_seconds}s...")
                time.sleep(retry_delay_seconds)

    msg = f"All {max_retries} attempts failed. Last error: {last_error}"
    print(msg)
    _publish_failure_alert(msg, max_retries, max_retries)
    return {"statusCode": 500, "body": msg}
