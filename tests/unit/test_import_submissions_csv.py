from datetime import datetime, timezone
from decimal import Decimal

import pytest

from scripts.import_submissions_csv import (
    _format_iso_utc,
    iter_items_from_csv,
    row_to_item,
)


def test_row_to_item_injects_keys_and_defaults():
    row = {
        "datum": "21.12.2025",
        "uhrzeit": "12:34",
        "betriebsstunden": "100",
        "starts": "5",
        "verbrauch_qm": "1.23",
        # deltas omitted intentionally
    }

    item = row_to_item(
        row,
        user_id="user-123",
        timestamp_utc="2025-12-21T12:34:56Z",
    )

    assert item["user_id"] == "user-123"
    assert item["timestamp_utc"] == "2025-12-21T12:34:56Z"
    assert isinstance(item["submission_id"], str) and len(item["submission_id"]) > 0

    assert item["datum"] == "21.12.2025"
    assert item["uhrzeit"] == "12:34"
    assert item["betriebsstunden"] == 100
    assert item["starts"] == 5
    assert item["verbrauch_qm"] == Decimal("1.23")

    assert item["delta_betriebsstunden"] == 0
    assert item["delta_starts"] == 0
    assert item["delta_verbrauch_qm"] == Decimal("0")


def test_row_to_item_preserves_existing_submission_id_and_deltas():
    row = {
        "submission_id": "abc-123",
        "datum": "21.12.2025",
        "uhrzeit": "12:34",
        "betriebsstunden": "100",
        "starts": "5",
        "verbrauch_qm": "1.23",
        "delta_betriebsstunden": "-1",
        "delta_starts": "2",
        "delta_verbrauch_qm": "-0.50",
    }

    item = row_to_item(
        row,
        user_id="user-123",
        timestamp_utc="2025-12-21T12:34:56Z",
    )

    assert item["submission_id"] == "abc-123"
    assert item["delta_betriebsstunden"] == -1
    assert item["delta_starts"] == 2
    assert item["delta_verbrauch_qm"] == Decimal("-0.50")


def test_format_iso_utc_matches_app_style_seconds_precision():
    dt = datetime(2025, 12, 21, 12, 34, 56, tzinfo=timezone.utc)
    assert _format_iso_utc(dt) == "2025-12-21T12:34:56Z"


def test_iter_items_from_csv_increments_timestamp_by_step_seconds(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "datum,uhrzeit,betriebsstunden,starts,verbrauch_qm\n"
        "21.12.2025,12:00,1,1,0.10\n"
        "21.12.2025,12:10,2,2,0.20\n",
        encoding="utf-8",
    )

    base = datetime(2025, 12, 21, 12, 0, 0, tzinfo=timezone.utc)
    items = list(
        iter_items_from_csv(
            csv_path,
            user_id="user-123",
            start_timestamp_utc=base,
            step_seconds=10,
            delimiter=",",
        )
    )

    assert len(items) == 2
    assert items[0]["timestamp_utc"] == "2025-12-21T12:00:00Z"
    assert items[1]["timestamp_utc"] == "2025-12-21T12:00:10Z"


def test_iter_items_from_csv_requires_positive_step_seconds(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "datum,uhrzeit,betriebsstunden,starts,verbrauch_qm\n"
        "21.12.2025,12:00,1,1,0.10\n",
        encoding="utf-8",
    )
    base = datetime(2025, 12, 21, 12, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        list(
            iter_items_from_csv(
                csv_path,
                user_id="user-123",
                start_timestamp_utc=base,
                step_seconds=0,
                delimiter=",",
            )
        )


def test_iter_items_from_csv_supports_semicolon_delimiter(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text(
        "datum;uhrzeit;betriebsstunden;starts;verbrauch_qm;notes\n"
        "21.12.2025;12:00;1;1;0.10;hello\n",
        encoding="utf-8",
    )

    base = datetime(2025, 12, 21, 12, 0, 0, tzinfo=timezone.utc)
    items = list(
        iter_items_from_csv(
            csv_path,
            user_id="user-123",
            start_timestamp_utc=base,
            step_seconds=10,
            delimiter=";",
        )
    )

    assert len(items) == 1
    assert items[0]["datum"] == "21.12.2025"
    assert items[0]["notes"] == "hello"


