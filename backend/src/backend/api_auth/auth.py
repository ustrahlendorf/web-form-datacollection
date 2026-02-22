#!/usr/bin/env python3
"""
Viessmann "Vis-Connect" auth helper (CLI).

This script ports the behavior of `SammelBox/php-auth/auth.php` to Python,
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
import logging
import os
import re
import secrets
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

from .. import config as _config

# Module-level URL constants for testability (used by test_vis_connect_get_iot_config).
AUTHORIZE_URL = _config.get_authorize_url()
TOKEN_URL = _config.get_token_url()


class CliError(RuntimeError):
    """Expected CLI failure with a user-facing message."""


class _RunIdFilter(logging.Filter):
    """
    Ensure every log record has a run_id attribute for formatting.
    """

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging uses `filter` name
        if not hasattr(record, "run_id"):
            record.run_id = self._run_id
        return True


def _coerce_log_level(level: str) -> int:
    level_upper = (level or "").strip().upper()
    if not level_upper:
        return logging.INFO
    return logging._nameToLevel.get(level_upper, logging.INFO)


def configure_logging(*, run_id: str, level: str) -> logging.LoggerAdapter:
    """
    Configure logging for CLI runs.

    - Uses root logger configuration only if nothing is configured yet.
    - Adds a run_id to all records so we can correlate multi-step flows.
    """
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=_coerce_log_level(level),
            format="%(asctime)s %(levelname)s [%(name)s] [run=%(run_id)s] %(message)s",
        )
    else:
        root.setLevel(_coerce_log_level(level))

    # Ensure *every* log record can be formatted with %(run_id)s, even if emitted
    # by a 3rd-party library or by a logger not wrapped in our LoggerAdapter.
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "run_id"):
            record.run_id = run_id
        return record

    logging.setLogRecordFactory(record_factory)

    # Also attach a filter to handlers so run_id is present even if a different
    # record factory is installed later (belt-and-suspenders).
    for h in root.handlers:
        h.addFilter(_RunIdFilter(run_id))

    logger = logging.getLogger("backend.api_auth")
    # We intentionally do NOT inject run_id via LoggerAdapter `extra`, because
    # our LogRecordFactory already sets run_id on every record. Injecting it
    # twice would raise KeyError ("Attempt to overwrite 'run_id' in LogRecord").
    return logging.LoggerAdapter(logger, {})


_SENSITIVE_KEYS = {
    "password",
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "code_verifier",
    "code",
    "authorization",
}


def _redact(value: object) -> str:
    """
    Redact potentially sensitive values for safe logging.
    """
    if value is None:
        return "<none>"
    s = str(value)
    if not s:
        return "<empty>"
    if len(s) <= 8:
        return "<redacted>"
    return f"{s[:3]}…{s[-3:]}"


def _redact_sensitive(value: object) -> str:
    """
    Redact *fully* for secret-bearing fields (tokens, passwords, codes).

    Unlike `_redact()`, this never keeps a prefix/suffix because even partial
    leaks of OAuth tokens/codes can be risky in logs.
    """
    if value is None:
        return "<none>"
    s = str(value)
    if not s:
        return "<empty>"
    return "<redacted>"


def _sanitize_mapping(d: dict) -> dict:
    """
    Return a shallow copy safe for logging (redacts sensitive keys).
    """
    safe: dict = {}
    for k, v in d.items():
        if str(k).lower() in _SENSITIVE_KEYS:
            safe[k] = _redact_sensitive(v)
        else:
            safe[k] = v
    return safe


def _sanitize_obj(obj: object) -> object:
    """
    Deep-sanitize JSON-like objects (dict/list/tuple) for safe logging.
    """
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                out[k] = _redact_sensitive(v)
            else:
                out[k] = _sanitize_obj(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_obj(v) for v in obj)
    return obj


def _sanitize_text(text: str) -> str:
    """
    Best-effort scrub of common OAuth token fields in free-form text.

    This is intentionally conservative: we prefer over-redaction to accidental leaks.
    """
    if not text:
        return text
    # JSON-ish tokens: "access_token":"..."
    scrubbed = re.sub(r'("access_token"\s*:\s*")[^"]+(")', r'\1<redacted>\2', text, flags=re.IGNORECASE)
    scrubbed = re.sub(r'("refresh_token"\s*:\s*")[^"]+(")', r'\1<redacted>\2', scrubbed, flags=re.IGNORECASE)
    scrubbed = re.sub(r'("id_token"\s*:\s*")[^"]+(")', r'\1<redacted>\2', scrubbed, flags=re.IGNORECASE)
    # Form/query-ish tokens: access_token=...
    scrubbed = re.sub(r"(access_token=)[^&\s]+", r"\1<redacted>", scrubbed, flags=re.IGNORECASE)
    scrubbed = re.sub(r"(refresh_token=)[^&\s]+", r"\1<redacted>", scrubbed, flags=re.IGNORECASE)
    scrubbed = re.sub(r"(id_token=)[^&\s]+", r"\1<redacted>", scrubbed, flags=re.IGNORECASE)
    # Authorization codes can appear in redirect URLs or HTML.
    scrubbed = re.sub(r"(code=)[^&\"\s]+", r"\1<redacted>", scrubbed, flags=re.IGNORECASE)
    return scrubbed


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


def extract_authorization_code(*, response: requests.Response, log: Optional[logging.LoggerAdapter] = None) -> str:
    """
    Robustly extract an authorization code from an authorize call response.
    """
    # 1) Redirect Location header (common for /authorize).
    location = response.headers.get("Location") or response.headers.get("location")
    if location:
        code = _extract_code_from_url(location)
        if code:
            if log is not None:
                log.debug(
                    "authorization code extracted from Location header",
                    extra={"run_id": log.extra.get("run_id")},
                )
            return code

    # 2) Final URL (if redirects were followed elsewhere).
    if response.url:
        code = _extract_code_from_url(response.url)
        if code:
            if log is not None:
                log.debug(
                    "authorization code extracted from response.url",
                    extra={"run_id": log.extra.get("run_id")},
                )
            return code

    # 3) Fallback: HTML/text body regex similar to the PHP script.
    # PHP used: /code=(.*)"/ (greedy). We use non-greedy and stop at " or & or whitespace.
    body = response.text or ""
    m = re.search(r'code=([^"&\s]+)', body)
    if m:
        if log is not None:
            log.debug(
                "authorization code extracted from response body regex",
                extra={"run_id": log.extra.get("run_id")},
            )
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


def load_config(args: argparse.Namespace, *, log: logging.LoggerAdapter) -> Config:
    _config._load_dotenv(log=log)
    client_id = _get_env("VIESSMANN_CLIENT_ID")
    email = _get_env("VIESSMANN_EMAIL")
    password = _get_env("VIESSMANN_PASSWORD")
    callback_uri = _get_env("VIESSMANN_CALLBACK_URI") or "http://localhost:4200/"
    scope = _get_env("VIESSMANN_SCOPE") or "IoT User"

    missing = [k for k, v in [("VIESSMANN_CLIENT_ID", client_id), ("VIESSMANN_EMAIL", email), ("VIESSMANN_PASSWORD", password)] if not v]
    if missing:
        raise CliError(f"Missing required environment variables: {', '.join(missing)}")

    # Log high-level config without leaking secrets/PII.
    email_hash = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()[:12] if email else "<none>"
    log.info(
        "loaded configuration",
        extra={"run_id": log.extra.get("run_id")},
    )
    log.debug(
        "config details (sanitized): %s",
        _sanitize_mapping(
            {
                "client_id": _redact(client_id),
                "email_sha256_12": email_hash,
                "callback_uri": callback_uri,
                "scope": scope,
                "timeout_seconds": args.timeout_seconds,
                "ssl_verify": not bool(args.insecure_skip_ssl_verify),
                "pkce_method_arg": args.pkce_method,
                "code_verifier_arg_provided": bool(args.code_verifier),
            }
        ),
        extra={"run_id": log.extra.get("run_id")},
    )

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


def request_authorization_code(*, session: requests.Session, cfg: Config, log: logging.LoggerAdapter) -> str:
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
    log.info(
        "requesting authorization code",
        extra={"run_id": log.extra.get("run_id")},
    )
    log.debug(
        "authorize request details (sanitized): %s",
        _sanitize_mapping(
            {
                "url": _config.get_authorize_url(),
                "params": _sanitize_mapping(params),
                "headers": _sanitize_mapping(headers),
                "auth_username": "<redacted>",  # email
                "auth_password": "<redacted>",
                "timeout_seconds": cfg.timeout_seconds,
                "ssl_verify": cfg.ssl_verify,
                "allow_redirects": False,
            }
        ),
        extra={"run_id": log.extra.get("run_id")},
    )

    start = time.perf_counter()
    resp = session.post(
        _config.get_authorize_url(),
        params=params,
        data=b"",
        headers=headers,
        auth=(cfg.email, cfg.password),
        timeout=cfg.timeout_seconds,
        verify=cfg.ssl_verify,
        allow_redirects=False,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    log.info(
        "authorize response received",
        extra={"run_id": log.extra.get("run_id")},
    )
    log.debug(
        "authorize response details: %s",
        {
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "has_location_header": bool(resp.headers.get("Location") or resp.headers.get("location")),
            "content_type": resp.headers.get("Content-Type") or resp.headers.get("content-type"),
            "content_length": resp.headers.get("Content-Length") or resp.headers.get("content-length"),
        },
        extra={"run_id": log.extra.get("run_id")},
    )

    # Some IDPs use 302 for /authorize. Treat 2xx/3xx as potentially valid.
    if resp.status_code >= 400:
        raise CliError(
            f"/authorize failed: HTTP {resp.status_code}. "
            f"Body (truncated, sanitized): {_sanitize_text((resp.text or '')[:500])!r}"
        )

    code = extract_authorization_code(response=resp, log=log)
    log.debug(
        "authorization code extracted (length=%s)",
        len(code),
        extra={"run_id": log.extra.get("run_id")},
    )
    return code


def exchange_code_for_token(*, session: requests.Session, cfg: Config, code: str, log: logging.LoggerAdapter) -> str:
    params = {
        "grant_type": "authorization_code",
        "code_verifier": cfg.code_verifier,
        "client_id": cfg.client_id,
        "redirect_uri": cfg.callback_uri,
        "code": code,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    log.info(
        "exchanging authorization code for access token",
        extra={"run_id": log.extra.get("run_id")},
    )
    log.debug(
        "token request details (sanitized): %s",
        _sanitize_mapping(
            {
                "url": _config.get_token_url(),
                "params": _sanitize_mapping(params),
                "headers": _sanitize_mapping(headers),
                "timeout_seconds": cfg.timeout_seconds,
                "ssl_verify": cfg.ssl_verify,
            }
        ),
        extra={"run_id": log.extra.get("run_id")},
    )

    start = time.perf_counter()
    resp = session.post(
        _config.get_token_url(),
        params=params,
        data=b"",
        headers=headers,
        timeout=cfg.timeout_seconds,
        verify=cfg.ssl_verify,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    log.debug(
        "token response details: %s",
        {
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "content_type": resp.headers.get("Content-Type") or resp.headers.get("content-type"),
        },
        extra={"run_id": log.extra.get("run_id")},
    )

    if resp.status_code >= 400:
        raise CliError(
            f"/token failed: HTTP {resp.status_code}. "
            f"Body (truncated, sanitized): {_sanitize_text((resp.text or '')[:800])!r}"
        )

    try:
        payload = resp.json()
    except Exception as e:
        raise CliError(
            f"/token response was not valid JSON: {e}. Body: {_sanitize_text((resp.text or '')[:800])!r}"
        ) from e

    log.debug(
        "token response body (sanitized): %s",
        _sanitize_obj(payload),
        extra={"run_id": log.extra.get("run_id")},
    )

    token = payload.get("access_token")
    if not token:
        log.warning(
            "token response missing access_token (keys=%s)",
            sorted(payload.keys()),
            extra={"run_id": log.extra.get("run_id")},
        )
        raise CliError(f"/token response missing access_token. Keys: {sorted(payload.keys())}")

    log.info(
        "access token acquired",
        extra={"run_id": log.extra.get("run_id")},
    )
    log.debug(
        "token response keys: %s",
        sorted(payload.keys()),
        extra={"run_id": log.extra.get("run_id")},
    )
    return token


def fetch_users_me(*, session: requests.Session, cfg: Config, access_token: str, log: logging.LoggerAdapter) -> dict:
    params = {"sections": "identity"}
    headers = {"Authorization": f"Bearer {access_token}"}

    log.info(
        "fetching /users/me",
        extra={"run_id": log.extra.get("run_id")},
    )
    log.debug(
        "users/me request details (sanitized): %s",
        _sanitize_mapping(
            {
                "url": _config.get_users_me_url(),
                "params": _sanitize_mapping(params),
                "headers": _sanitize_mapping(headers),
                "timeout_seconds": cfg.timeout_seconds,
                "ssl_verify": cfg.ssl_verify,
            }
        ),
        extra={"run_id": log.extra.get("run_id")},
    )

    start = time.perf_counter()
    resp = session.get(
        _config.get_users_me_url(),
        params=params,
        headers=headers,
        timeout=cfg.timeout_seconds,
        verify=cfg.ssl_verify,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    log.debug(
        "users/me response details: %s",
        {
            "status_code": resp.status_code,
            "elapsed_ms": elapsed_ms,
            "content_type": resp.headers.get("Content-Type") or resp.headers.get("content-type"),
        },
        extra={"run_id": log.extra.get("run_id")},
    )

    if resp.status_code >= 400:
        raise CliError(
            f"/users/me failed: HTTP {resp.status_code}. "
            f"Body (truncated, sanitized): {_sanitize_text((resp.text or '')[:800])!r}"
        )

    try:
        payload = resp.json()
    except Exception as e:
        raise CliError(
            f"/users/me response was not valid JSON: {e}. Body: {_sanitize_text((resp.text or '')[:800])!r}"
        ) from e

    if isinstance(payload, dict):
        log.debug(
            "users/me response keys: %s",
            sorted(payload.keys()),
            extra={"run_id": log.extra.get("run_id")},
        )
    else:
        log.debug(
            "users/me response type: %s",
            type(payload).__name__,
            extra={"run_id": log.extra.get("run_id")},
        )
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="auth.py",
        description="Viessmann Vis-Connect auth CLI (authorize -> token -> users/me).",
    )
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    p.add_argument("--timeout-seconds", default="30", help="HTTP timeout in seconds (default: 30).")
    p.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help='Logging verbosity (default: VIESSMANN_LOG_LEVEL or "INFO").',
    )
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
    log: Optional[logging.LoggerAdapter] = None
    try:
        run_id = uuid.uuid4().hex[:12]
        log_level = args.log_level or _get_env("VIESSMANN_LOG_LEVEL") or "INFO"
        log = configure_logging(run_id=run_id, level=log_level)

        log.info("starting backend auth flow")

        cfg = load_config(args, log=log)

        session = requests.Session()
        code = request_authorization_code(session=session, cfg=cfg, log=log)
        token = exchange_code_for_token(session=session, cfg=cfg, code=code, log=log)
        me = fetch_users_me(session=session, cfg=cfg, access_token=token, log=log)

        if args.pretty:
            print(json.dumps(me, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps(me, ensure_ascii=False))
        log.info("completed successfully")
        return 0
    except CliError as e:
        # Avoid accidentally printing secrets in error output.
        if log is not None:
            log.error("CLI error: %s", _sanitize_text(str(e)))
        else:
            logging.getLogger("backend.api_auth").error("CLI error: %s", _sanitize_text(str(e)))
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except requests.exceptions.SSLError as e:
        if log is not None:
            log.error("SSL error: %s", str(e))
        else:
            logging.getLogger("backend.api_auth").error("SSL error: %s", str(e))
        print(
            "Error: SSL verification failed. "
            "If you must (not recommended), retry with --insecure-skip-ssl-verify. "
            f"Details: {e}",
            file=sys.stderr,
        )
        return 3
    except requests.exceptions.Timeout:
        if log is not None:
            log.error("request timed out")
        else:
            logging.getLogger("backend.api_auth").error("request timed out")
        print("Error: request timed out. Try increasing --timeout-seconds.", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        if log is not None:
            log.warning("interrupted by user")
        else:
            logging.getLogger("backend.api_auth").warning("interrupted by user")
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
