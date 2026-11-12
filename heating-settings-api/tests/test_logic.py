import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda_src"))
import logic  # noqa: E402

NOW_LOCAL = datetime(2026, 11, 11, 8, 0)
FULL = {"komfort": 23, "normal": 20, "reduziert": 16, "neigung": 1.4, "niveau": 0.0}


def parse(body):
    return logic.parse_payload(body, NOW_LOCAL)


def test_full_payload_is_normalized():
    p = parse({**FULL, "event_at": "2026-10-29T07:40"})
    assert p["params"]["neigung"] == Decimal("1.4")
    assert p["params"]["komfort"] == Decimal("23")
    assert p["event_at"] == "2026-10-29T07:40"
    assert len(p["request_id"]) == 10


def test_request_id_is_deterministic_for_same_body():
    body = {**FULL, "event_at": "2026-10-29T07:40"}
    assert parse(body)["request_id"] == parse(dict(body))["request_id"]


def test_date_only_sets_time_unknown():
    p = parse({"normal": 21, "event_at": "2026-10-29"})
    assert p["event_at"] == "2026-10-29T00:00"
    assert p["quality"] == ["time_unknown"]


def test_default_event_at_is_now_local():
    assert parse({"normal": 21})["event_at"] == "2026-11-11T08:00"


@pytest.mark.parametrize("body, msg", [
    ({}, "mindestens ein Parameter"),
    ({"normal": "20"}, "Zahl erwartet"),
    ({"normal": True}, "Zahl erwartet"),
    ({"normal": 20.5}, "ganze Zahl"),
    ({"normal": 99}, "erlaubt sind"),
    ({"neigung": 1.45}, "Nachkommastelle"),
    ({"neigung": 9.0}, "erlaubt sind"),
    ({"normal": 20, "foo": 1}, "unbekannte Felder"),
    ({"normal": 20, "event_at": "29.10.2026"}, "event_at"),
    ({"normal": 20, "event_at": "2026-13-40"}, "event_at"),
    ({"normal": 20, "event_at": "2030-01-01T00:00"}, "Zukunft"),
    ({"normal": 20, "request_id": "a b"}, "request_id"),
])
def test_invalid_payloads(body, msg):
    with pytest.raises(logic.ValidationError, match=msg):
        parse(body)


def test_non_object_body():
    with pytest.raises(logic.ValidationError):
        parse([1, 2])


def test_first_entry_requires_all_params():
    with pytest.raises(logic.ValidationError, match="erster Eintrag"):
        logic.compute_change(parse({"normal": 20})["params"], {})


def test_partial_update_merges_and_tracks_prev():
    base = logic.state_of({"PK": "x", **parse(FULL)["params"]})
    merged, prev, changed = logic.compute_change(parse({"neigung": 1.2})["params"], base)
    assert merged["neigung"] == Decimal("1.2") and merged["normal"] == Decimal("20")
    assert changed == ["neigung"]
    assert prev == {"neigung": Decimal("1.4")}


def test_unchanged_values_are_not_reported():
    base = parse(FULL)["params"]
    _, prev, changed = logic.compute_change(parse({"normal": 20, "komfort": 22})["params"], base)
    assert changed == ["komfort"] and prev == {"komfort": Decimal("23")}
    _, _, changed = logic.compute_change(parse({"normal": 20})["params"], base)
    assert changed == []


def test_build_item_shape():
    p = parse({**FULL, "event_at": "2026-10-29T07:40", "request_id": "abc"})
    merged, prev, changed = logic.compute_change(p["params"], {})
    item = logic.build_item("SYSTEM#haus", p, merged, prev, changed, p["quality"], NOW_LOCAL)
    assert item["PK"] == "SYSTEM#haus"
    assert item["SK"] == "EVT#2026-10-29T07:40#abc"
    assert item["created_at"] == "2026-11-11T08:00"  # Ortszeit, hh:mm
    assert item["prev"] == {} and set(item["changed"]) == set(logic.PARAMS)


def test_range_bounds_include_whole_day():
    lo, hi = logic.range_bounds("2025-12-01", "2025-12-31")
    sk = logic.sort_key("2025-12-31T23:59", "zzz")
    assert lo <= logic.sort_key("2025-12-01T00:00", "a") and sk <= hi
    assert logic.sort_key("2026-01-01T00:00", "a") > hi


def test_to_jsonable():
    assert logic.to_jsonable({"a": Decimal("1.4"), "b": Decimal("20"), "c": [Decimal("0")]}) == {
        "a": 1.4, "b": 20, "c": [0]}
