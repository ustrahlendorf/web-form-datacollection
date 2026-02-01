#!/usr/bin/env python3
"""
Viessmann "Vis-Connect" auth helper (CLI).

This script ports the behavior of `vis-connect/php-auth/auth.php` to Python,
while improving safety and robustness:

- Reads secrets/config from environment variables (no hard-coded credentials)
- Uses proper PKCE by default (S256)
- Extracts the authorization code from:
  - redirect Location header (preferred), or
  - final URL, or
  - response body fallback regex (`code=...`)
- Exchanges the code for an access token and calls `/users/me`
- Prints the resulting JSON to stdout

Environment variables:
  - VIESSMANN_CLIENT_ID           (required)
  - VIESSMANN_EMAIL               (required)
  - VIESSMANN_PASSWORD            (required)
  - VIESSMANN_CALLBACK_URI        (optional, default: http://localhost:4200/)
  - VIESSMANN_SCOPE               (optional, default: IoT User)

Optional PKCE compatibility overrides:
  - VIESSMANN_CODE_VERIFIER       (optional; overrides generated verifier)
  - VIESSMANN_PKCE_METHOD         (optional; "S256" or "plain", default: S256)

Notes:
  - The legacy PHP script disables SSL verification. This script verifies SSL by
    default. Use --insecure-skip-ssl-verify only if you understand the risk.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests


AUTHORIZE_URL = "https://iam.viessmann.com/idp/v3/authorize"
TOKEN_URL = "https://iam.viessmann.com/idp/v3/token"
USERS_ME_URL = "https://api.viessmann.com/users/v1/users/me"


class CliError(RuntimeError):
    """Expected CLI failure with a user-facing message."""


def _base64url_no_padding(raw: bytes) -> str:
    """
    Base64URL encode without '=' padding, per PKCE spec.
    """
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_code_verifier(length: int = 64) -> str:
    """
    Generate a PKCE code_verifier.

    RFC 7636 requires 43..128 chars. We generate URL-safe characters.
    """
    if length < 43 or length > 128:
        raise ValueError("PKCE code_verifier length must be 43..128")
    # token_urlsafe(n) returns a string length ~ ceil(n*4/3).
    # We trim to desired length for determinism.
    return secrets.token_urlsafe(96)[:length]


def code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _base64url_no_padding(digest)


def code_challenge_plain(verifier: str) -> str:
    return verifier


def _extract_code_from_url(url: str) -> Optional[str]:
    """
    Extract ?code=... from a URL (or Location header value).
    Returns None if no code is present.
    """
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        values = qs.get("code")
        if values and values[0]:
            return values[0]
    except Exception:
        return None
    return None


def extract_authorization_code(*, response: requests.Response) -> str:
    """
    Robustly extract an authorization code from an authorize call response.
    """
    # 1) Redirect Location header (common for /authorize).
    location = response.headers.get("Location") or response.headers.get("location")
    if location:
        code = _extract_code_from_url(location)
        if code:
            return code

    # 2) Final URL (if redirects were followed elsewhere).
    if response.url:
        code = _extract_code_from_url(response.url)
        if code:
            return code

    # 3) Fallback: HTML/text body regex similar to the PHP script.
    # PHP used: /code=(.*)"/ (greedy). We use non-greedy and stop at " or & or whitespace.
    body = response.text or ""
    m = re.search(r'code=([^"&\s]+)', body)
    if m:
        return m.group(1)

    raise CliError(
        "Failed to extract authorization code from /authorize response "
        "(no Location header, no code in URL, no code=... in response body)."
    )


@dataclass(frozen=True)
class Config:
    client_id: str
    email: str
    password: str
    callback_uri: str
    scope: str
    timeout_seconds: float
    ssl_verify: bool
    pkce_method: str  # "S256" or "plain"
    code_verifier: str


def _get_env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_config(args: argparse.Namespace) -> Config:
    client_id = _get_env("VIESSMANN_CLIENT_ID")
    email = _get_env("VIESSMANN_EMAIL")
    password = _get_env("VIESSMANN_PASSWORD")
    callback_uri = _get_env("VIESSMANN_CALLBACK_URI") or "http://localhost:4200/"
    scope = _get_env("VIESSMANN_SCOPE") or "IoT User"

    missing = [k for k, v in [("VIESSMANN_CLIENT_ID", client_id), ("VIESSMANN_EMAIL", email), ("VIESSMANN_PASSWORD", password)] if not v]
    if missing:
        raise CliError(f"Missing required environment variables: {', '.join(missing)}")

    # PKCE config
    pkce_method = (args.pkce_method or _get_env("VIESSMANN_PKCE_METHOD") or "S256").strip()
    pkce_method_upper = pkce_method.upper()
    if pkce_method_upper not in {"S256", "PLAIN"}:
        raise CliError('VIESSMANN_PKCE_METHOD / --pkce-method must be "S256" or "plain"')

    verifier = args.code_verifier or _get_env("VIESSMANN_CODE_VERIFIER") or generate_code_verifier()

    return Config(
        client_id=client_id,
        email=email,
        password=password,
        callback_uri=callback_uri,
        scope=scope,
        timeout_seconds=float(args.timeout_seconds),
        ssl_verify=not bool(args.insecure_skip_ssl_verify),
        pkce_method="S256" if pkce_method_upper == "S256" else "plain",
        code_verifier=verifier,
    )


def request_authorization_code(*, session: requests.Session, cfg: Config) -> str:
    """
    Do the authorize call and return the extracted code.

    We intentionally do NOT follow redirects to avoid trying to connect to
    localhost (the typical redirect_uri).
    """
    if cfg.pkce_method == "S256":
        challenge = code_challenge_s256(cfg.code_verifier)
        challenge_method = "S256"
    else:
        challenge = code_challenge_plain(cfg.code_verifier)
        challenge_method = "plain"

    params = {
        "client_id": cfg.client_id,
        "code_challenge": challenge,
        "code_challenge_method": challenge_method,
        "scope": cfg.scope,
        "redirect_uri": cfg.callback_uri,
        "response_type": "code",
    }

    # PHP sets a form content-type and uses POST; we mirror that behavior.
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = session.post(
        AUTHORIZE_URL,
        params=params,
        data=b"",
        headers=headers,
        auth=(cfg.email, cfg.password),
        timeout=cfg.timeout_seconds,
        verify=cfg.ssl_verify,
        allow_redirects=False,
    )

    # Some IDPs use 302 for /authorize. Treat 2xx/3xx as potentially valid.
    if resp.status_code >= 400:
        raise CliError(
            f"/authorize failed: HTTP {resp.status_code}. "
            f"Body (truncated): {resp.text[:500]!r}"
        )

    return extract_authorization_code(response=resp)


def exchange_code_for_token(*, session: requests.Session, cfg: Config, code: str) -> str:
    params = {
        "grant_type": "authorization_code",
        "code_verifier": cfg.code_verifier,
        "client_id": cfg.client_id,
        "redirect_uri": cfg.callback_uri,
        "code": code,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    resp = session.post(
        TOKEN_URL,
        params=params,
        data=b"",
        headers=headers,
        timeout=cfg.timeout_seconds,
        verify=cfg.ssl_verify,
    )

    if resp.status_code >= 400:
        raise CliError(
            f"/token failed: HTTP {resp.status_code}. "
            f"Body (truncated): {resp.text[:800]!r}"
        )

    try:
        payload = resp.json()
    except Exception as e:
        raise CliError(f"/token response was not valid JSON: {e}. Body: {resp.text[:800]!r}") from e

    token = payload.get("access_token")
    if not token:
        raise CliError(f"/token response missing access_token. Keys: {sorted(payload.keys())}")
    return token


def fetch_users_me(*, session: requests.Session, cfg: Config, access_token: str) -> dict:
    params = {"sections": "identity"}
    headers = {"Authorization": f"Bearer {access_token}"}

    resp = session.get(
        USERS_ME_URL,
        params=params,
        headers=headers,
        timeout=cfg.timeout_seconds,
        verify=cfg.ssl_verify,
    )

    if resp.status_code >= 400:
        raise CliError(
            f"/users/me failed: HTTP {resp.status_code}. "
            f"Body (truncated): {resp.text[:800]!r}"
        )

    try:
        return resp.json()
    except Exception as e:
        raise CliError(f"/users/me response was not valid JSON: {e}. Body: {resp.text[:800]!r}") from e


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="auth.py",
        description="Viessmann Vis-Connect auth CLI (authorize -> token -> users/me).",
    )
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    p.add_argument("--timeout-seconds", default="30", help="HTTP timeout in seconds (default: 30).")
    p.add_argument(
        "--insecure-skip-ssl-verify",
        action="store_true",
        help="Disable TLS certificate verification (NOT recommended).",
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
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        cfg = load_config(args)

        session = requests.Session()
        code = request_authorization_code(session=session, cfg=cfg)
        token = exchange_code_for_token(session=session, cfg=cfg, code=code)
        me = fetch_users_me(session=session, cfg=cfg, access_token=token)

        if args.pretty:
            print(json.dumps(me, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps(me, ensure_ascii=False))
        return 0
    except CliError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except requests.exceptions.SSLError as e:
        print(
            "Error: SSL verification failed. "
            "If you must (not recommended), retry with --insecure-skip-ssl-verify. "
            f"Details: {e}",
            file=sys.stderr,
        )
        return 3
    except requests.exceptions.Timeout:
        print("Error: request timed out. Try increasing --timeout-seconds.", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

