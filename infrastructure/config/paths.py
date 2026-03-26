"""Repository layout paths used by CDK asset bundling."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Absolute path to the repository root (parent of the ``infrastructure/`` package)."""
    return Path(__file__).resolve().parent.parent.parent
