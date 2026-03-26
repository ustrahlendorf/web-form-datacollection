"""Shared ``Code.from_asset`` exclude list for Lambda bundles from the repo root."""

from __future__ import annotations

# Keep in sync across all stacks that zip the repo (or a subtree) for Lambda.
LAMBDA_CODE_ASSET_EXCLUDE: tuple[str, ...] = (
    "cdk.out",
    ".git",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".hypothesis",
    ".jsii-package-cache",
)
