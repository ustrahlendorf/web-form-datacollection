#!/usr/bin/env python3
"""
Heating values retrieval for Viessmann IoT API.

Fetches consumption, betriebsstunden, starts, supply temperature, and outside
temperature in a single batch call. Reuses get_device_features and get_feature_value.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .feature_data_fetcher import get_device_features
from .feature_extractors import get_feature_value
from .get_iot_config import IotConfig

# Feature paths per plan: heating.gas.consumption.heating, supply temp from sensors
HEATING_FEATURE_PATHS = [
    "heating.gas.consumption.heating",
    "heating.burners.0.statistics",
    "heating.circuits.0.sensors.temperature.supply",
    "heating.sensors.temperature.outside",
]


def _extract_gas_consumption_m3_pair(consumption_props: Any) -> tuple[Optional[float], Optional[float]]:
    """
    Extract (today, yesterday) gas consumption (m³) from heating.gas.consumption.heating properties.

    Viessmann returns day/week/month/year arrays. day.value[0] is today so far,
    day.value[1] is yesterday. Returns (None, None) if invalid or empty.
    """
    if consumption_props is None or not isinstance(consumption_props, dict):
        return (None, None)
    day_obj = consumption_props.get("day")
    if not isinstance(day_obj, dict):
        return (None, None)
    val_arr = day_obj.get("value")
    if not isinstance(val_arr, list) or len(val_arr) == 0:
        return (None, None)
    today_val = None
    yesterday_val = None
    try:
        today_val = float(val_arr[0]) if len(val_arr) >= 1 else None
    except (TypeError, ValueError):
        pass
    try:
        yesterday_val = float(val_arr[1]) if len(val_arr) >= 2 else None
    except (TypeError, ValueError):
        pass
    return (today_val, yesterday_val)


def get_heating_values(
    iot_config: IotConfig,
    *,
    timeout_seconds: float = 30.0,
    ssl_verify: bool = True,
) -> dict[str, Any]:
    """
    Fetch all heating values in one batch and return a normalized dict.

    Returns:
        {
            "gas_consumption_m3_today": float | None,  # day.value[0] (m³ today so far)
            "gas_consumption_m3_yesterday": float | None,  # day.value[1] (m³ yesterday)
            "betriebsstunden": int | None,
            "starts": int | None,
            "supply_temp": float | None,
            "outside_temp": float | None,
            "fetched_at": str,  # ISO timestamp
        }
    """
    features = get_device_features(
        iot_config,
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
    )

    consumption_props = get_feature_value(
        "heating.gas.consumption.heating",
        iot_config,
        features_data=features,
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
    )
    gas_today, gas_yesterday = _extract_gas_consumption_m3_pair(consumption_props)

    burner_stats = get_feature_value(
        "heating.burners.0.statistics",
        iot_config,
        features_data=features,
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
    )
    betriebsstunden = None
    starts = None
    if isinstance(burner_stats, dict):
        betriebsstunden = burner_stats.get("betriebsstunden")
        starts = burner_stats.get("starts")

    supply_temp = get_feature_value(
        "heating.circuits.0.sensors.temperature.supply",
        iot_config,
        features_data=features,
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
    )
    if supply_temp is not None and not isinstance(supply_temp, (int, float)):
        supply_temp = None

    outside_temp = get_feature_value(
        "heating.sensors.temperature.outside",
        iot_config,
        features_data=features,
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
    )
    if outside_temp is not None and not isinstance(outside_temp, (int, float)):
        outside_temp = None

    return {
        "gas_consumption_m3_today": float(gas_today) if gas_today is not None else None,
        "gas_consumption_m3_yesterday": float(gas_yesterday) if gas_yesterday is not None else None,
        "betriebsstunden": int(betriebsstunden) if betriebsstunden is not None else None,
        "starts": int(starts) if starts is not None else None,
        "supply_temp": float(supply_temp) if supply_temp is not None else None,
        "outside_temp": float(outside_temp) if outside_temp is not None else None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["get_heating_values"]
