"""
Unit tests for auto-retrieval handler: window parsing and early-exit when outside active window.
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from src.handlers.auto_retrieval_handler import (
    _parse_time_to_minutes,
    _parse_active_windows,
    _is_within_active_window,
    _check_active_window_and_maybe_skip,
    lambda_handler,
)


# =============================================================================
# Window parsing and time-in-window logic
# =============================================================================


class TestParseTimeToMinutes:
    """Tests for _parse_time_to_minutes."""

    def test_valid_times(self) -> None:
        assert _parse_time_to_minutes("00:00") == 0
        assert _parse_time_to_minutes("00:01") == 1
        assert _parse_time_to_minutes("08:00") == 8 * 60
        assert _parse_time_to_minutes("12:30") == 12 * 60 + 30
        assert _parse_time_to_minutes("23:59") == 23 * 60 + 59
        assert _parse_time_to_minutes("24:00") == 24 * 60  # end-of-day (24/7 window)

    def test_invalid_times(self) -> None:
        assert _parse_time_to_minutes("25:00") is None
        assert _parse_time_to_minutes("12:60") is None
        assert _parse_time_to_minutes("abc") is None
        assert _parse_time_to_minutes("") is None
        assert _parse_time_to_minutes(" 08:00 ") == 8 * 60  # strip works


class TestParseActiveWindows:
    """Tests for _parse_active_windows."""

    def test_valid_single_window(self) -> None:
        result = _parse_active_windows('[{"start":"08:00","stop":"12:00"}]')
        assert result == [(8 * 60, 12 * 60)]

    def test_valid_multiple_windows(self) -> None:
        result = _parse_active_windows(
            '[{"start":"08:00","stop":"12:00"},{"start":"14:00","stop":"18:00"}]'
        )
        assert result == [(8 * 60, 12 * 60), (14 * 60, 18 * 60)]

    def test_default_24_7(self) -> None:
        result = _parse_active_windows('[{"start":"00:00","stop":"24:00"}]')
        assert result == [(0, 24 * 60)]

    def test_valid_max_5_windows(self) -> None:
        windows = [
            '{"start":"08:00","stop":"09:00"}',
            '{"start":"10:00","stop":"11:00"}',
            '{"start":"12:00","stop":"13:00"}',
            '{"start":"14:00","stop":"15:00"}',
            '{"start":"16:00","stop":"17:00"}',
        ]
        result = _parse_active_windows("[" + ",".join(windows) + "]")
        assert result is not None
        assert len(result) == 5

    def test_invalid_more_than_5_windows(self) -> None:
        windows = [
            '{"start":"08:00","stop":"09:00"}',
            '{"start":"10:00","stop":"11:00"}',
            '{"start":"12:00","stop":"13:00"}',
            '{"start":"14:00","stop":"15:00"}',
            '{"start":"16:00","stop":"17:00"}',
            '{"start":"18:00","stop":"19:00"}',
        ]
        result = _parse_active_windows("[" + ",".join(windows) + "]")
        assert result is None

    def test_invalid_start_geq_stop(self) -> None:
        assert _parse_active_windows('[{"start":"12:00","stop":"12:00"}]') is None
        assert _parse_active_windows('[{"start":"12:00","stop":"08:00"}]') is None

    def test_invalid_json(self) -> None:
        assert _parse_active_windows("not json") is None
        assert _parse_active_windows("") is None
        assert _parse_active_windows("[]") is None  # empty list -> None (no valid windows)

    def test_invalid_structure(self) -> None:
        assert _parse_active_windows('{"start":"08:00","stop":"12:00"}') is None  # not array
        assert _parse_active_windows('[{"start":8,"stop":"12:00"}]') is None  # start not string
        assert _parse_active_windows('[{"start":"08:00"}]') is None  # missing stop


class TestIsWithinActiveWindow:
    """Tests for _is_within_active_window."""

    def test_inside_window(self) -> None:
        windows = [(8 * 60, 12 * 60)]

        now = datetime(2025, 3, 8, 8, 0, 0, tzinfo=timezone.utc)
        assert _is_within_active_window(windows, now) is True

        now = datetime(2025, 3, 8, 11, 59, 0, tzinfo=timezone.utc)
        assert _is_within_active_window(windows, now) is True

    def test_outside_window(self) -> None:
        windows = [(8 * 60, 12 * 60)]

        now = datetime(2025, 3, 8, 7, 59, 0, tzinfo=timezone.utc)
        assert _is_within_active_window(windows, now) is False

        now = datetime(2025, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
        assert _is_within_active_window(windows, now) is False

    def test_stop_exclusive(self) -> None:
        """stop is exclusive: 08:00-12:00 includes 08:00 up to but not including 12:00."""
        windows = [(8 * 60, 12 * 60)]

        now = datetime(2025, 3, 8, 11, 59, 59, tzinfo=timezone.utc)
        assert _is_within_active_window(windows, now) is True

        now = datetime(2025, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
        assert _is_within_active_window(windows, now) is False

    def test_second_window(self) -> None:
        windows = [(8 * 60, 12 * 60), (14 * 60, 18 * 60)]

        now = datetime(2025, 3, 8, 15, 0, 0, tzinfo=timezone.utc)
        assert _is_within_active_window(windows, now) is True


# =============================================================================
# Lambda handler early-exit when outside active window
# =============================================================================


@patch("src.handlers.auto_retrieval_handler._get_ssm_client")
def test_lambda_handler_skips_when_outside_window(mock_ssm_client: MagicMock) -> None:
    """When ACTIVE_WINDOWS_PARAM is set and current time is outside window, return early."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": '[{"start":"08:00","stop":"12:00"}]'}
    }
    mock_ssm_client.return_value = mock_ssm

    with patch.dict(
        "os.environ",
        {
            "ACTIVE_WINDOWS_PARAM": "TestActiveWindows",
            "AUTO_RETRIEVAL_SSM_PREFIX": "/HeatingDataCollection/AutoRetrieval",
        },
    ):
        with patch(
            "src.handlers.auto_retrieval_handler.datetime"
        ) as mock_dt:
            # Simulate 15:00 UTC (outside 08:00-12:00)
            mock_dt.now.return_value = datetime(2025, 3, 8, 15, 0, 0, tzinfo=timezone.utc)

            result = lambda_handler({}, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"skipped": "outside_active_window"}


