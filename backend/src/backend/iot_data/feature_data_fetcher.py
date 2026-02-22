#!/usr/bin/env python3
"""
Generic Viessmann IoT feature fetcher.

Fetches device features from the Viessmann API using IotConfig (from get_iot_config).
Supports optional caching to avoid duplicate HTTP calls when querying multiple features.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Optional

import requests

from .. import config as config_mod
from ..api_auth import auth as auth_mod
from .get_iot_config import IotConfig, api_get_json, _extract_list

# Module-level URL templates for testability.
IOT_FEATURES_URL_TMPL = config_mod.get_iot_features_url_tmpl()
IOT_SINGLE_FEATURE_URL_TMPL = config_mod.get_iot_single_feature_url_tmpl()


def get_device_features(
    iot_config: IotConfig,
    *,
    timeout_seconds: float = 30.0,
    ssl_verify: bool = True,
    session: Optional[requests.Session] = None,
    log: Optional[logging.LoggerAdapter] = None,
) -> list[dict[str, Any]]:
    """
    Fetch all device features from the Viessmann IoT API.

    Returns the raw `data` array of feature objects. Each feature has `feature`,
    `isEnabled`, and optionally `properties` and `commands`.

    Args:
        iot_config: IoT configuration from get_iot_config().
        timeout_seconds: HTTP timeout.
        ssl_verify: Whether to verify TLS certificates.
        session: Optional requests session (created if None).
        log: Optional logger (unused, for API consistency).

    Returns:
        List of feature dicts from the API response.
    """
    cfg = SimpleNamespace(timeout_seconds=timeout_seconds, ssl_verify=ssl_verify)
    url = IOT_FEATURES_URL_TMPL.format(
        installation_id=iot_config.installation_id,
        gateway_serial=iot_config.gateway_serial,
        device_id=iot_config.device_id,
    )
    sess = session if session is not None else requests.Session()
    payload = api_get_json(
        session=sess,
        url=url,
        access_token=iot_config.access_token,
        cfg=cfg,
        log=log,
        auth_mod=auth_mod,
    )
    return _extract_list(payload, url=url, auth_mod=auth_mod)


def get_single_feature(
    feature_path: str,
    iot_config: IotConfig,
    *,
    timeout_seconds: float = 30.0,
    ssl_verify: bool = True,
    session: Optional[requests.Session] = None,
    log: Optional[logging.LoggerAdapter] = None,
) -> Optional[dict[str, Any]]:
    """
    Fetch a single feature directly from the single-feature endpoint.

    Response shape: {"data": {...}}. Returns raw feature dict or None if not
    found, disabled, or HTTP 404.
    """
    url = IOT_SINGLE_FEATURE_URL_TMPL.format(
        installation_id=iot_config.installation_id,
        gateway_serial=iot_config.gateway_serial,
        device_id=iot_config.device_id,
        feature_path=feature_path,
    )
    cfg = SimpleNamespace(timeout_seconds=timeout_seconds, ssl_verify=ssl_verify)
    sess = session if session is not None else requests.Session()
    headers = {"Authorization": f"Bearer {iot_config.access_token}"}
    resp = sess.get(
        url,
        headers=headers,
        timeout=float(cfg.timeout_seconds),
        verify=bool(cfg.ssl_verify),
    )
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        body = (resp.text or "")[:800]
        raise auth_mod.CliError(
            f"GET {url} failed: HTTP {resp.status_code}. "
            f"Body (truncated, sanitized): {auth_mod._sanitize_text(body)!r}"
        )
    try:
        payload = resp.json()
    except Exception as e:
        body = (resp.text or "")[:800]
        raise auth_mod.CliError(
            f"GET {url} response was not valid JSON: {e}. "
            f"Body: {auth_mod._sanitize_text(body)!r}"
        ) from e
    items = _extract_list(payload, url=url, auth_mod=auth_mod)
    if not items:
        return None
    f = items[0]
    if not f.get("isEnabled", True):
        return None
    return f


def get_feature_data(
    feature_path: str,
    iot_config: IotConfig,
    *,
    features_data: Optional[list[dict[str, Any]]] = None,
    timeout_seconds: float = 30.0,
    ssl_verify: bool = True,
    session: Optional[requests.Session] = None,
    log: Optional[logging.LoggerAdapter] = None,
) -> Optional[dict[str, Any]]:
    """
    Fetch a single feature by path. Returns the raw feature object or None if not found/disabled.

    Args:
        feature_path: Feature identifier (e.g. "heating.circuits.0.temperature").
        iot_config: IoT configuration from get_iot_config().
        features_data: Optional pre-fetched features list to avoid duplicate HTTP calls.
        timeout_seconds: HTTP timeout (used only when features_data is None).
        ssl_verify: Whether to verify TLS certificates.
        session: Optional requests session.
        log: Optional logger.

    Returns:
        Raw feature dict with keys like feature, isEnabled, properties, commands,
        or None if not found or isEnabled is false.
    """
    if features_data is not None:
        for f in features_data:
            if isinstance(f, dict) and f.get("feature") == feature_path:
                if not f.get("isEnabled", True):
                    return None
                return f
        return None

    return get_single_feature(
        feature_path,
        iot_config,
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
        session=session,
        log=log,
    )


__all__ = ["get_device_features", "get_feature_data", "get_single_feature"]
