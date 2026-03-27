"""Shared ``Code.from_asset`` exclude list for Lambda bundles from the repo root."""

from __future__ import annotations

# Keep in sync across all stacks that zip the repo (or a subtree) for Lambda.
# Patterns follow CDK asset staging (gitignore-style, paths relative to repo root).
LAMBDA_CODE_ASSET_EXCLUDE: tuple[str, ...] = (
    "cdk.out",
    ".git",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".hypothesis",
    ".jsii-package-cache",
    # Non-runtime trees
    "tests",
    "docs",
    "frontend",
    "infrastructure",
    "scripts",
    ".github",
    ".cursor",
    ".vscode",
    # Dev / build artefacts (may exist under backend/ or lambdas/ after local runs)
    "**/__pycache__",
    "**/*.py[cod]",
    "**/.mypy_cache",
    "**/.ruff_cache",
    ".coverage",
    "htmlcov",
    ".tox",
    "dist",
    "build",
    "**/*.egg-info",
)
