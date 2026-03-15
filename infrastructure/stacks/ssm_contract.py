"""Shared SSM namespace/path contract for infrastructure stacks.

This module centralizes the SSM namespace root and builders used by stacks to
avoid drift across hardcoded parameter names and IAM ARNs.
"""

from __future__ import annotations


# Canonical namespace root used across infrastructure code unless overridden.
DEFAULT_SSM_NAMESPACE_PREFIX = "/HeatingDataCollection"

# Canonical parameter path segments used by multiple stacks.
SUBMISSIONS_ACTIVE_TABLE_NAME_SEGMENTS = ("Submissions", "Active", "TableName")
SUBMISSIONS_ACTIVE_TABLE_ARN_SEGMENTS = ("Submissions", "Active", "TableArn")
SUBMISSIONS_PASSIVE_TABLE_NAME_SEGMENTS = ("Submissions", "Passive", "TableName")
SUBMISSIONS_PASSIVE_TABLE_ARN_SEGMENTS = ("Submissions", "Passive", "TableArn")
AUTO_RETRIEVAL_SEGMENTS = ("AutoRetrieval",)


def normalize_namespace_prefix(prefix: str) -> str:
    """Normalize a namespace prefix to a leading-slash, no-trailing-slash form."""
    normalized = (prefix or "").strip()
    if not normalized:
        raise ValueError("SSM namespace prefix must not be empty")

    normalized = f"/{normalized.lstrip('/')}".rstrip("/")
    if normalized == "":
        raise ValueError("SSM namespace prefix must not resolve to root")

    return normalized


def _normalize_segment(segment: str) -> str:
    normalized = (segment or "").strip().strip("/")
    if not normalized:
        raise ValueError("SSM path segment must not be empty")
    return normalized


def ssm_parameter_name(namespace_prefix: str, *segments: str) -> str:
    """Build an absolute SSM parameter name from prefix and path segments."""
    normalized_prefix = normalize_namespace_prefix(namespace_prefix)
    normalized_segments = [_normalize_segment(segment) for segment in segments]
    if not normalized_segments:
        return normalized_prefix
    return f"{normalized_prefix}/{'/'.join(normalized_segments)}"


def ssm_parameter_arn(region: str, account: str, parameter_name: str) -> str:
    """Build an SSM parameter ARN from an absolute SSM parameter name."""
    normalized_region = (region or "").strip()
    normalized_account = (account or "").strip()
    if not normalized_region:
        raise ValueError("AWS region must not be empty")
    if not normalized_account:
        raise ValueError("AWS account must not be empty")

    # IAM expects "parameter/<path-without-leading-slash>" in SSM ARNs.
    relative_parameter_name = normalize_namespace_prefix(parameter_name).lstrip("/")
    return f"arn:aws:ssm:{normalized_region}:{normalized_account}:parameter/{relative_parameter_name}"


def ssm_parameter_arn_from_segments(
    region: str,
    account: str,
    namespace_prefix: str,
    *segments: str,
) -> str:
    """Build an SSM parameter ARN from namespace prefix and path segments."""
    return ssm_parameter_arn(
        region=region,
        account=account,
        parameter_name=ssm_parameter_name(namespace_prefix, *segments),
    )


__all__ = [
    "AUTO_RETRIEVAL_SEGMENTS",
    "DEFAULT_SSM_NAMESPACE_PREFIX",
    "SUBMISSIONS_ACTIVE_TABLE_ARN_SEGMENTS",
    "SUBMISSIONS_ACTIVE_TABLE_NAME_SEGMENTS",
    "SUBMISSIONS_PASSIVE_TABLE_ARN_SEGMENTS",
    "SUBMISSIONS_PASSIVE_TABLE_NAME_SEGMENTS",
    "normalize_namespace_prefix",
    "ssm_parameter_arn",
    "ssm_parameter_arn_from_segments",
    "ssm_parameter_name",
]
