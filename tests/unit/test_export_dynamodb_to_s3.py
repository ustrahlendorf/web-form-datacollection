from decimal import Decimal

import pytest

from scripts.export_dynamodb_to_s3 import (
    DEFAULT_PREFIX_AUTO_RETRIEVAL_FREQUENT,
    DEFAULT_PREFIX_BASE,
    _build_s3_keys,
    _json_default,
    _month_window_iso_date,
    parse_args,
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


def test_parse_args_submissions_default_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_SUBMISSIONS_TABLE_NAME", "submissions-2025")
    cfg = parse_args(["--bucket", "b", "--year", "2025", "--month", "1"])
    assert cfg.table_name == "submissions-2025"
    assert cfg.prefix_base == DEFAULT_PREFIX_BASE


def test_parse_args_preset_auto_retrieval_frequent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACTIVE_SUBMISSIONS_TABLE_NAME", raising=False)
    monkeypatch.setenv(
        "AUTO_RETRIEVAL_FREQUENT_TABLE_NAME",
        "submissions-auto-retrieval-frequent-dev",
    )
    cfg = parse_args(
        [
            "--bucket",
            "b",
            "--year",
            "2025",
            "--month",
            "1",
            "--preset",
            "auto_retrieval_frequent",
        ]
    )
    assert cfg.table_name == "submissions-auto-retrieval-frequent-dev"
    assert cfg.prefix_base == DEFAULT_PREFIX_AUTO_RETRIEVAL_FREQUENT


def test_parse_args_table_overrides_frequent_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_RETRIEVAL_FREQUENT_TABLE_NAME", "frequent-env")
    cfg = parse_args(
        [
            "--bucket",
            "b",
            "--year",
            "2025",
            "--month",
            "1",
            "--preset",
            "auto_retrieval_frequent",
            "--table",
            "other-table",
        ]
    )
    assert cfg.table_name == "other-table"


def test_parse_args_prefix_overrides_frequent_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_RETRIEVAL_FREQUENT_TABLE_NAME", "x")
    cfg = parse_args(
        [
            "--bucket",
            "b",
            "--year",
            "2025",
            "--month",
            "1",
            "--preset",
            "auto_retrieval_frequent",
            "--prefix-base",
            "custom/prefix",
        ]
    )
    assert cfg.prefix_base == "custom/prefix"


def test_parse_args_frequent_missing_table_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTO_RETRIEVAL_FREQUENT_TABLE_NAME", raising=False)
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--bucket",
                "b",
                "--year",
                "2025",
                "--month",
                "1",
                "--preset",
                "auto_retrieval_frequent",
            ]
        )


