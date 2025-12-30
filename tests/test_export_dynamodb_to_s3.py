from decimal import Decimal

import pytest

from scripts.export_dynamodb_to_s3 import (
    _build_s3_keys,
    _json_default,
    _month_window_iso_date,
)


def test_month_window_iso_date_basic() -> None:
    start, end = _month_window_iso_date(2025, 1)
    assert start == "2025-01-01"
    assert end == "2025-02-01"


def test_month_window_iso_date_december_rollover() -> None:
    start, end = _month_window_iso_date(2025, 12)
    assert start == "2025-12-01"
    assert end == "2026-01-01"


def test_month_window_iso_date_invalid_month() -> None:
    with pytest.raises(ValueError):
        _month_window_iso_date(2025, 0)
    with pytest.raises(ValueError):
        _month_window_iso_date(2025, 13)


def test_build_s3_keys_layout() -> None:
    data_key, manifest_key = _build_s3_keys(
        prefix_base="exports/submissions",
        year=2025,
        month=3,
        snapshot_at="2025-03-31T235959Z",
    )
    assert data_key.endswith("/part-000.jsonl.gz")
    assert manifest_key.endswith("/manifest.json")
    assert "year=2025/month=03" in data_key
    assert "snapshot_at=2025-03-31T235959Z" in data_key


def test_json_default_decimal() -> None:
    assert _json_default(Decimal("1.23")) == "1.23"


def test_json_default_unsupported_type() -> None:
    with pytest.raises(TypeError):
        _json_default(object())


