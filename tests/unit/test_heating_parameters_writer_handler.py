"""Tests für POST /heating/parameters (moto, kein AWS-Zugriff)."""
import base64
import json
import sys
from unittest import mock

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

TABLE = "test-parameters-writer"
PK = "SYSTEM#haus"
FULL = {"komfort": 23, "normal": 20, "reduziert": 16, "neigung": 1.4, "niveau": 0.0}
PUBLIC = {"event_at", "created_at", "komfort", "normal", "reduziert", "neigung", "niveau", "prev", "source"}


@pytest.fixture
def api(monkeypatch):
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
        name = "lambdas.heating_parameters_writer.handler"
        sys.modules.pop(name, None)
        from lambdas.heating_parameters_writer import handler
        handler._table = None
        yield handler
        sys.modules.pop(name, None)


def post(api, body, raw=False, **extra):
    event = {"routeKey": "POST /heating/parameters",
             "body": body if raw else json.dumps(body), **extra}
    res = api.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def stored():
    return boto3.resource("dynamodb").Table(TABLE).scan()["Items"]


def test_created_with_source_web_and_no_keys_in_response(api):
    status, body = post(api, {**FULL, "event_at": "2026-10-29T07:40"})
    assert status == 201 and body["status"] == "created"
    item = body["item"]
    assert set(item) == PUBLIC
    assert item["source"] == "web" and item["prev"] == {} and item["event_at"] == "2026-10-29T07:40"
    assert "PK" not in item and "SK" not in item
    (row,) = stored()
    assert row["source"] == "web" and row["PK"] == PK and row["SK"].startswith("EVT#2026-10-29T07:40#")


def test_created_at_is_set_by_server(api):
    _, body = post(api, {**FULL, "event_at": "2026-10-29T07:40", "created_at": "1999-01-01T00:00"})
    assert body["error"].startswith("unbekannte Felder")
    _, ok = post(api, {**FULL, "event_at": "2026-10-29T07:40"})
    assert ok["item"]["created_at"] != "1999-01-01T00:00" and len(ok["item"]["created_at"]) == 16


def test_event_at_defaults_to_now_without_time_is_midnight(api):
    _, body = post(api, {**FULL, "event_at": "2026-10-29"})
    assert body["item"]["event_at"] == "2026-10-29T00:00"
    _, body = post(api, {**FULL, "komfort": 24})
    assert len(body["item"]["event_at"]) == 16


def test_partial_update_merges_previous_state_and_tracks_prev(api):
    post(api, {**FULL, "event_at": "2026-10-01T08:00"})
    status, body = post(api, {"neigung": 1.2, "event_at": "2026-10-02T08:00"})
    assert status == 201
    item = body["item"]
    assert item["neigung"] == 1.2 and item["komfort"] == 23 and item["normal"] == 20
    assert item["prev"] == {"neigung": 1.4}


def test_unchanged(api):
    post(api, {**FULL, "event_at": "2026-10-01T08:00"})
    status, body = post(api, {"normal": 20, "event_at": "2026-10-02T08:00"})
    assert status == 200 and body["status"] == "unchanged"
    assert body["state"]["normal"] == 20
    assert len(stored()) == 1


def test_duplicate_with_same_body_and_event_at(api):
    body = {**FULL, "event_at": "2026-10-29T07:40"}
    assert post(api, body)[0] == 201
    status, again = post(api, body)
    assert status == 200 and again["status"] == "duplicate"
    assert set(again["item"]) == PUBLIC
    assert len(stored()) == 1


@pytest.mark.parametrize("first, partial", [
    (FULL, {"reduziert": 22}),
    (FULL, {"komfort": 19}),
    (FULL, {"normal": 24}),
])
def test_plausibility_violation_with_partial_update(api, first, partial):
    post(api, {**first, "event_at": "2026-10-01T08:00"})
    status, body = post(api, {**partial, "event_at": "2026-10-02T08:00"})
    assert status == 400 and "Plausibilität" in body["error"]
    assert len(stored()) == 1


def test_plausibility_violation_on_first_entry(api):
    status, body = post(api, {**FULL, "reduziert": 25})
    assert status == 400 and "reduziert (25) darf nicht größer als normal (20)" in body["error"]
    assert stored() == []


@pytest.mark.parametrize("override", [
    {"komfort": 31}, {"komfort": 4}, {"komfort": 22.5}, {"neigung": 3.6}, {"neigung": 1.25},
    {"niveau": -10.1}, {"niveau": "x"}, {"normal": True},
])
def test_range_and_format_violations(api, override):
    status, _ = post(api, {**FULL, **override})
    assert status == 400 and stored() == []


def test_missing_parameter_on_first_entry(api):
    status, body = post(api, {"komfort": 23})
    assert status == 400 and "erster Eintrag" in body["error"]


@pytest.mark.parametrize("event", [
    {"routeKey": "POST /heating/parameters"},
    {"routeKey": "POST /heating/parameters", "body": "{nope"},
    {"routeKey": "POST /heating/parameters", "body": "[1]"},
    {"routeKey": "POST /heating/parameters", "body": "{}"},
])
def test_invalid_or_missing_body(api, event):
    res = api.lambda_handler(event, None)
    assert res["statusCode"] == 400 and "error" in json.loads(res["body"])


def test_base64_body(api):
    raw = base64.b64encode(json.dumps({**FULL, "event_at": "2026-10-29T07:40"}).encode()).decode()
    status, _ = post(api, raw, raw=True, isBase64Encoded=True)
    assert status == 201


def test_event_at_in_future_is_rejected(api):
    status, body = post(api, {**FULL, "event_at": "2999-01-01T00:00"})
    assert status == 400 and "Zukunft" in body["error"]


def test_conflict_maps_to_409(api):
    err = ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem")
    table = api._get_table()
    with mock.patch.object(table, "put_item", side_effect=err):
        status, body = post(api, {**FULL, "event_at": "2026-10-29T07:40"})
    assert status == 409 and body == {"error": "Eintrag existiert bereits"}


def test_unexpected_error_is_generic(api, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "does-not-exist")
    api._table = None
    status, body = post(api, {**FULL, "event_at": "2026-10-29T07:40"})
    assert status == 500 and body == {"error": "interner Fehler"}


def test_iam_writer_still_writes_source_api(monkeypatch):
    """Die bestehende IAM-Route bleibt bei source=api und liefert weiter das volle Item."""
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setenv("TABLE_NAME", TABLE)
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        sys.modules.pop("lambdas.heating_settings_writer.handler", None)
        from lambdas.heating_settings_writer import handler
        handler._table = None
        res = handler.lambda_handler({"body": json.dumps({**FULL, "event_at": "2026-10-29T07:40"})}, None)
        body = json.loads(res["body"])
        sys.modules.pop("lambdas.heating_settings_writer.handler", None)
    assert res["statusCode"] == 201 and body["item"]["source"] == "api" and "PK" in body["item"]
