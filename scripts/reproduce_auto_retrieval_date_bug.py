#!/usr/bin/env python3
"""
Verify auto-retrieval date semantics locally.

Simulates: EventBridge triggers at 2026-03-10 06:00:45 UTC.
Expected:
  - timestamp_utc = retrieval time (2026-03-10T06:00:45Z)
  - datum/datum_iso = retrieval date (2026-03-10)
  - verbrauch_qm = gas value from yesterday (gas_consumption_m3_yesterday)
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

# Ensure project root and backend package root are on path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "backend", "src"))

# Simulate retrieval at 2026-03-10 06:00:45 UTC (matches user's observed timestamp_utc)
RETRIEVAL_TIME = datetime(2026, 3, 10, 6, 0, 45, tzinfo=timezone.utc)


def main() -> None:
    from backend.viessmann.viessmann_submit import (
        _viessmann_to_submission_values,
        store_viessmann_submission,
    )

    values = {
        "gas_consumption_m3_yesterday": 1.5,
        "betriebsstunden": 100,
        "starts": 50,
        "supply_temp": 45.0,
        "outside_temp": 5.0,
    }

    # Call with retrieval_time to simulate a scheduled Lambda run (UTC wall clock).
    mapped = _viessmann_to_submission_values(values, retrieval_time=RETRIEVAL_TIME)
    print(f"mapped datum={mapped['datum']} uhrzeit={mapped['uhrzeit']}")

    mock_table = MagicMock()
    mock_table.query.side_effect = [
        {"Items": [], "Count": 0},
        {"Items": [], "Count": 0},
    ]

    stored, _ = store_viessmann_submission(
        user_id="test-user",
        values=values,
        table=mock_table,
        skip_if_duplicate=True,
        retrieval_time=RETRIEVAL_TIME,
    )

    if stored and mock_table.put_item.called:
        item = mock_table.put_item.call_args[1]["Item"]
        print(f"Stored: timestamp_utc={item['timestamp_utc']} datum={item['datum']} datum_iso={item['datum_iso']} verbrauch_qm={item['verbrauch_qm']}")
        assert item["timestamp_utc"] == "2026-03-10T06:00:45Z", "timestamp_utc must be retrieval time"
        assert item["datum_iso"] == "2026-03-10", "datum_iso must be retrieval date"
        assert item["verbrauch_qm"] == Decimal("1.5"), "verbrauch_qm = gas_consumption_m3_yesterday"
        print("OK: datum/timestamp_utc=retrieval, verbrauch_qm=from yesterday")
    else:
        print("No item stored (check mock_table setup)")


if __name__ == "__main__":
    main()
