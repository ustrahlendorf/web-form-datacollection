"""Tests for src.viessmann_submit module."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.viessmann_submit import (
    _viessmann_to_submission_values,
    _datum_to_iso,
    store_viessmann_submission,
)


def test_viessmann_to_submission_values_basic() -> None:
    """Map Viessmann response to submission field values."""
    values = {
        "gas_consumption_m3_today": 1.5,
        "gas_consumption_m3_yesterday": 2.3,
        "betriebsstunden": 1234,
        "starts": 56,
        "supply_temp": 45.2,
        "outside_temp": -1.5,
        "fetched_at": "2025-02-23T06:00:00",
    }
    retrieval = datetime(2025, 2, 23, 6, 0, 0, tzinfo=timezone.utc)
    mapped = _viessmann_to_submission_values(values, retrieval_time=retrieval)

    # datum = yesterday (22.02.2025)
    assert mapped["datum"] == "22.02.2025"
    assert mapped["uhrzeit"] == "06:00"
    assert mapped["betriebsstunden"] == 1234
    assert mapped["starts"] == 56
    assert mapped["verbrauch_qm"] == Decimal("2.3")
    assert mapped["vorlauf_temp"] == Decimal("45.2")
    assert mapped["aussentemp"] == Decimal("-1.5")


def test_viessmann_to_submission_values_verbrauch_exceeds_20() -> None:
    """Auto-retrieved verbrauch_qm may exceed 20 (relaxed validation)."""
    values = {
        "gas_consumption_m3_yesterday": 25.5,
        "betriebsstunden": 100,
        "starts": 10,
        "supply_temp": None,
        "outside_temp": None,
    }
    mapped = _viessmann_to_submission_values(values)
    assert mapped["verbrauch_qm"] == Decimal("25.5")


def test_viessmann_to_submission_values_fallback_to_today() -> None:
    """When yesterday is None, fall back to today."""
    values = {
        "gas_consumption_m3_today": 1.0,
        "gas_consumption_m3_yesterday": None,
        "betriebsstunden": 0,
        "starts": 0,
    }
    mapped = _viessmann_to_submission_values(values)
    assert mapped["verbrauch_qm"] == Decimal("1.0")


def test_datum_to_iso() -> None:
    """Convert dd.mm.yyyy to YYYY-MM-DD."""
    assert _datum_to_iso("22.02.2025") == "2025-02-22"


def test_store_viessmann_submission_skips_duplicate() -> None:
    """Skip storing when datum_iso already exists."""
    mock_table = MagicMock()
    mock_table.query.side_effect = [
        {"Items": [{"datum_iso": "2025-02-22", "user_id": "user-1"}], "Count": 1},
    ]

    values = {
        "gas_consumption_m3_yesterday": 2.0,
        "betriebsstunden": 100,
        "starts": 5,
        "supply_temp": 40.0,
        "outside_temp": 5.0,
    }

    stored, submission_id = store_viessmann_submission(
        user_id="user-1",
        values=values,
        table=mock_table,
        skip_if_duplicate=True,
    )

    assert stored is False
    assert submission_id is None
    mock_table.put_item.assert_not_called()


def test_store_viessmann_submission_stores_new() -> None:
    """Store new submission when no duplicate."""
    mock_table = MagicMock()
    mock_table.query.side_effect = [
        {"Items": [], "Count": 0},  # duplicate check
        {"Items": [], "Count": 0},  # previous submission query
    ]

    values = {
        "gas_consumption_m3_yesterday": 2.0,
        "betriebsstunden": 100,
        "starts": 5,
        "supply_temp": 40.0,
        "outside_temp": 5.0,
    }

    stored, submission_id = store_viessmann_submission(
        user_id="user-1",
        values=values,
        table=mock_table,
        skip_if_duplicate=True,
    )

    assert stored is True
    assert submission_id is not None
    mock_table.put_item.assert_called_once()
    item = mock_table.put_item.call_args[1]["Item"]
    assert item["user_id"] == "user-1"
    assert item["betriebsstunden"] == 100
    assert item["starts"] == 5
    assert item["verbrauch_qm"] == Decimal("2.0")
