#!/usr/bin/env python3
"""
Heating values retrieval for Viessmann IoT API.

Fetches consumption, betriebsstunden, starts, supply temperature, and outside
temperature in a single batch call. Reuses get_device_features and get_feature_value.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import requests

from ...shared import config as config_mod
from .feature_data_fetcher import get_device_features
from .feature_extractors import get_feature_value
from .get_iot_config import IotConfig

OPERATING_MODE_FEATURE = "heating.circuits.0.operating.modes.active"
VALID_HEATING_MODES = frozenset({"heating", "standby"})

# Feature paths per plan: heating.gas.consumption.heating, supply temp from sensors
HEATING_FEATURE_PATHS = [
    "heating.gas.consumption.heating",
    "heating.burners.0.statistics",
    "heating.circuits.0.sensors.temperature.supply",
    "heating.sensors.temperature.outside",
    "heating.circuits.0.operating.modes.active",
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

    operating_mode_props = get_feature_value(
        "heating.circuits.0.operating.modes.active",
        iot_config,
        features_data=features,
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
    )
    operating_mode: Optional[str] = None
    if isinstance(operating_mode_props, dict):
        val = operating_mode_props.get("value")
        if isinstance(val, dict):
            operating_mode = val.get("value")
        elif isinstance(val, str):
            operating_mode = val

    return {
        "gas_consumption_m3_today": float(gas_today) if gas_today is not None else None,
        "gas_consumption_m3_yesterday": float(gas_yesterday) if gas_yesterday is not None else None,
        "betriebsstunden": int(betriebsstunden) if betriebsstunden is not None else None,
        "starts": int(starts) if starts is not None else None,
        "supply_temp": float(supply_temp) if supply_temp is not None else None,
        "outside_temp": float(outside_temp) if outside_temp is not None else None,
        "operating_mode": operating_mode,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def set_heating_mode(
    mode: str,
    iot_config: IotConfig,
    *,
    timeout_seconds: float = 30.0,
    ssl_verify: bool = True,
) -> None:
    """
    Set the heating operating mode via the Viessmann IoT API setMode command.

    Args:
        mode: Target mode — must be "heating" or "standby".
        iot_config: IoT configuration from get_iot_config().
        timeout_seconds: HTTP timeout.
        ssl_verify: Whether to verify TLS certificates.

    Raises:
        ValueError: If mode is not a valid value.
        RuntimeError: If the Viessmann API command returns an error.
    """
    if mode not in VALID_HEATING_MODES:
        raise ValueError(f"Invalid mode {mode!r}; must be one of {sorted(VALID_HEATING_MODES)}")

    tmpl = config_mod.get_iot_single_feature_url_tmpl()
    feature_url = tmpl.format(
        installation_id=iot_config.installation_id,
        gateway_serial=iot_config.gateway_serial,
        device_id=iot_config.device_id,
        feature_path=OPERATING_MODE_FEATURE,
    )
    command_url = f"{feature_url}/commands/setMode"

    resp = requests.post(
        command_url,
        json={"mode": mode},
        headers={"Authorization": f"Bearer {iot_config.access_token}"},
        timeout=float(timeout_seconds),
        verify=bool(ssl_verify),
    )
    if resp.status_code >= 400:
        body = (resp.text or "")[:400]
        raise RuntimeError(
            f"setMode command failed: HTTP {resp.status_code}. Body: {body!r}"
        )


__all__ = ["get_heating_values", "set_heating_mode"]
