"""
Viessmann Vis-Connect URL and environment configuration.

Loads .env and exposes base URLs and derived endpoint URLs. All URLs can be
overridden via environment variables for environment switching (e.g. staging/prod).

Environment variables:
  - VIESSMANN_IAM_BASE_URL       (optional, default: https://iam.viessmann-climatesolutions.com/idp/v3)
  - VIESSMANN_API_BASE_URL       (optional, default: https://api.viessmann-climatesolutions.com)
  - VIESSMANN_TOKEN_CACHE_PATH   (optional; path to token cache file; empty = disabled)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional


_DEFAULT_IAM_BASE = "https://iam.viessmann-climatesolutions.com/idp/v3"
_DEFAULT_API_BASE = "https://api.viessmann-climatesolutions.com"


def _load_dotenv(log: Optional[logging.LoggerAdapter] = None) -> None:
    """
    Load a .env file into the process environment (if one exists).

    Search order:
    1. Current working directory (.env)
    2. The backend package root — i.e. two levels up from this file
       (backend/src/backend/config.py → backend/)

    Shell / CI environment variables already set take priority: we always
    call load_dotenv() with override=False so existing values are never
    overwritten.

    If python-dotenv is not installed the function is a no-op; credentials
    must then be exported in the calling shell instead.
    """
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]
    except ImportError:
        return

    # Candidate 1: standard location – current working directory
    cwd_env = Path.cwd() / ".env"
    # Candidate 2: backend project root (2 levels up from this source file)
    #   config.py → backend/ → src/ → backend/
    package_root_env = Path(__file__).resolve().parents[2] / ".env"

    env_file: Optional[Path] = None
    if cwd_env.is_file():
        env_file = cwd_env
    elif package_root_env.is_file():
        env_file = package_root_env

    if env_file is None:
        return

    loaded = load_dotenv(env_file, override=False)
    if log is not None:
        if loaded:
            log.debug("loaded .env from %s (shell vars take precedence)", env_file)
        else:
            log.debug(
                ".env found at %s but all variables were already set in the environment",
                env_file,
            )


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable, stripped; return default if unset or empty."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


# Load .env on module import so URL getters see env vars.
_load_dotenv()


def get_iam_base_url() -> str:
    """Return IAM base URL (e.g. for /authorize, /token)."""
    return _get_env("VIESSMANN_IAM_BASE_URL", _DEFAULT_IAM_BASE) or _DEFAULT_IAM_BASE


def get_api_base_url() -> str:
    """Return API base URL (e.g. for /users/me, /iot/...)."""
    return _get_env("VIESSMANN_API_BASE_URL", _DEFAULT_API_BASE) or _DEFAULT_API_BASE


def get_authorize_url() -> str:
    """Return full OAuth authorize endpoint URL."""
    return f"{get_iam_base_url().rstrip('/')}/authorize"


def get_token_url() -> str:
    """Return full OAuth token endpoint URL."""
    return f"{get_iam_base_url().rstrip('/')}/token"


def get_token_cache_path() -> Optional[Path]:
    """
    Return path to token cache file, or None if caching is disabled.

    Uses VIESSMANN_TOKEN_CACHE_PATH if set. If empty, returns None.
    Default: ~/.viessmann/tokens.json
    """
    override = _get_env("VIESSMANN_TOKEN_CACHE_PATH")
    if override is not None:
        if not override:
            return None
        return Path(override).expanduser()
    return Path.home() / ".viessmann" / "tokens.json"


def get_users_me_url() -> str:
    """Return /users/me endpoint URL."""
    return f"{get_api_base_url().rstrip('/')}/users/v1/users/me"


def get_iot_installations_url() -> str:
    """Return IoT installations list endpoint URL."""
    return f"{get_api_base_url().rstrip('/')}/iot/v2/equipment/installations"


def get_iot_gateways_url() -> str:
    """Return IoT gateways list endpoint URL."""
    return f"{get_api_base_url().rstrip('/')}/iot/v2/equipment/gateways"


def get_iot_devices_url_tmpl() -> str:
    """
    Return IoT devices URL template with placeholders:
    {installation_id}, {gateway_serial}.
    """
    base = get_api_base_url().rstrip("/")
    return f"{base}/iot/v2/equipment/installations/{{installation_id}}/gateways/{{gateway_serial}}/devices"


def get_iot_features_url_tmpl() -> str:
    """
    Return IoT features URL template with placeholders:
    {installation_id}, {gateway_serial}, {device_id}.
    """
    base = get_api_base_url().rstrip("/")
    return f"{base}/iot/v2/features/installations/{{installation_id}}/gateways/{{gateway_serial}}/devices/{{device_id}}/features"


def get_iot_single_feature_url_tmpl() -> str:
    """
    Return IoT single-feature URL template with placeholders:
    {installation_id}, {gateway_serial}, {device_id}, {feature_path}.
    Response shape: {"data": {...}}.
    """
    base = get_api_base_url().rstrip("/")
    return f"{base}/iot/v2/features/installations/{{installation_id}}/gateways/{{gateway_serial}}/devices/{{device_id}}/features/{{feature_path}}"
