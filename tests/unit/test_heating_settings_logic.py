from datetime import datetime
from decimal import Decimal

import pytest

from backend.heating_settings import logic

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


def test_date_only_gets_midnight():
    p = parse({"normal": 21, "event_at": "2026-10-29"})
    assert p["event_at"] == "2026-10-29T00:00"
    assert "quality" not in p


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
    item = logic.build_item("SYSTEM#haus", p, merged, prev, NOW_LOCAL)
    assert item["PK"] == "SYSTEM#haus"
    assert item["SK"] == "EVT#2026-10-29T07:40#abc"
    assert item["created_at"] == "2026-11-11T08:00"  # Ortszeit, hh:mm
    assert item["prev"] == {} and changed == list(logic.PARAMS)
    assert set(item) == {"PK", "SK", "event_at", "created_at", "komfort", "normal", "reduziert",
                         "neigung", "niveau", "prev", "source"}


def test_range_bounds_include_whole_day():
    lo, hi = logic.range_bounds("2025-12-01", "2025-12-31")
    sk = logic.sort_key("2025-12-31T23:59", "zzz")
    assert lo <= logic.sort_key("2025-12-01T00:00", "a") and sk <= hi
    assert logic.sort_key("2026-01-01T00:00", "a") > hi


def test_to_jsonable():
    assert logic.to_jsonable({"a": Decimal("1.4"), "b": Decimal("20"), "c": [Decimal("0")]}) == {
        "a": 1.4, "b": 20, "c": [0]}


def test_plausibility_accepts_equal_and_ordered_values():
    logic.check_plausibility(parse({**FULL, "normal": 23, "reduziert": 23})["params"])
    logic.compute_change(parse(FULL)["params"], {})


@pytest.mark.parametrize("override, message", [
    ({"reduziert": 21}, r"reduziert \(21\) darf nicht größer als normal \(20\)"),
    ({"normal": 24}, r"normal \(24\) darf nicht größer als komfort \(23\)"),
    ({"komfort": 19}, r"normal \(20\) darf nicht größer als komfort \(19\)"),
])
def test_plausibility_violation_on_first_entry(override, message):
    with pytest.raises(logic.ValidationError, match=message):
        logic.compute_change(parse({**FULL, **override})["params"], {})


def test_plausibility_checks_partial_update_against_previous_state():
    base = parse(FULL)["params"]
    with pytest.raises(logic.ValidationError, match="Plausibilität"):
        logic.compute_change(parse({"reduziert": 22})["params"], base)
    with pytest.raises(logic.ValidationError, match="Plausibilität"):
        logic.compute_change(parse({"komfort": 18})["params"], base)


def test_plausibility_not_checked_when_nothing_changes():
    legacy = {**parse(FULL)["params"], "reduziert": Decimal("22")}  # Altbestand, nicht plausibel
    _, _, changed = logic.compute_change({"normal": Decimal("20")}, legacy)
    assert changed == []


def test_build_item_source_defaults_to_api_and_is_configurable():
    p = parse({**FULL, "event_at": "2026-10-29T07:40", "request_id": "abc"})
    merged, prev, _ = logic.compute_change(p["params"], {})
    assert logic.build_item("SYSTEM#haus", p, merged, prev, NOW_LOCAL)["source"] == "api"
    assert logic.build_item("SYSTEM#haus", p, merged, prev, NOW_LOCAL, source="web")["source"] == "web"
