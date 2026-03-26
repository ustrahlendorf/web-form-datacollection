"""Unit tests for backend.iot_data.feature_extractors."""

from unittest.mock import Mock

import pytest

import backend.iot_data.feature_extractors as ext_mod
from backend.iot_data.get_iot_config import IotConfig


def _make_iot_config() -> IotConfig:
    return IotConfig(
        access_token="test-token",
        installation_id="inst-123",
        gateway_serial="gw-xyz",
        device_id="dev-1",
    )


def _mock_json_response(payload, *, status_code: int = 200):
    resp = Mock()
    resp.status_code = status_code
    resp.text = ""
    resp.json = Mock(return_value=payload)
    return resp


# --- extract_temperature ---


def test_extract_temperature_from_value_key() -> None:
    feature = {"feature": "heating.circuits.0.temperature", "properties": {"value": 21}}
    assert ext_mod.extract_temperature(feature) == 21.0


def test_extract_temperature_from_value_nested() -> None:
    """Viessmann API returns value as nested object: {type, value, unit}."""
    feature = {
        "feature": "heating.circuits.0.temperature",
        "properties": {
            "value": {"type": "number", "value": 36.8, "unit": "celsius"},
        },
    }
    assert ext_mod.extract_temperature(feature) == 36.8


def test_extract_temperature_from_temperature_nested() -> None:
    feature = {
        "feature": "heating.circuits.0.temperature",
        "properties": {"temperature": {"value": 21, "unit": "celsius"}},
    }
    assert ext_mod.extract_temperature(feature) == 21.0


def test_extract_temperature_from_temperature_scalar() -> None:
    feature = {"feature": "heating.boiler.temperature", "properties": {"temperature": 65.5}}
    assert ext_mod.extract_temperature(feature) == 65.5


def test_extract_temperature_returns_none_when_empty_properties() -> None:
    feature = {"feature": "heating.circuits.0.temperature", "properties": {}}
    assert ext_mod.extract_temperature(feature) is None


def test_extract_temperature_returns_none_when_no_properties() -> None:
    feature = {"feature": "heating.circuits.0.temperature"}
    assert ext_mod.extract_temperature(feature) is None


# --- extract_consumption ---


def test_extract_consumption_returns_full_properties() -> None:
    feature = {
        "feature": "heating.gas.consumption.total",
        "properties": {
            "energy": {"value": 100, "unit": "kWh"},
            "volume": {"value": 10, "unit": "m3"},
        },
    }
    result = ext_mod.extract_consumption(feature)
    assert result == {
        "energy": {"value": 100, "unit": "kWh"},
        "volume": {"value": 10, "unit": "m3"},
    }


def test_extract_consumption_returns_empty_dict_when_no_properties() -> None:
    feature = {"feature": "heating.gas.consumption.total"}
    assert ext_mod.extract_consumption(feature) == {}


# --- extract_raw_properties ---


def test_extract_raw_properties_returns_properties() -> None:
    feature = {"feature": "device.serial", "properties": {"serial": "ABC123"}}
    assert ext_mod.extract_raw_properties(feature) == {"serial": "ABC123"}


# --- extract_burner_statistics ---


def test_extract_burner_statistics_from_hours_property() -> None:
    """Viessmann API returns hours and starts in nested format."""
    feature = {
        "feature": "heating.burners.0.statistics",
        "properties": {
            "hours": {"type": "number", "value": 28496, "unit": "hour"},
            "starts": {"type": "number", "value": 13258, "unit": ""},
        },
    }
    result = ext_mod.extract_burner_statistics(feature)
    assert result["betriebsstunden"] == 28496
    assert result["starts"] == 13258


def test_extract_burner_statistics_from_scalar_hours() -> None:
    """Hours and starts as scalar values."""
    feature = {
        "feature": "heating.burners.0.statistics",
        "properties": {
            "hours": 100,
            "starts": 10,
        },
    }
    result = ext_mod.extract_burner_statistics(feature)
    assert result["betriebsstunden"] == 100
    assert result["starts"] == 10


def test_extract_burner_statistics_returns_none_when_empty() -> None:
    feature = {"feature": "heating.burners.0.statistics", "properties": {}}
    result = ext_mod.extract_burner_statistics(feature)
    assert result["betriebsstunden"] is None
    assert result["starts"] is None


def test_extract_feature_value_uses_burner_extractor_for_statistics_path() -> None:
    feature = {
        "feature": "heating.burners.0.statistics",
        "properties": {
            "hours": {"value": 500},
            "starts": {"value": 25},
        },
    }
    result = ext_mod.extract_feature_value("heating.burners.0.statistics", feature)
    assert result == {"betriebsstunden": 500, "starts": 25}


# --- extract_feature_value ---


def test_extract_feature_value_returns_none_when_feature_null() -> None:
    assert ext_mod.extract_feature_value("heating.circuits.0.temperature", None) is None


def test_extract_feature_value_uses_temperature_extractor_for_temperature_path() -> None:
    feature = {"properties": {"value": 21}}
    assert ext_mod.extract_feature_value("heating.circuits.0.temperature", feature) == 21.0


def test_extract_feature_value_uses_consumption_extractor_for_consumption_path() -> None:
    feature = {"properties": {"energy": 100}}
    result = ext_mod.extract_feature_value("heating.gas.consumption.total", feature)
    assert result == {"energy": 100}


def test_extract_feature_value_uses_raw_extractor_for_unknown_path() -> None:
    feature = {"properties": {"foo": "bar"}}
    result = ext_mod.extract_feature_value("device.unknown.feature", feature)
    assert result == {"foo": "bar"}


# --- get_feature_value (integration with fetch) ---


def test_get_feature_value_with_cache_extracts_temperature() -> None:
    iot_config = _make_iot_config()
    features_data = [
        {
            "feature": "heating.circuits.0.temperature",
            "isEnabled": True,
            "properties": {"value": 21},
        },
    ]

    result = ext_mod.get_feature_value(
        "heating.circuits.0.temperature",
        iot_config,
        features_data=features_data,
    )

    assert result == 21.0


def test_get_feature_value_with_cache_extracts_consumption() -> None:
    iot_config = _make_iot_config()
    features_data = [
        {
            "feature": "heating.gas.consumption.total",
            "isEnabled": True,
            "properties": {"energy": 100, "volume": 10},
        },
    ]

    result = ext_mod.get_feature_value(
        "heating.gas.consumption.total",
        iot_config,
        features_data=features_data,
    )

    assert result == {"energy": 100, "volume": 10}


def test_get_feature_value_with_cache_returns_none_when_feature_missing() -> None:
    iot_config = _make_iot_config()
    features_data = [
        {"feature": "heating.boiler.temperature", "isEnabled": True, "properties": {}},
    ]

    result = ext_mod.get_feature_value(
        "heating.circuits.0.temperature",
        iot_config,
        features_data=features_data,
    )

    assert result is None


def test_get_feature_value_without_cache_fetches_via_http() -> None:
    iot_config = _make_iot_config()
    session = Mock()
    # Single-feature endpoint returns {"data": {...}} (object, not array)
    session.get.return_value = _mock_json_response({
        "data": {
            "feature": "heating.circuits.0.temperature",
            "isEnabled": True,
            "properties": {"value": 21},
        },
    })

    result = ext_mod.get_feature_value(
        "heating.circuits.0.temperature",
        iot_config,
        session=session,
    )

    assert result == 21.0
    session.get.assert_called_once()
