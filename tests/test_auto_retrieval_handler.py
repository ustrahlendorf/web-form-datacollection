"""Tests for auto-retrieval Lambda handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.auto_retrieval_handler import lambda_handler


@patch("src.handlers.auto_retrieval_handler._load_viessmann_credentials")
@patch("src.handlers.auto_retrieval_handler._load_config")
@patch("backend.iot_data.get_iot_config.get_iot_config")
@patch("backend.iot_data.heating_values.get_heating_values")
def test_dry_run_returns_mapped_without_storing(
    mock_get_heating_values,
    mock_get_iot_config,
    mock_load_config,
    mock_load_credentials,
) -> None:
    """Dry-run fetches from Viessmann, maps, validates, but does not write to DynamoDB."""
    mock_load_config.return_value = {
        "user_id": "user-123",
        "max_retries": 3,
        "retry_delay_seconds": 60,
    }
    mock_load_credentials.return_value = {
        "VIESSMANN_CLIENT_ID": "cid",
        "VIESSMANN_EMAIL": "e@x.com",
        "VIESSMANN_PASSWORD": "pwd",
    }
    mock_get_iot_config.return_value = {"install_id": "inst-1"}
    mock_get_heating_values.return_value = {
        "gas_consumption_m3_yesterday": 2.5,
        "betriebsstunden": 100,
        "starts": 10,
        "supply_temp": 45.0,
        "outside_temp": 5.0,
    }

    with patch.dict("os.environ", {"VIESSMANN_CREDENTIALS_SECRET_ARN": "arn:aws:..."}):
        with patch("src.handlers.auto_retrieval_handler._get_dynamodb_table") as mock_table:
            response = lambda_handler({"dry_run": True}, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["dry_run"] is True
    assert "mapped" in body
    mapped = body["mapped"]
    assert mapped["betriebsstunden"] == 100
    assert mapped["starts"] == 10
    assert mapped["verbrauch_qm"] == 2.5
    assert "datum" in mapped
    assert "uhrzeit" in mapped

    # DynamoDB must not be accessed in dry-run
    mock_table.assert_not_called()
