#!/usr/bin/env python3
"""
Heating parameters (Heizkreis 0) read/write via the Viessmann IoT API.

Contract: docs/reference/heating-parameters-live-api.md

Read:  one get_device_features batch call (or reuse ``features_data``).
Write: live read -> diff -> one command per changed parameter -> verification read.
Secrets/tokens are never logged.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import requests

from ...shared import config as config_mod
from .feature_data_fetcher import get_device_features
from .get_iot_config import IotConfig

logger = logging.getLogger(__name__)

_CIRCUIT = "heating.circuits.0"
PROGRAM_FEATURES = {
    "komfort": f"{_CIRCUIT}.operating.programs.comfort",
    "normal": f"{_CIRCUIT}.operating.programs.normal",
    "reduziert": f"{_CIRCUIT}.operating.programs.reduced",
}
CURVE_FEATURE = f"{_CIRCUIT}.heating.curve"
CURVE_PARAMS = ("neigung", "niveau")
PARAMETER_NAMES = ("komfort", "normal", "reduziert", "neigung", "niveau")

# OPEN QUESTION (not verifiable from repo/docs/backend data): Viessmann's setCurve
# constraint for ``shift`` is, to our knowledge, an integer step (slope: step 0.1).
# Our "niveau" allows 1 decimal. Verify against commands.setCurve.params of a real
# feature response. While True, a non-integral niveau is rejected (ValueError)
# BEFORE anything is written; set to False to send niveau as given.
SHIFT_INTEGER_ONLY = True

# Whole write path must stay below the API Gateway 30 s limit.
TOTAL_BUDGET_SECONDS = 26.0
_EPS = 1e-6


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def _find_feature(features: list[dict[str, Any]], path: str) -> Optional[dict[str, Any]]:
    for f in features or []:
        if isinstance(f, dict) and f.get("feature") == path:
            return f
    return None


def _prop_number(feature: Optional[dict[str, Any]], prop: str) -> Optional[float]:
    """properties.<prop>.value (Viessmann: {"type":"number","value":x,"unit":..}) or scalar."""
    if not feature:
        return None
    p = (feature.get("properties") or {}).get(prop)
    if isinstance(p, dict):
        p = p.get("value")
    return _to_float(p)


def _parse_live(features: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, path in PROGRAM_FEATURES.items():
        # Assumed structure: properties.temperature.value (per contract).
        out[name] = _prop_number(_find_feature(features, path), "temperature")
    curve = _find_feature(features, CURVE_FEATURE)
    out["neigung"] = _prop_number(curve, "slope")
    out["niveau"] = _prop_number(curve, "shift")
    out["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return out


def get_heating_parameters(
    iot_config: IotConfig,
    *,
    timeout_seconds: float = 8.0,
    ssl_verify: bool = True,
    features_data: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Return {"komfort","normal","reduziert","neigung","niveau","fetched_at"}; unreadable -> None."""
    features = features_data
    if features is None:
        features = get_device_features(
            iot_config, timeout_seconds=timeout_seconds, ssl_verify=ssl_verify
        )
    return _parse_live(features)


def _command_url(iot_config: IotConfig, feature_path: str, command: str) -> str:
    tmpl = config_mod.get_iot_single_feature_url_tmpl()
    base = tmpl.format(
        installation_id=iot_config.installation_id,
        gateway_serial=iot_config.gateway_serial,
        device_id=iot_config.device_id,
        feature_path=feature_path,
    )
    return f"{base}/commands/{command}"


def _post_command(
    iot_config: IotConfig,
    feature_path: str,
    command: str,
    body: dict[str, Any],
    *,
    timeout: float,
    ssl_verify: bool,
) -> None:
    """POST a command; raises RuntimeError on HTTP >= 400 or transport error."""
    url = _command_url(iot_config, feature_path, command)
    try:
        resp = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {iot_config.access_token}"},
            timeout=timeout,
            verify=bool(ssl_verify),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"{command} failed: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        body_txt = (resp.text or "")[:400]
        raise RuntimeError(f"{command} failed: HTTP {resp.status_code}. Body: {body_txt!r}")


def _clean_number(v: float) -> Any:
    return int(v) if float(v).is_integer() else v


