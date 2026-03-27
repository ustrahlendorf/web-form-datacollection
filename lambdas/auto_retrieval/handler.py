"""
Lambda handler for scheduled automatic Viessmann data retrieval.

Triggered by EventBridge Rule (cron). Fetches heating values from Viessmann API,
stores in DynamoDB. Retries on connection failure (configurable via SSM).
Publishes to SNS on final failure.

When ACTIVE_WINDOWS_PARAM is set (frequent scheduler), Lambda checks current time
in AUTO_RETRIEVAL_ACTIVE_WINDOWS_TIMEZONE (default UTC) against configured windows
and exits early if outside any window.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Lazily initialized clients
_secrets_client = None
_ssm_client = None
_sns_client = None
_dynamodb = None
_appconfig_data_client = None


DEFAULT_SSM_NAMESPACE_PREFIX = "/HeatingDataCollection"


def _normalize_namespace_prefix(prefix: str) -> str:
    """Normalize namespace prefix to '/segment[/segment...]' without trailing slash."""
    normalized = (prefix or "").strip()
    if not normalized:
        return DEFAULT_SSM_NAMESPACE_PREFIX
    return f"/{normalized.lstrip('/')}".rstrip("/")


def _default_auto_retrieval_ssm_prefix() -> str:
    """
    Resolve the auto-retrieval SSM prefix from env in one place.

    Priority:
    1) AUTO_RETRIEVAL_SSM_PREFIX (explicit runtime override)
    2) SSM_NAMESPACE_PREFIX + '/AutoRetrieval' (shared namespace root)
    3) DEFAULT_SSM_NAMESPACE_PREFIX + '/AutoRetrieval'
    """
    explicit_prefix = os.environ.get("AUTO_RETRIEVAL_SSM_PREFIX", "").strip()
    if explicit_prefix:
        return explicit_prefix.rstrip("/")

    namespace_prefix = _normalize_namespace_prefix(
        os.environ.get("SSM_NAMESPACE_PREFIX", DEFAULT_SSM_NAMESPACE_PREFIX)
    )
    return f"{namespace_prefix}/AutoRetrieval"


def _ssm_fallback_enabled() -> bool:
    """Return whether migration fallback to runtime SSM values is enabled."""
    raw = os.environ.get("AUTO_RETRIEVAL_ENABLE_SSM_FALLBACK", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


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


def _get_appconfig_data_client():
    """Get boto3 AppConfigData client (lazy init for tests)."""
    global _appconfig_data_client
    if _appconfig_data_client is None:
        import boto3

        _appconfig_data_client = boto3.client("appconfigdata")
    return _appconfig_data_client


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


# HH:MM pattern for time validation
_TIME_PATTERN = re.compile(r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$")


def _parse_time_to_minutes(s: str) -> int | None:
    """Parse HH:MM string to minutes since midnight. Returns None if invalid. Accepts 24:00 as end-of-day."""
    s = s.strip()
    if s == "24:00":
        return 24 * 60
    m = _TIME_PATTERN.match(s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h * 60 + mi


def _parse_active_windows(json_str: str) -> List[Tuple[int, int]] | None:
    """
    Parse and validate ActiveWindows JSON. Returns list of (start_min, stop_min) or None if invalid.
    - Max 5 windows
    - start < stop
    - stop is exclusive (e.g. 08:00-12:00 includes 08:00 up to but not including 12:00)
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or len(data) > 5:
        return None
    result = []
    for w in data:
        if not isinstance(w, dict):
            return None
        start_s = w.get("start")
        stop_s = w.get("stop")
        if not isinstance(start_s, str) or not isinstance(stop_s, str):
            return None
        start_min = _parse_time_to_minutes(start_s)
        stop_min = _parse_time_to_minutes(stop_s)
        if start_min is None or stop_min is None or start_min >= stop_min:
            return None
        result.append((start_min, stop_min))
    return result if result else None


def _get_appconfig_identifiers() -> Tuple[str, str, str]:
    """Resolve AppConfig identifiers from environment variables."""
    app_id = (
        os.environ.get("AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID")
        or os.environ.get("APPCONFIG_APPLICATION_ID")
        or ""
    ).strip()
    env_id = (
        os.environ.get("AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID")
        or os.environ.get("APPCONFIG_ENVIRONMENT_ID")
        or ""
    ).strip()
    profile_id = (
        os.environ.get("AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID")
        or os.environ.get("APPCONFIG_CONFIGURATION_PROFILE_ID")
        or ""
    ).strip()
    return app_id, env_id, profile_id


