"""Tests für POST /heating/parameters (moto + gemockte Viessmann-Funktionen, kein AWS-Zugriff)."""
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
GROUP_CLAIMS = {"sub": "u1", "cognito:groups": "[heating-parameter-writers]"}


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
        handler._secrets = mock.MagicMock()
        with mock.patch.object(handler.viessmann_credentials, "load_into_env"), \
                mock.patch.object(handler, "_get_iot_config", return_value={"cfg": 1}):
            yield handler
        sys.modules.pop(name, None)


class Viessmann:
    """Gemockte Viessmann-API: hält den Live-Zustand, apply ändert ihn."""

    def __init__(self, live=None, fail_on=None, live_error=False):
        self.live = dict(live or FULL)
        self.fail_on = fail_on
        self.live_error = live_error
        self.applied_calls = []

    def get(self, iot_config, **kw):
        if self.live_error:
            raise RuntimeError("boom")
        return {**self.live, "fetched_at": "2026-11-15T10:00:00+00:00"}

    def apply(self, changes, iot_config, **kw):
        self.applied_calls.append(dict(changes))
        before = dict(self.live)
        applied, error, partial = {}, None, False
        for k, v in changes.items():
            if k == self.fail_on:
                applied[k] = {"from": before[k], "to": v, "ok": False}
                error, partial = f"Command {k} fehlgeschlagen", bool(applied and any(a["ok"] for a in applied.values()))
                break
            self.live[k] = v
            applied[k] = {"from": before[k], "to": v, "ok": True}
        return {"applied": applied, "live_before": before, "live_after": dict(self.live),
                "error": error, "partial": partial}


@pytest.fixture
def vm():
    v = Viessmann()
    import backend.heating.iot_data as pkg
    mod = mock.MagicMock(get_heating_parameters=v.get, apply_heating_parameters=v.apply)
    with mock.patch.dict(sys.modules, {"backend.heating.iot_data.heating_parameters": mod}), \
            mock.patch.object(pkg, "heating_parameters", mod, create=True):
        yield v


def post(api, body, groups=True, raw=False):
    claims = GROUP_CLAIMS if groups is True else (groups or {"sub": "u1"})
    event = {"routeKey": "POST /heating/parameters",
             "requestContext": {"authorizer": {"jwt": {"claims": claims}}},
             "body": body if raw else json.dumps(body)}
    res = api.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def stored():
    return boto3.resource("dynamodb").Table(TABLE).scan()["Items"]


def test_forbidden_without_group_and_nothing_called(api, vm):
    status, body = post(api, {"komfort": 24}, groups=False)
    assert status == 403 and body == {"error": "forbidden"}
    status, _ = post(api, {"komfort": 24}, groups={"sub": "u", "cognito:groups": "[other]"})
    assert status == 403 and vm.applied_calls == [] and stored() == []


def test_group_claim_as_list_is_accepted(api, vm):
    status, _ = post(api, {"komfort": 24}, groups={"sub": "u", "cognito:groups": ["x", "heating-parameter-writers"]})
    assert status == 201


def test_created_with_verified_values_source_web_and_server_time(api, vm):
    status, body = post(api, {"komfort": 24, "event_at": "1999-01-01T00:00"})
    assert status == 201 and body["status"] == "created"
    item = body["item"]
    assert set(item) == PUBLIC and item["source"] == "web"
    assert item["komfort"] == 24 and item["normal"] == 20 and item["prev"] == {"komfort": 23}
    assert item["event_at"] != "1999-01-01T00:00" and len(item["event_at"]) == 16
    assert body["applied"] == {"komfort": {"from": 23, "to": 24, "ok": True}}
    assert vm.applied_calls == [{"komfort": 24}]
    (row,) = stored()
    assert row["PK"] == PK and row["source"] == "web"


def test_stored_values_are_live_after_not_requested(api, vm):
    orig = vm.apply

    def apply_and_drift(changes, cfg, **kw):
        res = orig(changes, cfg, **kw)
        res["live_after"]["komfort"] = 22  # Gerät hat anderen Wert übernommen
        return res
    vm.apply = apply_and_drift
    import sys as _s
    _s.modules["backend.heating.iot_data.heating_parameters"].apply_heating_parameters = apply_and_drift
    status, body = post(api, {"komfort": 24})
    assert status == 201 and body["item"]["komfort"] == 22


