"""Tests für GET /heating/parameters/live und POST /heating/parameters/sync."""
import json
import sys
from unittest import mock

import boto3
import pytest
from moto import mock_aws

TABLE = "test-parameters-live"
LIVE = {"komfort": 23, "normal": 20, "reduziert": 16, "neigung": 1.4, "niveau": 0.0,
        "fetched_at": "2026-11-15T10:00:00+00:00"}
GROUP = {"sub": "u1", "cognito:groups": "[heating-parameter-writers]"}


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
        name = "lambdas.heating_parameters_live.handler"
        sys.modules.pop(name, None)
        from lambdas.heating_parameters_live import handler
        handler._table = None
        handler._secrets = mock.MagicMock()
        with mock.patch.object(handler.viessmann_credentials, "load_into_env"), \
                mock.patch.object(handler, "_get_iot_config", return_value={}):
            yield handler
        sys.modules.pop(name, None)


@pytest.fixture
def live():
    state = {"value": dict(LIVE), "error": False}

    def get(cfg, **kw):
        if state["error"]:
            raise RuntimeError("x")
        return dict(state["value"])
    mod = mock.MagicMock(get_heating_parameters=get)
    with mock.patch.dict(sys.modules, {"backend.heating.iot_data.heating_parameters": mod}):
        yield state


def call(api, route, claims=GROUP):
    event = {"routeKey": route, "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}
    res = api.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def stored():
    return boto3.resource("dynamodb").Table(TABLE).scan()["Items"]


def test_live_any_signed_in_user(api, live):
    status, body = call(api, "GET /heating/parameters/live", claims={"sub": "u"})
    assert status == 200 and body["komfort"] == 23 and body["fetched_at"] == LIVE["fetched_at"]


def test_live_error_502(api, live):
    live["error"] = True
    status, body = call(api, "GET /heating/parameters/live")
    assert status == 502 and "error" in body


def test_unauthenticated_401_and_unknown_route_404(api, live):
    assert call(api, "GET /heating/parameters/live", claims={})[0] == 401
    assert call(api, "GET /nope")[0] == 404


def test_sync_requires_group(api, live):
    status, body = call(api, "POST /heating/parameters/sync", claims={"sub": "u"})
    assert status == 403 and body == {"error": "forbidden"} and stored() == []


def test_sync_creates_item_with_source_viessmann_when_table_empty(api, live):
    status, body = call(api, "POST /heating/parameters/sync")
    assert status == 201 and body["status"] == "created"
    assert body["item"]["source"] == "viessmann" and body["item"]["komfort"] == 23
    assert "PK" not in body["item"]
    assert len(stored()) == 1


def test_sync_unchanged_then_created_on_difference(api, live):
    call(api, "POST /heating/parameters/sync")
    status, body = call(api, "POST /heating/parameters/sync")
    assert status == 200 and body["status"] == "unchanged" and len(stored()) == 1
    live["value"]["normal"] = 19
    # Gleiche Minute -> gleicher Schlüssel möglich; hier anderer Hash wegen anderer Werte
    status, body = call(api, "POST /heating/parameters/sync")
    assert status == 201 and body["item"]["normal"] == 19 and body["item"]["prev"] == {"normal": 20}
    assert len(stored()) == 2


def test_sync_live_error_502(api, live):
    live["error"] = True
    status, _ = call(api, "POST /heating/parameters/sync")
    assert status == 502 and stored() == []


def test_sync_incomplete_live_without_history_502(api, live):
    live["value"]["niveau"] = None
    status, body = call(api, "POST /heating/parameters/sync")
    assert status == 502 and "niveau" in body["error"]


def test_sync_out_of_range_live_value_502(api, live):
    live["value"]["komfort"] = 99
    status, body = call(api, "POST /heating/parameters/sync")
    assert status == 502 and stored() == []
