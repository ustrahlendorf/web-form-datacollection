#!/usr/bin/env python3
"""
Fetch Viessmann IoT configuration (installation id, gateway serial, device id).

This module reuses the existing OAuth implementation from `api_auth.auth` and then
calls the IoT equipment endpoints with:

    Authorization: Bearer <access_token>

Selection rule (per project plan): we **auto-pick the first element** returned
from each list endpoint and extract:
- installations[0]["id"]
- gateways[0]["serial"]
- devices[0]["id"]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .. import config as config_mod
from ..api_auth import auth as auth_mod

# Module-level URL constants for testability.
IOT_INSTALLATIONS_URL = config_mod.get_iot_installations_url()
IOT_GATEWAYS_URL = config_mod.get_iot_gateways_url()
IOT_DEVICES_URL_TMPL = config_mod.get_iot_devices_url_tmpl()


@dataclass(frozen=True)
class IotConfig:
    access_token: str
    installation_id: str
    gateway_serial: str
    device_id: str


def _build_auth_args(
    *,
    timeout_seconds: float,
    ssl_verify: bool,
    pkce_method: Optional[str] = None,
    code_verifier: Optional[str] = None,
) -> argparse.Namespace:
    """
    Build an argparse.Namespace compatible with `api_auth.auth.load_config()`.
    """
    return argparse.Namespace(
        timeout_seconds=str(timeout_seconds),
        insecure_skip_ssl_verify=not bool(ssl_verify),
        pkce_method=pkce_method,
        code_verifier=code_verifier,
        # Not used by `load_config()`, but present in the CLI args.
        pretty=False,
        log_level=None,
    )


def _extract_list(payload: Any, *, url: str, auth_mod) -> list[dict]:
    """
    Normalize IoT list responses to a list[dict].

    Viessmann APIs return either:
    - {"data": [...]}  (array of items, e.g. installations, gateways, devices)
    - {"data": {...}}  (single object, e.g. single-feature endpoint)
    - [...]           (bare list)
    """
    items: Any
    if isinstance(payload, dict) and "data" in payload:
        data = payload["data"]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            raise auth_mod.CliError(
                f"Unexpected 'data' type from {url}: expected list or object."
            )
    elif isinstance(payload, list):
        items = payload
    else:
        raise auth_mod.CliError(
            f"Unexpected JSON shape from {url}: expected list or dict with 'data'."
        )

    # Defensive: enforce list[dict] shape for downstream key extraction.
    if not all(isinstance(x, dict) for x in items):
        raise auth_mod.CliError(
            f"Unexpected items from {url}: expected list of objects."
        )
    return items


def _require_first(items: list[dict], *, url: str, what: str, auth_mod) -> dict:
    if not items:
        raise auth_mod.CliError(f"{what} list from {url} is empty.")
    return items[0]


def _require_key(obj: dict, key: str, *, url: str, what: str, auth_mod) -> str:
    value = obj.get(key)
    # Viessmann APIs sometimes return identifiers as integers (e.g. installation "id": 194640).
    # We accept string or int identifiers and always return a string for downstream URL building.
    if value is None or value == "":
        raise auth_mod.CliError(f"Missing or invalid '{key}' in first {what} item from {url}.")
    if isinstance(value, (str, int)):
        return str(value)
    raise auth_mod.CliError(f"Missing or invalid '{key}' in first {what} item from {url}.")


def api_get_json(*, session: requests.Session, url: str, access_token: str, cfg: Any, log, auth_mod) -> Any:
    """
    Shared IoT GET helper.

    - Adds Authorization: Bearer
    - Enforces timeout + TLS verification from `api_auth.auth.Config`
    - Parses JSON and raises `CliError` on failures
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = session.get(
        url,
        headers=headers,
        timeout=float(getattr(cfg, "timeout_seconds", 30.0)),
        verify=bool(getattr(cfg, "ssl_verify", True)),
    )

    if resp.status_code >= 400:
        body = (resp.text or "")[:800]
        raise auth_mod.CliError(
            f"GET {url} failed: HTTP {resp.status_code}. "
            f"Body (truncated, sanitized): {auth_mod._sanitize_text(body)!r}"
        )

    try:
        return resp.json()
    except Exception as e:
        body = (resp.text or "")[:800]
        raise auth_mod.CliError(
            f"GET {url} response was not valid JSON: {e}. Body: {auth_mod._sanitize_text(body)!r}"
        ) from e


def get_installation_id(*, session: requests.Session, access_token: str, cfg: Any, log, auth_mod) -> str:
    url = config_mod.get_iot_installations_url()
    payload = api_get_json(session=session, url=url, access_token=access_token, cfg=cfg, log=log, auth_mod=auth_mod)
    items = _extract_list(payload, url=url, auth_mod=auth_mod)
    first = _require_first(items, url=url, what="installations", auth_mod=auth_mod)
    return _require_key(first, "id", url=url, what="installations", auth_mod=auth_mod)


def get_gateway_serial(*, session: requests.Session, access_token: str, cfg: Any, log, auth_mod) -> str:
    url = config_mod.get_iot_gateways_url()
    payload = api_get_json(session=session, url=url, access_token=access_token, cfg=cfg, log=log, auth_mod=auth_mod)
    items = _extract_list(payload, url=url, auth_mod=auth_mod)
    first = _require_first(items, url=url, what="gateways", auth_mod=auth_mod)
    return _require_key(first, "serial", url=url, what="gateways", auth_mod=auth_mod)


