#!/usr/bin/env python3
"""
Extraction layer for Viessmann IoT feature data.

Maps feature paths to extractors that convert raw API responses into typed values.
Different features return different shapes: scalars (temperature), complex objects
(consumption), etc.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from .feature_data_fetcher import get_feature_data
from .get_iot_config import IotConfig


def extract_temperature(feature: dict[str, Any]) -> Optional[float]:
    """
    Extract scalar temperature from properties.

    Handles Viessmann structures:
    - {"temperature": {"value": 21, "unit": "celsius"}}
    - {"value": {"type": "number", "value": 36.8, "unit": "celsius"}}
    - {"value": 21, "unit": "celsius"}
    - {"temperature": 21}
    """
    props = feature.get("properties") or {}
    if "temperature" in props:
        val = props["temperature"]
        if isinstance(val, dict):
            return _extract_scalar_from_prop(val.get("value"))
        return _coerce_float(val)
    if "value" in props:
        return _extract_scalar_from_prop(props["value"])
    return None


def extract_consumption(feature: dict[str, Any]) -> dict[str, Any]:
    """
    Return full properties object for consumption features (gas, power).

    Consumption features have multiple entries (energy, volume, etc.).
    """
    return feature.get("properties") or {}


def extract_raw_properties(feature: dict[str, Any]) -> dict[str, Any]:
    """
    Fallback: return raw properties for features without a dedicated extractor.
    """
    return feature.get("properties") or {}


def extract_burner_statistics(feature: dict[str, Any]) -> dict[str, Any]:
    """
    Extract operating hours (Betriebsstunden) and starts from burner statistics.

    Viessmann API returns properties like:
    - hours: {value: N, unit: "hour"}
    - starts: {value: N} or similar

    Returns dict with keys: betriebsstunden (int), starts (int).
    """
    props = feature.get("properties") or {}
    result: dict[str, Any] = {"betriebsstunden": None, "starts": None}

    # hours (Betriebsstunden)
    oh = props.get("hours")
    if oh is not None:
        val = oh.get("value") if isinstance(oh, dict) else oh
        result["betriebsstunden"] = _coerce_int(val)

    # starts
    s = props.get("starts")
    if s is not None:
        val = s.get("value") if isinstance(s, dict) else s
        result["starts"] = _coerce_int(val)

    return result


def _coerce_int(value: Any) -> Optional[int]:
    """Coerce value to int if numeric, else None."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> Optional[float]:
    """Coerce value to float if numeric, else None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_scalar_from_prop(prop_value: Any) -> Optional[float]:
    """
    Extract a numeric scalar from a property value.

    Handles both scalar and nested Viessmann structures:
    - 36.8
    - {"type": "number", "value": 36.8, "unit": "celsius"}
    """
    if prop_value is None:
        return None
    if isinstance(prop_value, (int, float)):
        return float(prop_value)
    if isinstance(prop_value, dict) and "value" in prop_value:
        return _coerce_float(prop_value["value"])
    return None


def _get_extractor(feature_path: str) -> Callable[[dict[str, Any]], Any]:
    """
    Return the appropriate extractor for a feature path.

    Uses pattern matching for common feature types to avoid a large explicit registry.
    """
    # Temperature features: heating.circuits.*.temperature, heating.boiler.temperature,
    # heating.dhw.sensors.temperature.*, heating.sensors.temperature.*, etc.
    if ".temperature" in feature_path:
        return extract_temperature
    # Consumption features: gas, power, heat production
    if "consumption" in feature_path or "heat.production" in feature_path:
        return extract_consumption
    # Burner statistics: operating hours (Betriebsstunden), starts
    if "burners" in feature_path and "statistics" in feature_path:
        return extract_burner_statistics
    return extract_raw_properties


def extract_feature_value(feature_path: str, feature: Optional[dict[str, Any]]) -> Any:
    """
    Apply the appropriate extractor for feature_path.

    Args:
        feature_path: Feature identifier (e.g. "heating.circuits.0.temperature").
        feature: Raw feature dict from get_feature_data, or None.

    Returns:
        Extracted value (float, dict, etc.) or None if feature is None.
    """
    if feature is None:
        return None
    extractor = _get_extractor(feature_path)
    return extractor(feature)


def get_feature_value(
    feature_path: str,
    iot_config: IotConfig,
    *,
    features_data: Optional[list[dict[str, Any]]] = None,
    timeout_seconds: float = 30.0,
    ssl_verify: bool = True,
    session: Optional[Any] = None,
    log: Optional[Any] = None,
) -> Any:
    """
    Fetch feature and return extracted value.

    Combines get_feature_data with extract_feature_value. Use features_data
    to avoid duplicate HTTP calls when querying multiple features.

    Args:
        feature_path: Feature identifier (e.g. "heating.circuits.0.temperature").
        iot_config: IoT configuration from get_iot_config().
        features_data: Optional pre-fetched features list.
        timeout_seconds: HTTP timeout (used only when features_data is None).
        ssl_verify: Whether to verify TLS certificates.
        session: Optional requests session.
        log: Optional logger.

    Returns:
        Extracted value: float for temperature, dict for consumption, etc.
    """
    feature = get_feature_data(
        feature_path,
        iot_config,
        features_data=features_data,
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
        session=session,
        log=log,
    )
    return extract_feature_value(feature_path, feature)


__all__ = [
    "extract_burner_statistics",
    "extract_consumption",
    "extract_feature_value",
    "extract_raw_properties",
    "extract_temperature",
    "get_feature_value",
]