def _normalize_appconfig_payload(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    """Normalize AppConfig payload keys into internal handler config keys."""
    if not isinstance(payload, dict):
        print("AppConfig payload is not an object; using fallback")
        return None

    result: Dict[str, Any] = {}
    if "maxRetries" in payload:
        result["max_retries"] = payload.get("maxRetries")
    if "retryDelaySeconds" in payload:
        result["retry_delay_seconds"] = payload.get("retryDelaySeconds")
    if "userId" in payload:
        result["user_id"] = payload.get("userId")
    if "frequentActiveWindows" in payload:
        windows_str = json.dumps(payload.get("frequentActiveWindows"))
        windows = _parse_active_windows(windows_str)
        if windows is not None:
            result["frequent_active_windows"] = windows
        else:
            print("AppConfig frequentActiveWindows invalid; ignoring this field")
    return result if result else None


def _load_appconfig_from_agent(app_id: str, env_id: str, profile_id: str) -> Dict[str, Any] | None:
    """
    Load runtime config from the local AppConfig Agent endpoint.

    Returns normalized config dictionary on success, otherwise None.
    """
    use_agent = os.environ.get("AUTO_RETRIEVAL_USE_APPCONFIG_AGENT", "false").strip().lower()
    if use_agent not in ("1", "true", "yes", "on"):
        return None

    endpoint = os.environ.get("AUTO_RETRIEVAL_APPCONFIG_AGENT_ENDPOINT", "http://127.0.0.1:2772").strip()
    endpoint = endpoint.rstrip("/")
    if not endpoint:
        return None

    timeout_raw = os.environ.get("AUTO_RETRIEVAL_APPCONFIG_AGENT_TIMEOUT_SECONDS", "2.0").strip()
    try:
        timeout_seconds = max(0.1, float(timeout_raw))
    except ValueError:
        timeout_seconds = 2.0

    url = (
        f"{endpoint}/applications/{urllib_parse.quote(app_id, safe='')}"
        f"/environments/{urllib_parse.quote(env_id, safe='')}"
        f"/configurations/{urllib_parse.quote(profile_id, safe='')}"
    )

    try:
        with urllib_request.urlopen(url, timeout=timeout_seconds) as response:
            raw = response.read()
    except Exception as e:
        print(f"AppConfig Agent read failed: {e}; falling back to AppConfigData SDK")
        return None

    if not raw:
        print("AppConfig Agent returned empty config; falling back to AppConfigData SDK")
        return None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        print(f"AppConfig Agent payload parse failed: {e}; falling back to AppConfigData SDK")
        return None

    normalized = _normalize_appconfig_payload(payload)
    if normalized is None:
        print("AppConfig Agent payload invalid/empty; falling back to AppConfigData SDK")
    return normalized


def _load_appconfig() -> Dict[str, Any] | None:
    """
    Load and validate runtime config from AppConfig hosted profile.

    Returns normalized config dictionary on success, otherwise None.
    """
    app_id, env_id, profile_id = _get_appconfig_identifiers()
    if not app_id or not env_id or not profile_id:
        return None

    appconfig_from_agent = _load_appconfig_from_agent(app_id, env_id, profile_id)
    if appconfig_from_agent is not None:
        return appconfig_from_agent

    try:
        client = _get_appconfig_data_client()
        session = client.start_configuration_session(
            ApplicationIdentifier=app_id,
            EnvironmentIdentifier=env_id,
            ConfigurationProfileIdentifier=profile_id,
        )
        token = session.get("InitialConfigurationToken")
        if not token:
            print("AppConfig session returned no token; using fallback")
            return None
        response = client.get_latest_configuration(ConfigurationToken=token)
        raw = response.get("Configuration").read()
    except Exception as e:
        print(f"AppConfig read failed: {e}; using fallback")
        return None

    if not raw:
        print("AppConfig returned empty config; using fallback")
        return None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        print(f"AppConfig payload parse failed: {e}; using fallback")
        return None

    return _normalize_appconfig_payload(payload)


def _is_within_active_window(windows: List[Tuple[int, int]], now: datetime) -> bool:
    """Check if current time falls within any configured active windows."""
    minutes = now.hour * 60 + now.minute
    for start_min, stop_min in windows:
        if start_min <= minutes < stop_min:
            return True
    return False


def _get_active_windows_timezone() -> tuple[Any, str]:
    """
    Resolve timezone used for active-window evaluation.

    Defaults to UTC. Set AUTO_RETRIEVAL_ACTIVE_WINDOWS_TIMEZONE to an IANA timezone
    (for example Europe/Berlin) to evaluate windows in local time.
    """
    tz_name = os.environ.get("AUTO_RETRIEVAL_ACTIVE_WINDOWS_TIMEZONE", "UTC").strip() or "UTC"
    if tz_name.upper() == "UTC":
        return timezone.utc, "UTC"
    try:
        return ZoneInfo(tz_name), tz_name
    except ZoneInfoNotFoundError:
        print(
            f"Invalid AUTO_RETRIEVAL_ACTIVE_WINDOWS_TIMEZONE='{tz_name}', "
            "falling back to UTC"
        )
        return timezone.utc, "UTC"


def _is_once_daily_event() -> bool:
    """Return True when invocation is the once-daily scheduled retrieval."""
    raw = os.environ.get("ONCE_DAILY", "false").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _check_active_window_and_maybe_skip() -> bool:
    """
    If ACTIVE_WINDOWS_PARAM is set, use AppConfig first and optionally SSM fallback.
    Returns True when current time is outside all active windows and retrieval should be skipped.
    Returns False if we should proceed.
    """
    if _is_once_daily_event():
        print("ONCE_DAILY=true: skipping active-window evaluation")
        return False

    param_name = os.environ.get("ACTIVE_WINDOWS_PARAM")
    if not param_name:
        return False
    tzinfo, tz_name = _get_active_windows_timezone()

    appconfig_data = _load_appconfig()
    if appconfig_data:
        windows = appconfig_data.get("frequent_active_windows")
        if windows:
            now = datetime.now(tzinfo)
            if _is_within_active_window(windows, now):
                return False
            print(
                f"Outside active window from AppConfig in timezone {tz_name} "
                f"at {now.strftime('%H:%M')}, skipping retrieval"
            )
            return True

    if not _ssm_fallback_enabled():
        print("No AppConfig active windows and SSM fallback disabled; proceeding with retrieval")
        return False

    ssm_prefix = _default_auto_retrieval_ssm_prefix()
    path = f"{ssm_prefix}/{param_name}"
    try:
        client = _get_ssm_client()
        resp = client.get_parameter(Name=path, WithDecryption=False)
        value = (resp.get("Parameter") or {}).get("Value") or ""
    except Exception as e:
        print(f"SSM get_parameter {path} failed: {e}, proceeding with retrieval")
        return False
    windows = _parse_active_windows(value)
    if windows is None:
        print(f"Invalid ActiveWindows format: {value}, proceeding with retrieval")
        return False
    now = datetime.now(tzinfo)
    if _is_within_active_window(windows, now):
        return False
    print(
        f"Outside active window from SSM in timezone {tz_name} "
        f"at {now.strftime('%H:%M')}, skipping retrieval"
    )
    return True


def _get_ssm_param(name: str, default: str = "") -> str:
    """Get SSM parameter value."""
    if not _ssm_fallback_enabled():
        return default

    ssm_prefix = _default_auto_retrieval_ssm_prefix()
    path = f"{ssm_prefix}/{name}"
    try:
        client = _get_ssm_client()
        resp = client.get_parameter(Name=path, WithDecryption=False)
        return (resp.get("Parameter") or {}).get("Value") or default
    except Exception as e:
        print(f"SSM get_parameter {path} failed: {e}")
        return default


def _load_config() -> Dict[str, Any]:
    """Load auto-retrieval config with fallback order: AppConfig -> optional SSM -> defaults."""
    appconfig_data = _load_appconfig() or {}

    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    max_retries = _safe_int(appconfig_data.get("max_retries"))
    if max_retries is None:
        max_retries = _safe_int(_get_ssm_param("MaxRetries", "5"))
    if max_retries is None:
        max_retries = 5

    retry_delay_seconds = _safe_int(appconfig_data.get("retry_delay_seconds"))
    if retry_delay_seconds is None:
        retry_delay_seconds = _safe_int(_get_ssm_param("RetryDelaySeconds", "300"))
    if retry_delay_seconds is None:
        retry_delay_seconds = 300

    user_id = appconfig_data.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        user_id = _get_ssm_param("UserId", "SET_ME")

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

    When ACTIVE_WINDOWS_PARAM is set (frequent scheduler), exits early if current
    time in AUTO_RETRIEVAL_ACTIVE_WINDOWS_TIMEZONE (default UTC) is outside any
    configured active window.
    """
    if _check_active_window_and_maybe_skip():
        return {"statusCode": 200, "body": json.dumps({"skipped": "outside_active_window"})}

    config = _load_config()
    user_id = config["user_id"]
    max_retries = config["max_retries"]
    retry_delay_seconds = config["retry_delay_seconds"]

    if not user_id or user_id == "SET_ME":
        msg = (
            "AutoRetrieval userId not configured. Set userId in AppConfig "
            f"or enable SSM fallback and set {_default_auto_retrieval_ssm_prefix()}/UserId."
        )
        print(msg)
        _publish_failure_alert(msg, 0, max_retries)
        return {"statusCode": 500, "body": msg}

    creds = _load_viessmann_credentials()
    os.environ["VIESSMANN_CLIENT_ID"] = creds["VIESSMANN_CLIENT_ID"]
    os.environ["VIESSMANN_EMAIL"] = creds["VIESSMANN_EMAIL"]
    os.environ["VIESSMANN_PASSWORD"] = creds["VIESSMANN_PASSWORD"]

    from backend.heating.iot_data.get_iot_config import get_iot_config
    from backend.heating.iot_data.heating_values import get_heating_values

    from backend.viessmann.viessmann_submit import store_viessmann_submission

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            iot_config = get_iot_config(timeout_seconds=30.0, ssl_verify=True)
            values = get_heating_values(iot_config, timeout_seconds=30.0, ssl_verify=True)

            # Validate we have minimum required data
            if values.get("betriebsstunden") is None and values.get("starts") is None:
                raise ValueError("Viessmann API returned no betriebsstunden or starts")

            skip_dup_str = os.environ.get("AUTO_RETRIEVAL_SKIP_DUPLICATE", "true").lower()
            skip_if_duplicate = skip_dup_str in ("true", "1", "yes")

            table = _get_dynamodb_table()
            stored, submission_id = store_viessmann_submission(
                user_id=user_id,
                values=values,
                table=table,
                skip_if_duplicate=skip_if_duplicate,
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