def _validate_changes(changes: dict[str, Any]) -> dict[str, float]:
    if not isinstance(changes, dict):
        raise ValueError("changes must be a dict")
    unknown = [k for k in changes if k not in PARAMETER_NAMES]
    if unknown:
        raise ValueError(f"Invalid parameter name(s): {sorted(unknown)}; allowed: {list(PARAMETER_NAMES)}")
    out: dict[str, float] = {}
    for k, v in changes.items():
        f = _to_float(v)
        if f is None or f != f or f in (float("inf"), float("-inf")):
            raise ValueError(f"Parameter {k!r} must be numeric, got {v!r}")
        if k == "niveau" and SHIFT_INTEGER_ONLY and abs(f - round(f)) > _EPS:
            raise ValueError("niveau must be a whole number (Viessmann shift is integer-stepped)")
        out[k] = f
    return out


def _differs(live: Optional[float], new: float) -> bool:
    return live is None or abs(live - new) > _EPS


def apply_heating_parameters(
    changes: dict[str, Any],
    iot_config: IotConfig,
    *,
    timeout_seconds: float = 8.0,
    ssl_verify: bool = True,
) -> dict[str, Any]:
    """
    Write only the changed parameters to the heating.

    Returns {"applied": {param: {"from","to","ok"}}, "live_before", "live_after",
    "error", "partial"}. Stops at the first failed command, then does a verification
    read. Raises ValueError for invalid parameter names/values; an initial read
    failure propagates (nothing written).
    """
    wanted = _validate_changes(changes)
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS

    def _t() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0.5:
            raise RuntimeError("time budget exhausted")
        return min(float(timeout_seconds), remaining)

    live_before = get_heating_parameters(
        iot_config, timeout_seconds=_t(), ssl_verify=ssl_verify
    )

    diff = {k: v for k, v in wanted.items() if _differs(live_before.get(k), v)}
    applied: dict[str, dict[str, Any]] = {}
    error: Optional[str] = None

    # Build ordered command plan: one setTemperature per program, ONE setCurve.
    plan: list[tuple[str, Any]] = [(k, v) for k, v in diff.items() if k in PROGRAM_FEATURES]
    curve_changed = [k for k in CURVE_PARAMS if k in diff]
    if curve_changed:
        plan.append(("curve", curve_changed))

    for step, arg in plan:
        names = arg if step == "curve" else [step]
        try:
            if step == "curve":
                slope = diff.get("neigung", live_before.get("neigung"))
                shift = diff.get("niveau", live_before.get("niveau"))
                if slope is None or shift is None:
                    raise RuntimeError("setCurve needs both values; live partner value unreadable")
                body = {
                    "slope": _clean_number(slope),
                    "shift": int(round(shift)) if SHIFT_INTEGER_ONLY else _clean_number(shift),
                }
                _post_command(iot_config, CURVE_FEATURE, "setCurve", body,
                              timeout=_t(), ssl_verify=ssl_verify)
            else:
                _post_command(iot_config, PROGRAM_FEATURES[step], "setTemperature",
                              {"targetTemperature": _clean_number(arg)},
                              timeout=_t(), ssl_verify=ssl_verify)
            ok = True
        except RuntimeError as exc:
            ok = False
            error = str(exc)
        for n in names:
            applied[n] = {"from": live_before.get(n), "to": _clean_number(diff[n]), "ok": ok}
        logger.info(
            "heating parameter write: params=%s ok=%s", names, ok
        )
        if not ok:
            break

    live_after: Optional[dict[str, Any]]
    if not plan:
        live_after = live_before  # nothing written, no verification needed
    else:
        try:
            live_after = get_heating_parameters(
                iot_config, timeout_seconds=_t(), ssl_verify=ssl_verify
            )
        except Exception as exc:  # noqa: BLE001 - report, don't mask the write result
            live_after = None
            error = error or f"verification read failed: {type(exc).__name__}"

    partial = any(v["ok"] for v in applied.values()) and (
        error is not None
        or len(applied) < len(diff)
    )
    return {
        "applied": applied,
        "live_before": live_before,
        "live_after": live_after,
        "error": error,
        "partial": bool(partial),
    }


__all__ = [
    "PARAMETER_NAMES",
    "SHIFT_INTEGER_ONLY",
    "apply_heating_parameters",
    "get_heating_parameters",
]
