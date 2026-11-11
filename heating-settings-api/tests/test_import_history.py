import csv
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import import_history as imp  # noqa: E402

COLUMNS = ["created_at", "event_date", "event_time", "flags", "komfort", "komfort_prev", "normal",
           "normal_prev", "reduziert", "reduziert_prev", "neigung", "neigung_prev", "niveau",
           "niveau_prev", "changed", "raw_len", "prev_mismatch", "unmarked_change", "review"]


def row(**kw):
    base = dict.fromkeys(COLUMNS, "")
    base.update(created_at="2026-10-29T07:40:08", event_date="2026-10-29", event_time="07:40",
                komfort="23.0", normal="22.0", reduziert="16.0", neigung="1.4", niveau="0.0")
    base.update(kw)
    return base


def test_row_to_item_basic():
    item = imp.row_to_item(row(neigung_prev="1.2", changed="neigung"), "SYSTEM#haus")
    assert item["PK"] == "SYSTEM#haus"
    assert item["event_at"] == "2026-10-29T07:40"
    assert item["SK"].startswith("EVT#2026-10-29T07:40#")
    assert item["komfort"] == Decimal(23) and item["neigung"] == Decimal("1.4")
    assert item["prev"] == {"neigung": Decimal("1.2")} and item["changed"] == ["neigung"]
    assert item["created_at"] == "2026-10-29T06:40:08Z"  # Ortszeit (MEZ) -> UTC
    assert item["source"] == "apple-notes-import" and item["quality"] == []


def test_missing_time_and_review_flags_become_quality():
    item = imp.row_to_item(
        row(event_time="", flags="date_uncertain", prev_mismatch="normal", unmarked_change="komfort,niveau"),
        "SYSTEM#haus")
    assert item["event_at"] == "2026-10-29T00:00"
    assert item["quality"] == ["time_unknown", "date_uncertain", "prev_mismatch:normal",
                               "unmarked_change:komfort", "unmarked_change:niveau"]


def test_keys_are_deterministic_and_distinct():
    a = imp.row_to_item(row(), "SYSTEM#haus")
    b = imp.row_to_item(row(), "SYSTEM#haus")
    c = imp.row_to_item(row(event_date="2026-10-30"), "SYSTEM#haus")
    assert a["SK"] == b["SK"] and a["SK"] != c["SK"]


def test_non_integer_temperature_is_rejected():
    with pytest.raises(ValueError):
        imp.row_to_item(row(normal="20.5"), "SYSTEM#haus")


def test_load_items_sorted_and_dry_run_writes_nothing(tmp_path, capsys):
    path = tmp_path / "events.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, COLUMNS)
        w.writeheader()
        w.writerow(row(event_date="2026-10-29"))
        w.writerow(row(event_date="2026-01-05", created_at="2026-01-05T08:00:00"))
    assert imp.main(["--csv", str(path)]) == 0  # Dry-Run: kein --table nötig, keine AWS-Aufrufe
    out = capsys.readouterr().out
    assert "2 Einträge, 2026-01-05T07:40 bis 2026-10-29T07:40" in out
    assert "Dry-Run" in out


def test_apply_requires_table(tmp_path):
    path = tmp_path / "events.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, COLUMNS)
        w.writeheader()
        w.writerow(row())
    with pytest.raises(SystemExit):
        imp.main(["--csv", str(path), "--apply"])
