"""Unit tests for backend.iot_data.heating_values."""

from unittest.mock import patch

import pytest

import backend.iot_data.heating_values as hv_mod
from backend.iot_data.get_iot_config import IotConfig


def _make_iot_config() -> IotConfig:
    return IotConfig(
        access_token="test-token",
        installation_id="inst-123",
        gateway_serial="gw-xyz",
        device_id="dev-1",
    )


def _gas_consumption_props(day_first: float) -> dict:
    """Viessmann heating.gas.consumption.heating properties structure."""
    return {
        "day": {"type": "array", "value": [day_first, 8.3, 9, 8.6, 8.1, 8.4, 8.4, 8.9], "unit": "cubicMeter"},
        "week": {"type": "array", "value": [56.3, 50.5, 60.8, 64.5, 71.2, 55.6, 74.6], "unit": "cubicMeter"},
        "month": {"type": "array", "value": [176.1, 299.6, 238.2], "unit": "cubicMeter"},
        "year": {"type": "array", "value": [475.7, 1471.6], "unit": "cubicMeter"},
    }


def test_get_heating_values_extracts_gas_consumption_m3_from_day_value() -> None:
    """Gas consumption today and yesterday from day.value array (m³)."""
    iot_config = _make_iot_config()
    features = [
        {"feature": "heating.gas.consumption.heating", "isEnabled": True, "properties": _gas_consumption_props(5.5)},
        {"feature": "heating.burners.0.statistics", "isEnabled": True, "properties": {"operatingHours": {"value": 100}, "starts": {"value": 25}}},
        {"feature": "heating.circuits.0.sensors.temperature.supply", "isEnabled": True, "properties": {"value": 45.2}},
        {"feature": "heating.sensors.temperature.outside", "isEnabled": True, "properties": {"value": 3.1}},
    ]

    def mock_get_feature_value(path, *args, **kwargs):
        for f in features:
            if f.get("feature") == path:
                props = f.get("properties", {})
                if path == "heating.burners.0.statistics":
                    return {"betriebsstunden": 100, "starts": 25}
                if path in ("heating.circuits.0.sensors.temperature.supply", "heating.sensors.temperature.outside"):
                    return props.get("value")
                return props
        return None

    with patch.object(hv_mod, "get_device_features", return_value=features):
        with patch.object(hv_mod, "get_feature_value", side_effect=mock_get_feature_value):
            result = hv_mod.get_heating_values(iot_config)

    assert result["gas_consumption_m3_today"] == 5.5
    assert result["gas_consumption_m3_yesterday"] == 8.3
    assert result["betriebsstunden"] == 100
    assert result["starts"] == 25
    assert result["supply_temp"] == 45.2
    assert result["outside_temp"] == 3.1
    assert "fetched_at" in result


def test_get_heating_values_returns_none_when_day_value_empty() -> None:
    """When day.value is empty, gas_consumption_m3_today and gas_consumption_m3_yesterday are None."""
    iot_config = _make_iot_config()
    features = [
        {"feature": "heating.gas.consumption.heating", "isEnabled": True, "properties": {"day": {"value": []}}},
        {"feature": "heating.burners.0.statistics", "isEnabled": True, "properties": {}},
        {"feature": "heating.circuits.0.sensors.temperature.supply", "isEnabled": True, "properties": {}},
        {"feature": "heating.sensors.temperature.outside", "isEnabled": True, "properties": {}},
    ]

    with patch.object(hv_mod, "get_device_features", return_value=features):
        with patch.object(hv_mod, "get_feature_value") as mock_gfv:
            def side_effect(path, *args, **kwargs):
                for f in features:
                    if f.get("feature") == path:
                        return f.get("properties")
                return None

            mock_gfv.side_effect = side_effect

            result = hv_mod.get_heating_values(iot_config)

    assert result["gas_consumption_m3_today"] is None
    assert result["gas_consumption_m3_yesterday"] is None


def test_extract_gas_consumption_m3_pair_returns_none_when_no_day_key() -> None:
    """When properties lack 'day' key, returns (None, None)."""
    assert hv_mod._extract_gas_consumption_m3_pair({"week": {"value": [1, 2, 3]}}) == (None, None)


def test_extract_gas_consumption_m3_pair_returns_today_and_yesterday() -> None:
    """Extracts today and yesterday from day.value array."""
    props = {"day": {"type": "array", "value": [5.5, 8.3, 9], "unit": "cubicMeter"}}
    assert hv_mod._extract_gas_consumption_m3_pair(props) == (5.5, 8.3)


def test_extract_gas_consumption_m3_pair_single_element_returns_yesterday_none() -> None:
    """When day.value has only one element, yesterday is None."""
    props = {"day": {"type": "array", "value": [5.5], "unit": "cubicMeter"}}
    assert hv_mod._extract_gas_consumption_m3_pair(props) == (5.5, None)
