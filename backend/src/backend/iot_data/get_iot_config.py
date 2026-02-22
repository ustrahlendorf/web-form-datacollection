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
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

from .. import config as config_mod
from ..api_auth import auth as auth_mod

# Buffer in seconds: treat token as expired this many seconds before actual expiry.
_TOKEN_EXPIRY_BUFFER = 300  # 5 minutes

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
    token_cache_disabled: bool = False,
) -> argparse.Namespace:
    """
    Build an argparse.Namespace compatible with `api_auth.auth.load_config()`.
    """
    return argparse.Namespace(
        timeout_seconds=str(timeout_seconds),
        insecure_skip_ssl_verify=not bool(ssl_verify),
        pkce_method=pkce_method,
        code_verifier=code_verifier,
        token_cache_disabled=token_cache_disabled,
        # Not used by `load_config()`, but present in the CLI args.
        pretty=False,
        log_level=None,
    )


def load_token_cache(cache_path: Path) -> Optional[dict[str, Any]]:
    """
    Load token cache from file. Returns None if file does not exist or is invalid.
    """
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        required = {"access_token", "expires_at"}
        if not required.issubset(data.keys()):
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def save_token_cache(cache_path: Path, data: dict[str, Any]) -> None:
    """
    Save token cache with atomic write and restrictive permissions (0o600).
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp_path.chmod(0o600)
    tmp_path.rename(cache_path)


def get_valid_token(
    *,
    session: requests.Session,
    cfg: Any,
    log,
    auth_mod,
    cache_path: Optional[Path],
) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[str], int]:
    """
    Obtain a valid access token, using cache and refresh when possible.

    Returns (access_token, refresh_token, installation_id, gateway_serial, device_id, expires_at).
    IoT ids may be None if not in cache (caller must fetch them).
    """
    now = int(time.time())

    # 1. Try load from cache
    if cache_path is not None:
        cached = load_token_cache(cache_path)
        if cached is not None:
            expires_at = cached.get("expires_at")
            access_token = cached.get("access_token")
            refresh_token = cached.get("refresh_token")
            inst_id = cached.get("installation_id")
            gw_serial = cached.get("gateway_serial")
            dev_id = cached.get("device_id")

            if access_token and expires_at is not None:
                if now < (expires_at - _TOKEN_EXPIRY_BUFFER):
                    # Cache hit: token still valid
                    log.debug(
                        "using cached token (expires_at=%s)",
                        expires_at,
                        extra={"run_id": log.extra.get("run_id")},
                    )
                    return (
                        access_token,
                        refresh_token,
                        inst_id,
                        gw_serial,
                        dev_id,
                        int(expires_at),
                    )

                # Token expired but we have refresh_token: refresh
                if refresh_token:
                    try:
                        token_response = auth_mod.refresh_access_token(
                            session=session,
                            cfg=cfg,
                            refresh_token=refresh_token,
                            log=log,
                        )
                        new_expires = (
                            now + token_response.expires_in
                            if token_response.expires_in is not None
                            else expires_at
                        )
                        save_data = {
                            "access_token": token_response.access_token,
                            "refresh_token": token_response.refresh_token or refresh_token,
                            "expires_at": new_expires,
                            "installation_id": inst_id,
                            "gateway_serial": gw_serial,
                            "device_id": dev_id,
                        }
                        save_token_cache(cache_path, {k: v for k, v in save_data.items() if v is not None})
                        log.debug(
                            "refreshed token and updated cache",
                            extra={"run_id": log.extra.get("run_id")},
                        )
                        return (
                            token_response.access_token,
                            token_response.refresh_token or refresh_token,
                            inst_id,
                            gw_serial,
                            dev_id,
                            new_expires,
                        )
                    except auth_mod.CliError:
                        log.debug(
                            "token refresh failed, falling back to full OAuth",
                            extra={"run_id": log.extra.get("run_id")},
                        )
                        # Fall through to full OAuth

    # 2. Full OAuth flow
    code = auth_mod.request_authorization_code(session=session, cfg=cfg, log=log)
    token_response = auth_mod.exchange_code_for_token(session=session, cfg=cfg, code=code, log=log)
    access_token = token_response.access_token
    refresh_token = token_response.refresh_token
    expires_at = (
        now + token_response.expires_in
        if token_response.expires_in is not None
        else now + 3600
    )  # default 1h if missing

    if cache_path is not None and refresh_token:
        save_token_cache(
            cache_path,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
            },
        )

    return (access_token, refresh_token, None, None, None, expires_at)


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


def get_iot_config(
    *,
    timeout_seconds: float = 30.0,
    ssl_verify: bool = True,
    log_level: Optional[str] = None,
    pkce_method: Optional[str] = None,
    code_verifier: Optional[str] = None,
    token_cache_disabled: bool = False,
) -> IotConfig:
    """
    Public API: return token + IoT identifiers (installation id, gateway serial, device id).

    Configuration for OAuth credentials comes from the same env vars as `api_auth.auth`:
    - VIESSMANN_CLIENT_ID (required)
    - VIESSMANN_EMAIL     (required)
    - VIESSMANN_PASSWORD  (required)
    - VIESSMANN_CALLBACK_URI (optional)
    - VIESSMANN_SCOPE        (optional)
    - VIESSMANN_TOKEN_CACHE_PATH (optional; empty = disabled)
    """
    run_id = uuid.uuid4().hex[:12]
    effective_log_level = log_level or os.getenv("VIESSMANN_LOG_LEVEL") or "INFO"
    log = auth_mod.configure_logging(run_id=run_id, level=effective_log_level)

    args = _build_auth_args(
        timeout_seconds=timeout_seconds,
        ssl_verify=ssl_verify,
        pkce_method=pkce_method,
        code_verifier=code_verifier,
        token_cache_disabled=token_cache_disabled,
    )
    cfg = auth_mod.load_config(args, log=log)

    cache_path: Optional[Path] = None
    if not token_cache_disabled:
        cache_path = config_mod.get_token_cache_path()

    session = requests.Session()
    access_token, refresh_token, cached_inst_id, cached_gw_serial, cached_dev_id, expires_at = get_valid_token(
        session=session,
        cfg=cfg,
        log=log,
        auth_mod=auth_mod,
        cache_path=cache_path,
    )

    if cached_inst_id and cached_gw_serial and cached_dev_id:
        installation_id = cached_inst_id
        gateway_serial = cached_gw_serial
        device_id = cached_dev_id
    else:
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
        # Persist full config to cache for next run
        if cache_path is not None and refresh_token:
            save_token_cache(
                cache_path,
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                    "installation_id": installation_id,
                    "gateway_serial": gateway_serial,
                    "device_id": device_id,
                },
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
    p.add_argument(
        "--no-token-cache",
        action="store_true",
        help="Disable token cache (always use full OAuth flow).",
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
            token_cache_disabled=bool(args.no_token_cache),
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
