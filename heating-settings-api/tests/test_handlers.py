"""Handler-Tests gegen eine DynamoDB-Attrappe (moto) – kein echter AWS-Zugriff."""
import base64
import json
import re
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda_src"))

TABLE = "test-settings"
PK = "SYSTEM#haus"
FULL = {"komfort": 23, "normal": 20, "reduziert": 16, "neigung": 1.4, "niveau": 0.0}


@pytest.fixture
def handlers(monkeypatch):
    """Frische moto-Tabelle und frisch importierte Handler pro Test."""
    # Niemals echte Zugangsdaten/Profile verwenden
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.setenv("SYSTEM_ID", "haus")
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        for name in ("writer", "reader"):
            sys.modules.pop(name, None)
        import reader, writer  # noqa: E401
        writer._table = reader._table = None
        yield writer, reader
        for name in ("writer", "reader"):
            sys.modules.pop(name, None)


def post(writer, body, raw=False, **extra):
    event = {"routeKey": "POST /changes", "body": body if raw else json.dumps(body), **extra}
    res = writer.handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def get(reader, route, **qs):
    res = reader.handler({"routeKey": f"GET {route}", "queryStringParameters": qs or None}, None)
    return res["statusCode"], json.loads(res["body"])


def seed(writer, *events):
    for event_at, params in events:
        status, _ = post(writer, {"event_at": event_at, **params})
        assert status == 201


def items():
    return boto3.resource("dynamodb").Table(TABLE).scan()["Items"]


# ----------------------------------------------------------------- writer

def test_first_entry_created_with_all_params(handlers):
    writer, _ = handlers
    status, body = post(writer, {**FULL, "event_at": "2026-01-05T08:00"})
    assert status == 201 and body["status"] == "created"
    item = body["item"]
    assert item["PK"] == PK and item["SK"].startswith("EVT#2026-01-05T08:00#")
    assert item["prev"] == {} and set(item["changed"]) == set(FULL)
    assert item["source"] == "api" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", item["created_at"])
    assert len(items()) == 1


def test_partial_update_merges_state_and_tracks_prev(handlers):
    writer, _ = handlers
    seed(writer, ("2026-01-05T08:00", FULL))
    status, body = post(writer, {"event_at": "2026-01-18T13:00", "neigung": 1.2, "normal": 21})
    assert status == 201
    item = body["item"]
    assert item["komfort"] == 23 and item["reduziert"] == 16  # aus Vorgängerzustand
    assert item["neigung"] == 1.2 and item["normal"] == 21
    assert set(item["changed"]) == {"neigung", "normal"}
    assert item["prev"] == {"neigung": 1.4, "normal": 20}
    assert item["quality"] == []


def test_unchanged_values_write_nothing(handlers):
    writer, _ = handlers
    seed(writer, ("2026-01-05T08:00", FULL))
    status, body = post(writer, {"event_at": "2026-02-01T08:00", "neigung": 1.4})
    assert (status, body["status"]) == (200, "unchanged")
    assert len(items()) == 1


def test_replay_is_idempotent(handlers):
    writer, _ = handlers
    payload = {**FULL, "event_at": "2026-01-05T08:00"}
    assert post(writer, payload)[0] == 201
    status, body = post(writer, payload)
    assert (status, body["status"]) == (200, "duplicate")
    assert len(items()) == 1


def test_same_minute_different_request_ids_both_stored(handlers):
    writer, _ = handlers
    seed(writer, ("2026-01-05T08:00", FULL))
    a = post(writer, {"event_at": "2026-01-06T08:00", "normal": 21, "request_id": "a"})
    b = post(writer, {"event_at": "2026-01-06T08:00", "normal": 22, "request_id": "b"})
    assert a[0] == 201 and b[0] == 201 and len(items()) == 3


def test_backdated_entry_is_flagged(handlers):
    writer, _ = handlers
    seed(writer, ("2026-03-01T08:00", FULL))
    status, body = post(writer, {**FULL, "event_at": "2026-01-01T08:00", "normal": 18})
    assert status == 201
    assert body["item"]["quality"] == ["backdated_before_later_events"]
    assert body["item"]["prev"] == {}  # nichts davor


def test_date_only_event_is_flagged_time_unknown(handlers):
    writer, _ = handlers
    status, body = post(writer, {**FULL, "event_at": "2026-01-05"})
    assert status == 201 and body["item"]["event_at"] == "2026-01-05T00:00"
    assert "time_unknown" in body["item"]["quality"]