def test_stale_verification_read_still_stores_accepted_target(api, vm):
    """Regression: Therme übernimmt den Wert, der Read direkt danach liefert noch den alten."""
    orig = vm.apply

    def apply_stale(changes, cfg, **kw):
        res = orig(changes, cfg, **kw)
        res["live_after"] = dict(res["live_before"])  # verzögerte Cloud: alter Zustand
        return res
    import sys as _s
    _s.modules["backend.heating.iot_data.heating_parameters"].apply_heating_parameters = apply_stale
    status, body = post(api, {"reduziert": 18})
    assert status == 201 and body["status"] == "created"
    assert body["item"]["reduziert"] == 18 and body["item"]["prev"] == {"reduziert": 16}
    (row,) = stored()
    assert row["reduziert"] == 18


def test_unchanged_does_not_write(api, vm):
    status, body = post(api, {"normal": 20})
    assert status == 200 and body["status"] == "unchanged" and body["state"]["normal"] == 20
    assert vm.applied_calls == [] and stored() == []


def test_only_changed_params_are_applied(api, vm):
    post(api, {"komfort": 23, "normal": 21})
    assert vm.applied_calls == [{"normal": 21}]


@pytest.mark.parametrize("override", [
    {"komfort": 31}, {"komfort": 22.5}, {"neigung": 3.6}, {"niveau": "x"}, {"foo": 1},
])
def test_validation_errors_400(api, vm, override):
    status, body = post(api, override)
    assert status == 400 and "error" in body and vm.applied_calls == [] and stored() == []


@pytest.mark.parametrize("partial", [{"reduziert": 22}, {"komfort": 19}, {"normal": 24}])
def test_plausibility_against_live_state(api, vm, partial):
    status, body = post(api, partial)
    assert status == 400 and "Plausibilität" in body["error"] and vm.applied_calls == []


@pytest.mark.parametrize("raw", ["{nope", "[1]", "{}"])
def test_invalid_body(api, vm, raw):
    status, _ = post(api, raw, raw=True)
    assert status == 400


def test_partial_failure_502_with_item_of_actual_values(api, vm):
    vm.fail_on = "normal"
    status, body = post(api, {"komfort": 25, "normal": 21})
    assert status == 502 and body["partial"] is True
    assert body["applied"]["komfort"]["ok"] is True and body["applied"]["normal"]["ok"] is False
    assert body["item"]["komfort"] == 25 and body["item"]["normal"] == 20
    assert body["item"]["source"] == "web" and body["item"]["prev"] == {"komfort": 23}
    assert len(stored()) == 1


def test_first_command_fails_502_without_item(api, vm):
    vm.fail_on = "komfort"
    status, body = post(api, {"komfort": 25})
    assert status == 502 and body["partial"] is False and body["item"] is None
    assert stored() == []


def test_live_read_failure_502(api, vm):
    vm.live_error = True
    status, body = post(api, {"komfort": 25})
    assert status == 502 and body["partial"] is False and body["item"] is None


def test_conflict_maps_to_409(api, vm):
    err = ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem")
    with mock.patch.object(api._get_table(), "put_item", side_effect=err):
        status, body = post(api, {"komfort": 24})
    assert status == 409 and body == {"error": "Eintrag existiert bereits"}


def test_failure_is_logged_structured_without_secrets(api, vm, caplog):
    vm.fail_on = "komfort"
    with caplog.at_level("INFO"):
        post(api, {"komfort": 25})
    msgs = [r.getMessage() for r in caplog.records if "heating_parameter_write_failed" in r.getMessage()]
    assert msgs and '"parameter": "komfort"' in msgs[0] and "password" not in msgs[0].lower()


def test_unexpected_error_is_generic(api, vm, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "does-not-exist")
    api._table = None
    status, body = post(api, {"komfort": 24})
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
