"""Lambda validator for AppConfig auto-retrieval configuration."""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

_TIME_PATTERN = re.compile(r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$")


def _parse_time_to_minutes(value: str) -> int | None:
    value = value.strip()
    if value == "24:00":
        return 24 * 60
    match = _TIME_PATTERN.match(value)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    return hours * 60 + minutes


def _validate_active_windows(active_windows: Any) -> None:
    if not isinstance(active_windows, list):
        raise ValueError("'frequentActiveWindows' must be an array.")
    if len(active_windows) == 0:
        raise ValueError("'frequentActiveWindows' must contain at least one window.")
    if len(active_windows) > 5:
        raise ValueError("'frequentActiveWindows' must not contain more than 5 windows.")

    for index, window in enumerate(active_windows):
        if not isinstance(window, dict):
            raise ValueError(f"Window at index {index} must be an object.")
        start = window.get("start")
        stop = window.get("stop")
        if not isinstance(start, str) or not isinstance(stop, str):
            raise ValueError(f"Window at index {index} requires string 'start' and 'stop'.")
        start_minutes = _parse_time_to_minutes(start)
        stop_minutes = _parse_time_to_minutes(stop)
        if start_minutes is None or stop_minutes is None:
            raise ValueError(f"Window at index {index} has invalid HH:MM values.")
        if start_minutes >= stop_minutes:
            raise ValueError(
                f"Window at index {index} must satisfy start < stop (received {start}-{stop})."
            )


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("schemaVersion") != 1:
        raise ValueError("'schemaVersion' must equal 1.")

    max_retries = config.get("maxRetries")
    if not isinstance(max_retries, int) or not (0 <= max_retries <= 20):
        raise ValueError("'maxRetries' must be an integer between 0 and 20.")

    retry_delay = config.get("retryDelaySeconds")
    if not isinstance(retry_delay, int) or not (1 <= retry_delay <= 3600):
        raise ValueError("'retryDelaySeconds' must be an integer between 1 and 3600.")

    user_id = config.get("userId")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("'userId' must be a non-empty string.")

    _validate_active_windows(config.get("frequentActiveWindows"))


def _parse_configuration_content(event: dict[str, Any]) -> dict[str, Any]:
    # AppConfig Lambda validator sends content as base64-encoded bytes.
    content = event.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Missing or empty 'content' in validator event.")

    content_str = content.strip()
    if content_str.startswith("{"):
        decoded_content = content_str
    else:
        try:
            decoded_content = base64.b64decode(content_str, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("Configuration content is not valid JSON.") from exc

    try:
        config = json.loads(decoded_content)
    except json.JSONDecodeError as exc:
        raise ValueError("Configuration content is not valid JSON.") from exc

    if not isinstance(config, dict):
        raise ValueError("Configuration content must be a JSON object.")
    return config


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    config = _parse_configuration_content(event)
    _validate_config(config)
    return {"statusCode": 200, "message": "Configuration is valid."}
