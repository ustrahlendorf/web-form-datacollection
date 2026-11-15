"""Unit-Tests für backend.shared.auth und viessmann_credentials."""
import json
from unittest import mock

import pytest

from backend.shared import auth, viessmann_credentials


def ev(claims):
    return {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}


@pytest.mark.parametrize("raw, expected", [
    (None, []), ("[a heating-parameter-writers]", ["a", "heating-parameter-writers"]),
    ("heating-parameter-writers", ["heating-parameter-writers"]), (["x", "y"], ["x", "y"]),
    ("a,b", ["a", "b"]), ("", []),
])
def test_parse_groups(raw, expected):
    assert auth.parse_groups(raw) == expected


def test_is_in_group_exact_match_only():
    assert auth.is_in_group(ev({"cognito:groups": "[heating-parameter-writers]"}))
    assert not auth.is_in_group(ev({"cognito:groups": "[heating-parameter-writers-x]"}))
    assert not auth.is_in_group({})


def test_legacy_claims_location():
    event = {"requestContext": {"authorizer": {"claims": {"sub": "s"}}}}
    assert auth.get_user_id(event) == "s"


def test_load_into_env(monkeypatch):
    monkeypatch.setenv("VIESSMANN_CREDENTIALS_SECRET_ARN", "arn:x")
    client = mock.MagicMock()
    client.get_secret_value.return_value = {"SecretString": json.dumps(
        {"VIESSMANN_CLIENT_ID": "c", "VIESSMANN_EMAIL": "e", "VIESSMANN_PASSWORD": "p"})}
    viessmann_credentials.load_into_env(client)
    import os
    assert os.environ["VIESSMANN_CLIENT_ID"] == "c"
    for k in ("VIESSMANN_CLIENT_ID", "VIESSMANN_EMAIL", "VIESSMANN_PASSWORD"):
        monkeypatch.delenv(k, raising=False)


def test_load_into_env_errors(monkeypatch):
    monkeypatch.delenv("VIESSMANN_CREDENTIALS_SECRET_ARN", raising=False)
    with pytest.raises(ValueError):
        viessmann_credentials.load_into_env(mock.MagicMock())
    monkeypatch.setenv("VIESSMANN_CREDENTIALS_SECRET_ARN", "arn:x")
    client = mock.MagicMock()
    client.get_secret_value.return_value = {"SecretString": json.dumps({"VIESSMANN_CLIENT_ID": "c"})}
    with pytest.raises(ValueError, match="VIESSMANN_EMAIL"):
        viessmann_credentials.load_into_env(client)
