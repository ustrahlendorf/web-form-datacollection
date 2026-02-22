"""Unit tests for backend.iot_data.feature_data_fetcher."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import backend.api_auth.auth as auth_mod
import backend.iot_data.feature_data_fetcher as fetcher_mod
from backend.iot_data.get_iot_config import IotConfig


def _make_iot_config(
    *,
    access_token: str = "test-token",
    installation_id: str = "inst-123",
    gateway_serial: str = "gw-xyz",
    device_id: str = "dev-1",
) -> IotConfig:
    return IotConfig(
        access_token=access_token,
        installation_id=installation_id,
        gateway_serial=gateway_serial,
        device_id=device_id,
    )


def _mock_json_response(payload, *, status_code: int = 200, text: str = ""):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.json = Mock(return_value=payload)
    return resp


def test_get_device_features_accepts_data_as_object() -> None:
    """API may return {"data": {...}} (single object); normalize to list of one."""
    iot_config = _make_iot_config()
    session = Mock()
    session.get.return_value = _mock_json_response({
        "data": {
            "feature": "heating.circuits.0.temperature",
            "isEnabled": True,
            "properties": {"value": {"value": 36.8, "unit": "celsius"}},
        },
    })

    features = fetcher_mod.get_device_features(iot_config, session=session)

    assert len(features) == 1
    assert features[0]["feature"] == "heating.circuits.0.temperature"


def test_get_device_features_returns_data_array() -> None:
    iot_config = _make_iot_config()
    session = Mock()
    session.get.return_value = _mock_json_response({
        "data": [
            {"feature": "heating.circuits.0.temperature", "isEnabled": True, "properties": {"value": 21}},
            {"feature": "heating.boiler.temperature", "isEnabled": True, "properties": {"value": 65}},
        ],
    })

    features = fetcher_mod.get_device_features(iot_config, session=session)

    assert len(features) == 2
    assert features[0]["feature"] == "heating.circuits.0.temperature"
    assert features[1]["feature"] == "heating.boiler.temperature"
    expected_url = fetcher_mod.IOT_FEATURES_URL_TMPL.format(
        installation_id="inst-123",
        gateway_serial="gw-xyz",
        device_id="dev-1",
    )
    session.get.assert_called_once()
    call_args = session.get.call_args
    assert call_args[0][0] == expected_url
    assert call_args[1]["headers"] == {"Authorization": "Bearer test-token"}


def test_get_single_feature_returns_feature_from_data_object() -> None:
    """Single-feature endpoint returns {"data": {...}}; extracts feature correctly."""
    iot_config = _make_iot_config()
    session = Mock()
    session.get.return_value = _mock_json_response({
        "data": {
            "feature": "heating.circuits.0.temperature",
            "isEnabled": True,
            "properties": {"value": {"value": 21, "unit": "celsius"}},
        },
    })

    result = fetcher_mod.get_single_feature(
        "heating.circuits.0.temperature",
        iot_config,
        session=session,
    )

    assert result is not None
    assert result["feature"] == "heating.circuits.0.temperature"
    assert session.get.call_args[0][0].endswith("/features/heating.circuits.0.temperature")


def test_get_single_feature_returns_none_when_disabled() -> None:
    iot_config = _make_iot_config()
    session = Mock()
    session.get.return_value = _mock_json_response({
        "data": {
            "feature": "heating.circuits.0.temperature",
            "isEnabled": False,
            "properties": {"value": 21},
        },
    })

    result = fetcher_mod.get_single_feature(
        "heating.circuits.0.temperature",
        iot_config,
        session=session,
    )

    assert result is None


def test_get_feature_data_with_features_cache_returns_feature() -> None:
    iot_config = _make_iot_config()
    features_data = [
        {"feature": "heating.circuits.0.temperature", "isEnabled": True, "properties": {"value": 21}},
        {"feature": "heating.boiler.temperature", "isEnabled": True, "properties": {"value": 65}},
    ]

    result = fetcher_mod.get_feature_data(
        "heating.circuits.0.temperature",
        iot_config,
        features_data=features_data,
    )

    assert result is not None
    assert result["feature"] == "heating.circuits.0.temperature"
    assert result["properties"]["value"] == 21


def test_get_feature_data_with_features_cache_returns_none_when_not_found() -> None:
    iot_config = _make_iot_config()
    features_data = [
        {"feature": "heating.boiler.temperature", "isEnabled": True, "properties": {}},
    ]

    result = fetcher_mod.get_feature_data(
        "heating.circuits.0.temperature",
        iot_config,
        features_data=features_data,
    )

    assert result is None


def test_get_feature_data_with_features_cache_returns_none_when_disabled() -> None:
    iot_config = _make_iot_config()
    features_data = [
        {"feature": "heating.circuits.0.temperature", "isEnabled": False, "properties": {"value": 21}},
    ]

    result = fetcher_mod.get_feature_data(
        "heating.circuits.0.temperature",
        iot_config,
        features_data=features_data,
    )

    assert result is None


def test_get_feature_data_without_cache_fetches_via_single_feature_endpoint() -> None:
    """Uses single-feature endpoint; response shape: {"data": {...}}."""
    iot_config = _make_iot_config()
    session = Mock()
    session.get.return_value = _mock_json_response({
        "data": {
            "feature": "heating.circuits.0.temperature",
            "isEnabled": True,
            "properties": {"value": {"type": "number", "value": 36.8, "unit": "celsius"}},
        },
    })

    result = fetcher_mod.get_feature_data(
        "heating.circuits.0.temperature",
        iot_config,
        session=session,
    )

    assert result is not None
    assert result["feature"] == "heating.circuits.0.temperature"
    session.get.assert_called_once()
    expected_url = fetcher_mod.IOT_SINGLE_FEATURE_URL_TMPL.format(
        installation_id="inst-123",
        gateway_serial="gw-xyz",
        device_id="dev-1",
        feature_path="heating.circuits.0.temperature",
    )
    assert session.get.call_args[0][0] == expected_url


def test_get_feature_data_without_cache_returns_none_on_404() -> None:
    """Single-feature endpoint returns 404 when feature does not exist."""
    iot_config = _make_iot_config()
    session = Mock()
    resp = Mock()
    resp.status_code = 404
    resp.text = ""
    session.get.return_value = resp

    result = fetcher_mod.get_feature_data(
        "heating.circuits.0.temperature",
        iot_config,
        session=session,
    )

    assert result is None
