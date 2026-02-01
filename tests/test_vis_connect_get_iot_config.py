"""
Offline unit tests for `vis-connect/python-auth/get_iot_config.py`.

We do not perform network calls:
- OAuth calls (/authorize, /token) are satisfied by a fake Session.post().
- IoT list endpoints are satisfied by a fake Session.get().
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import requests


def _load_get_iot_config_module():
    """
    Load the module by file path because `vis-connect/` contains hyphens.
    """
    repo_root = Path(__file__).resolve().parents[1]  # web-form-verbrauch/
    mod_path = repo_root / "vis-connect" / "python-auth" / "get_iot_config.py"
    spec = importlib.util.spec_from_file_location("vis_connect_get_iot_config", mod_path)
    assert spec and spec.loader, f"Failed to create import spec for {mod_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def _make_json_response(payload, *, status_code: int = 200, url: str = "https://example.invalid") -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(payload).encode("utf-8")  # noqa: SLF001 - test helper
    resp.encoding = "utf-8"
    resp.url = url
    return resp


def _make_redirect_response(*, location: str, status_code: int = 302) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp.headers["Location"] = location
    resp.url = "https://iam.viessmann-climatesolutions.com/idp/v3/authorize"
    resp._content = b""  # noqa: SLF001 - test helper
    return resp


class FakeSession:
    def __init__(self, mod, *, installations_payload, gateways_payload, devices_payload) -> None:
        self._mod = mod
        self._installations_payload = installations_payload
        self._gateways_payload = gateways_payload
        self._devices_payload = devices_payload
        self.get_calls: list[dict] = []

    def post(self, url: str, **kwargs):  # noqa: ANN001 - mimic requests.Session.post
        if url == self._mod._load_auth_module().AUTHORIZE_URL:
            return _make_redirect_response(location="http://localhost:4200/?code=fake-auth-code")
        if url == self._mod._load_auth_module().TOKEN_URL:
            return _make_json_response({"access_token": "FAKE_ACCESS_TOKEN"}, url=url)
        raise AssertionError(f"Unexpected POST url: {url}")

    def get(self, url: str, **kwargs):  # noqa: ANN001 - mimic requests.Session.get
        self.get_calls.append({"url": url, "kwargs": kwargs})
        if url == self._mod.IOT_INSTALLATIONS_URL:
            return _make_json_response(self._installations_payload, url=url)
        if url == self._mod.IOT_GATEWAYS_URL:
            return _make_json_response(self._gateways_payload, url=url)
        if url.startswith("https://api.viessmann-climatesolutions.com/iot/v2/equipment/installations/") and url.endswith("/devices"):
            return _make_json_response(self._devices_payload, url=url)
        raise AssertionError(f"Unexpected GET url: {url}")


@pytest.fixture()
def mod():
    return _load_get_iot_config_module()


def test_get_iot_config_happy_path_picks_first_and_sets_bearer_header(monkeypatch, mod) -> None:
    monkeypatch.setenv("VIESSMANN_CLIENT_ID", "client-id")
    monkeypatch.setenv("VIESSMANN_EMAIL", "user@example.com")
    monkeypatch.setenv("VIESSMANN_PASSWORD", "pw")
    monkeypatch.setenv("VIESSMANN_CALLBACK_URI", "http://localhost:4200/")

    fake_session = FakeSession(
        mod,
        installations_payload={"data": [{"id": "inst-1"}]},
        gateways_payload={"data": [{"serial": "gw-serial-1"}]},
        devices_payload={"data": [{"id": "dev-1"}]},
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: fake_session)

    cfg = mod.get_iot_config()

    assert cfg.access_token == "FAKE_ACCESS_TOKEN"
    assert cfg.installation_id == "inst-1"
    assert cfg.gateway_serial == "gw-serial-1"
    assert cfg.device_id == "dev-1"

    # Verify Bearer header is used for ALL IoT GETs.
    assert len(fake_session.get_calls) == 3
    for call in fake_session.get_calls:
        headers = call["kwargs"].get("headers") or {}
        assert headers.get("Authorization") == "Bearer FAKE_ACCESS_TOKEN"


def test_get_iot_config_empty_installations_raises(monkeypatch, mod) -> None:
    monkeypatch.setenv("VIESSMANN_CLIENT_ID", "client-id")
    monkeypatch.setenv("VIESSMANN_EMAIL", "user@example.com")
    monkeypatch.setenv("VIESSMANN_PASSWORD", "pw")
    monkeypatch.setenv("VIESSMANN_CALLBACK_URI", "http://localhost:4200/")

    fake_session = FakeSession(
        mod,
        installations_payload={"data": []},
        gateways_payload={"data": [{"serial": "gw"}]},
        devices_payload={"data": [{"id": "dev"}]},
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: fake_session)

    with pytest.raises(mod._load_auth_module().CliError):
        mod.get_iot_config()


def test_get_iot_config_missing_installation_id_raises(monkeypatch, mod) -> None:
    monkeypatch.setenv("VIESSMANN_CLIENT_ID", "client-id")
    monkeypatch.setenv("VIESSMANN_EMAIL", "user@example.com")
    monkeypatch.setenv("VIESSMANN_PASSWORD", "pw")
    monkeypatch.setenv("VIESSMANN_CALLBACK_URI", "http://localhost:4200/")

    fake_session = FakeSession(
        mod,
        installations_payload={"data": [{}]},  # missing "id"
        gateways_payload={"data": [{"serial": "gw"}]},
        devices_payload={"data": [{"id": "dev"}]},
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: fake_session)

    with pytest.raises(mod._load_auth_module().CliError):
        mod.get_iot_config()

