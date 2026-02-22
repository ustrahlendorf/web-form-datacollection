#!/usr/bin/env python3
"""
CLI for fetching and extracting a single Viessmann IoT feature value.

Fetches IoT config via OAuth, then retrieves the feature and extracts its value.
Prints the result as JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from ..api_auth import auth as auth_mod
from .feature_extractors import get_feature_value
from .get_iot_config import get_iot_config


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch a Viessmann IoT feature value (e.g. temperature, consumption)."
    )
    p.add_argument(
        "feature",
        help='Feature path (e.g. "heating.circuits.0.temperature").',
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
    CLI entrypoint: fetch feature value and print as JSON.

    Returns 0 on success, 1 when feature not found, 2 on auth/config errors.
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
        value = get_feature_value(
            args.feature,
            cfg,
            timeout_seconds=float(args.timeout_seconds),
            ssl_verify=not bool(args.insecure_skip_ssl_verify),
        )
        if value is None:
            print("null", file=sys.stdout)
            return 1
        print(json.dumps(value, ensure_ascii=False, default=str))
        return 0
    except auth_mod.CliError as e:
        print(f"Error: {auth_mod._sanitize_text(str(e))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