def get_device_id(
    *,
    session: requests.Session,
    access_token: str,
    installation_id: str,
    gateway_serial: str,
    cfg: Any,
    log,
    auth_mod,
) -> str:
    url = config_mod.get_iot_devices_url_tmpl().format(
        installation_id=installation_id, gateway_serial=gateway_serial
    )
    payload = api_get_json(session=session, url=url, access_token=access_token, cfg=cfg, log=log, auth_mod=auth_mod)
    items = _extract_list(payload, url=url, auth_mod=auth_mod)
    first = _require_first(items, url=url, what="devices", auth_mod=auth_mod)
    return _require_key(first, "id", url=url, what="devices", auth_mod=auth_mod)


def get_access_token(*, session: requests.Session, cfg: Any, log, auth_mod) -> str:
    """
    Obtain an access token using the OAuth flow implemented in `api_auth.auth`.
    """
    code = auth_mod.request_authorization_code(session=session, cfg=cfg, log=log)
    return auth_mod.exchange_code_for_token(session=session, cfg=cfg, code=code, log=log)


def get_iot_config(
    *,
    timeout_seconds: float = 30.0,
    ssl_verify: bool = True,
    log_level: Optional[str] = None,
    pkce_method: Optional[str] = None,
    code_verifier: Optional[str] = None,
) -> IotConfig:
    """
    Public API: return token + IoT identifiers (installation id, gateway serial, device id).

    Configuration for OAuth credentials comes from the same env vars as `api_auth.auth`:
    - VIESSMANN_CLIENT_ID (required)
    - VIESSMANN_EMAIL     (required)
    - VIESSMANN_PASSWORD  (required)
    - VIESSMANN_CALLBACK_URI (optional)
    - VIESSMANN_SCOPE        (optional)
    """
    run_id = uuid.uuid4().hex[:12]
    effective_log_level = log_level or os.getenv("VIESSMANN_LOG_LEVEL") or "INFO"
    log = auth_mod.configure_logging(run_id=run_id, level=effective_log_level)

    args = _build_auth_args(
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
        pkce_method=pkce_method,
        code_verifier=code_verifier,
    )
    cfg = auth_mod.load_config(args, log=log)

    session = requests.Session()
    access_token = get_access_token(session=session, cfg=cfg, log=log, auth_mod=auth_mod)

    installation_id = get_installation_id(session=session, access_token=access_token, cfg=cfg, log=log, auth_mod=auth_mod)
    gateway_serial = get_gateway_serial(session=session, access_token=access_token, cfg=cfg, log=log, auth_mod=auth_mod)
    device_id = get_device_id(
        session=session,
        access_token=access_token,
        installation_id=installation_id,
        gateway_serial=gateway_serial,
        cfg=cfg,
        log=log,
        auth_mod=auth_mod,
    )

    # Debug-only visibility into return values.
    #
    # IMPORTANT: The access token is a secret, so even at DEBUG we never log it
    # in cleartext. We log a fully redacted placeholder to avoid accidental
    # leaks in CI logs, terminals, or log aggregators.
    #
    # If you truly need to see the raw token, print it explicitly in a local,
    # controlled environment (not recommended) rather than changing this logger.
    log.debug(
        "get_iot_config() resolved values (sanitized): %s",
        {
            "access_token": auth_mod._redact_sensitive(access_token),
            "installation_id": installation_id,
            "gateway_serial": gateway_serial,
            "device_id": device_id,
        },
    )

    return IotConfig(
        access_token=access_token,
        installation_id=installation_id,
        gateway_serial=gateway_serial,
        device_id=device_id,
    )


__all__ = ["IotConfig", "get_iot_config"]


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch Viessmann IoT identifiers (installation id, gateway serial, device id)."
    )
    p.add_argument(
        "--timeout-seconds",
        default="30",
        help="HTTP timeout in seconds (default: 30).",
    )
    p.add_argument(
        "--insecure-skip-ssl-verify",
        action="store_true",
        help="Disable TLS certificate verification (NOT recommended).",
    )
    p.add_argument(
        "--log-level",
        default=None,
        help='Logging level (e.g. "DEBUG", "INFO"). You can also set VIESSMANN_LOG_LEVEL.',
    )
    p.add_argument(
        "--code-verifier",
        default=None,
        help="Override PKCE code_verifier (otherwise generated).",
    )
    p.add_argument(
        "--pkce-method",
        default=None,
        choices=["S256", "plain"],
        help='PKCE method ("S256" default; "plain" for legacy compatibility).',
    )
    return p.parse_args(sys.argv[1:] if argv is None else argv)


def main(argv: Optional[list[str]] = None) -> int:
    """
    CLI entrypoint so running this file produces output.

    Prints the resolved identifiers as JSON to stdout.
    """
    args = _parse_args(argv)
    try:
        cfg = get_iot_config(
            timeout_seconds=float(args.timeout_seconds),
            ssl_verify=not bool(args.insecure_skip_ssl_verify),
            log_level=args.log_level,
            pkce_method=args.pkce_method,
            code_verifier=args.code_verifier,
        )
        print(
            json.dumps(
                {
                    "installation_id": cfg.installation_id,
                    "gateway_serial": cfg.gateway_serial,
                    "device_id": cfg.device_id,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except auth_mod.CliError as e:
        # Avoid accidentally printing secrets in error output.
        print(f"Error: {auth_mod._sanitize_text(str(e))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