@pytest.mark.parametrize("payload, msg", [
    ({"komfort": 99}, "erlaubt sind"),
    ({"normal": 20.5}, "ganze Zahl"),
    ({"normal": 20}, "erster Eintrag"),
    ({"foo": 1}, "unbekannte Felder"),
    ({}, "mindestens ein Parameter"),
    ({"normal": 20, "event_at": "2999-01-01T00:00"}, "Zukunft"),
])
def test_validation_errors_return_400_and_write_nothing(handlers, payload, msg):
    writer, _ = handlers
    status, body = post(writer, payload)
    assert status == 400 and msg in body["error"]
    assert items() == []


def test_body_problems(handlers):
    writer, _ = handlers
    assert post(writer, "kein json", raw=True)[0] == 400
    assert post(writer, "[1,2]", raw=True)[0] == 400
    assert writer.handler({"routeKey": "POST /changes"}, None)["statusCode"] == 400  # Body fehlt
    encoded = base64.b64encode(json.dumps(FULL).encode()).decode()
    status, _ = post(writer, encoded, raw=True, isBase64Encoded=True)
    assert status == 201


def test_race_on_existing_key_returns_409(handlers, monkeypatch):
    writer, _ = handlers
    payload = {**FULL, "event_at": "2026-01-05T08:00", "request_id": "race"}
    assert post(writer, payload)[0] == 201
    # get_item "übersieht" den Eintrag (anderer Schreiber war schneller) -> Bedingung im put_item greift
    table = writer._get_table()
    monkeypatch.setattr(table, "get_item", lambda **kw: {})
    status, body = post(writer, payload)
    assert status == 409 and "existiert bereits" in body["error"]
    assert len(items()) == 1


# ----------------------------------------------------------------- reader

def test_current_404_when_empty(handlers):
    _, reader = handlers
    status, body = get(reader, "/current")
    assert status == 404 and "noch keine" in body["error"]


def test_current_returns_latest_by_event_time_not_insert_order(handlers):
    writer, reader = handlers
    seed(writer, ("2026-03-01T08:00", FULL))
    post(writer, {**FULL, "event_at": "2026-01-01T08:00", "normal": 18})  # nachträglich eingefügt
    status, body = get(reader, "/current")
    assert status == 200 and body["event_at"] == "2026-03-01T08:00"
    assert isinstance(body["neigung"], float) and isinstance(body["komfort"], int)  # Decimal -> JSON


def _seed_series(writer):
    seed(writer, ("2025-12-01T08:00", FULL))
    for i, day in enumerate(["2025-12-15", "2026-01-10", "2026-01-20", "2026-02-05"]):
        post(writer, {"event_at": f"{day}T08:00", "normal": 21 + i})


def test_changes_range_is_inclusive_and_ordered(handlers):
    writer, reader = handlers
    _seed_series(writer)
    status, body = get(reader, "/changes", **{"from": "2026-01-10", "to": "2026-01-20"})
    assert status == 200 and body["count"] == 2
    assert [i["event_at"] for i in body["items"]] == ["2026-01-10T08:00", "2026-01-20T08:00"]
    _, desc = get(reader, "/changes", order="desc", limit="2")
    assert [i["event_at"] for i in desc["items"]] == ["2026-02-05T08:00", "2026-01-20T08:00"]


def test_changes_pagination_walks_all_items(handlers):
    writer, reader = handlers
    _seed_series(writer)
    seen, token = [], None
    for _ in range(10):
        qs = {"limit": "2", **({"next_token": token} if token else {})}
        status, body = get(reader, "/changes", **qs)
        assert status == 200
        seen += [i["event_at"] for i in body["items"]]
        token = body.get("next_token")
        if not token:
            break
    assert seen == sorted(seen) and len(seen) == 5 and len(set(seen)) == 5


@pytest.mark.parametrize("qs", [
    {"limit": "0"}, {"limit": "101"}, {"limit": "abc"}, {"order": "sideways"},
    {"from": "29.10.2026"}, {"to": "2026-13-45"}, {"next_token": "!!!"},
])
def test_changes_invalid_params_return_400(handlers, qs):
    _, reader = handlers
    assert get(reader, "/changes", **qs)[0] == 400


def test_next_token_for_foreign_partition_is_rejected(handlers):
    _, reader = handlers
    forged = base64.urlsafe_b64encode(json.dumps({"PK": "SYSTEM#anderes", "SK": "EVT#2020"}).encode()).decode()
    status, body = get(reader, "/changes", next_token=forged)
    assert status == 400 and "next_token" in body["error"]


def test_unknown_route_404(handlers):
    _, reader = handlers
    assert get(reader, "/nope")[0] == 404