@patch("src.handlers.auto_retrieval_handler._get_ssm_client")
def test_lambda_handler_proceeds_when_inside_window(mock_ssm_client: MagicMock) -> None:
    """When ACTIVE_WINDOWS_PARAM is set and current time is inside window, proceed with retrieval."""
    mock_ssm = MagicMock()
    mock_ssm.get_parameter.return_value = {
        "Parameter": {"Value": '[{"start":"08:00","stop":"12:00"}]'}
    }
    mock_ssm_client.return_value = mock_ssm

    with patch.dict(
        "os.environ",
        {
            "ACTIVE_WINDOWS_PARAM": "TestActiveWindows",
            "AUTO_RETRIEVAL_SSM_PREFIX": "/HeatingDataCollection/AutoRetrieval",
            "SUBMISSIONS_TABLE": "test-table",
            "VIESSMANN_CREDENTIALS_SECRET_ARN": "arn:aws:secretsmanager:eu-central-1:123:secret:test",
        },
    ):
        with patch(
            "src.handlers.auto_retrieval_handler.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2025, 3, 8, 10, 0, 0, tzinfo=timezone.utc)
            with patch("src.handlers.auto_retrieval_handler._load_config") as mock_config:
                mock_config.return_value = {
                    "max_retries": 1,
                    "retry_delay_seconds": 60,
                    "user_id": "SET_ME",
                }
                # Should proceed to user_id check and fail with 500 (SET_ME)
                result = lambda_handler({}, None)

    # Proceeds past window check; fails on user_id not configured
    assert result["statusCode"] == 500


def test_lambda_handler_no_active_windows_param_proceeds() -> None:
    """When ACTIVE_WINDOWS_PARAM is not set, skip window check entirely."""
    import os

    env_backup = os.environ.get("ACTIVE_WINDOWS_PARAM")
    if "ACTIVE_WINDOWS_PARAM" in os.environ:
        del os.environ["ACTIVE_WINDOWS_PARAM"]

    try:
        with patch.dict(
            "os.environ",
            {
                "SUBMISSIONS_TABLE": "test-table",
                "VIESSMANN_CREDENTIALS_SECRET_ARN": "arn:aws:secretsmanager:eu-central-1:123:secret:test",
            },
        ):
            with patch("src.handlers.auto_retrieval_handler._load_config") as mock_config:
                mock_config.return_value = {
                    "max_retries": 1,
                    "retry_delay_seconds": 60,
                    "user_id": "SET_ME",
                }
                result = lambda_handler({}, None)

        # Proceeds past window check; fails on user_id not configured
        assert result["statusCode"] == 500
    finally:
        if env_backup is not None:
            os.environ["ACTIVE_WINDOWS_PARAM"] = env_backup
