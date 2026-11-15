"""Tests für GET /heating/parameters (moto, kein AWS-Zugriff)."""
import base64
import json
import sys
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

TABLE = "test-parameters"
PK = "SYSTEM#haus"
FULL = {"komfort": 23, "normal": 20, "reduziert": 16, "neigung": 1.4, "niveau": 0.0}


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
        sys.modules.pop("lambdas.heating_parameters.handler", None)
        from lambdas.heating_parameters import handler
        handler._table = None
        yield handler
        sys.modules.pop("lambdas.heating_parameters.handler", None)


def put(event_at, prev=None, **over):
    boto3.resource("dynamodb").Table(TABLE).put_item(Item={
        "PK": PK, "SK": f"EVT#{event_at}#abc", "event_at": event_at,
        "created_at": event_at, **{k: Decimal(str(v)) for k, v in {**FULL, **over}.items()},
        "prev": {k: Decimal(str(v)) for k, v in (prev or {}).items()}, "source": "api",
    })


def get(handler, **qs):
    res = handler.lambda_handler({"routeKey": "GET /heating/parameters", "queryStringParameters": qs or None}, None)
    return res["statusCode"], json.loads(res["body"])


def test_empty_table(api):
    assert get(api) == (200, {"items": [], "count": 0})


def test_newest_first_and_allowlist(api):
    put("2026-01-05T08:00")
    put("2026-01-18T13:00", prev={"neigung": 1.4}, neigung=1.2)
    status, body = get(api)
    assert status == 200 and body["count"] == 2 and "next_token" not in body
    first, second = body["items"]
    assert (first["event_at"], second["event_at"]) == ("2026-01-18T13:00", "2026-01-05T08:00")
    assert first["prev"] == {"neigung": 1.4} and second["prev"] == {}
    assert first["neigung"] == 1.2 and first["komfort"] == 23 and first["source"] == "api"
    for item in body["items"]:
        assert set(item) == {"event_at", "created_at", "komfort", "normal", "reduziert",
                             "neigung", "niveau", "prev", "source"}
        assert "PK" not in item and "SK" not in item


def test_extra_attributes_not_leaked(api):
    boto3.resource("dynamodb").Table(TABLE).put_item(Item={
        "PK": PK, "SK": "EVT#2026-01-01T00:00#x", "event_at": "2026-01-01T00:00", "secret": "x",
    })
    _, body = get(api)
    assert body["items"] == [{"event_at": "2026-01-01T00:00", "prev": {}}]


def test_pagination_with_next_token(api):
    for day in range(1, 6):
        put(f"2026-01-0{day}T08:00")
    status, page1 = get(api, limit="2")
    assert status == 200 and [i["event_at"][:10] for i in page1["items"]] == ["2026-01-05", "2026-01-04"]
    _, page2 = get(api, limit="2", next_token=page1["next_token"])
    assert [i["event_at"][:10] for i in page2["items"]] == ["2026-01-03", "2026-01-02"]
    _, page3 = get(api, limit="2", next_token=page2["next_token"])
    assert [i["event_at"][:10] for i in page3["items"]] == ["2026-01-01"]
    assert "next_token" not in page3


@pytest.mark.parametrize("limit", ["0", "101", "-1", "abc", "1.5"])
def test_invalid_limit(api, limit):
    assert get(api, limit=limit)[0] == 400


def test_limit_bounds_ok(api):
    assert get(api, limit="1")[0] == 200 and get(api, limit="100")[0] == 200


@pytest.mark.parametrize("token", [
    "!!!",
    base64.urlsafe_b64encode(b"not json").decode(),
    base64.urlsafe_b64encode(json.dumps({"PK": "SYSTEM#other", "SK": "EVT#x"}).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps({"PK": PK, "SK": "OTHER#x"}).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps({"PK": PK, "SK": "EVT#x", "extra": 1}).encode()).decode(),
])
def test_invalid_token(api, token):
    assert get(api, next_token=token)[0] == 400


def test_unexpected_error_is_generic(api, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "does-not-exist")
    api._table = None
    status, body = get(api)
    assert status == 500 and body == {"error": "interner Fehler"}
