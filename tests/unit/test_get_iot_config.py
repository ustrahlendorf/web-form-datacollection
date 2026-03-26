from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import backend.api_auth.auth as auth_mod
import backend.iot_data.get_iot_config as get_iot_mod

def _make_cfg(*, timeout_seconds: float = 12.5, ssl_verify: bool = True):
    return SimpleNamespace(timeout_seconds=timeout_seconds, ssl_verify=ssl_verify)


def _mock_json_response(payload, *, status_code: int = 200, text: str = ""):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.json = Mock(return_value=payload)
    return resp


def _assert_called_with_bearer_header(call, *, expected_url: str, token: str, timeout_seconds: float, ssl_verify: bool):
    args, kwargs = call
    assert args == (expected_url,)
    assert kwargs["headers"] == {"Authorization": f"Bearer {token}"}
    assert kwargs["timeout"] == float(timeout_seconds)
    assert kwargs["verify"] == bool(ssl_verify)


def test_get_installation_id_sets_bearer_header_and_picks_first() -> None:
    token = "test-token"
    cfg = _make_cfg(timeout_seconds=7.0, ssl_verify=False)
    session = Mock()
    session.get.return_value = _mock_json_response(
        {"data": [{"id": "inst-1"}, {"id": "inst-2"}]},
    )

    installation_id = get_iot_mod.get_installation_id(
        session=session,
        access_token=token,
        cfg=cfg,
        log=None,
        auth_mod=auth_mod,
    )

    assert installation_id == "inst-1"
    _assert_called_with_bearer_header(
        session.get.call_args,
        expected_url=get_iot_mod.IOT_INSTALLATIONS_URL,
        token=token,
        timeout_seconds=cfg.timeout_seconds,
        ssl_verify=cfg.ssl_verify,
    )


def test_get_gateway_serial_sets_bearer_header_and_picks_first() -> None:
    token = "test-token"
    cfg = _make_cfg(timeout_seconds=30.0, ssl_verify=True)
    session = Mock()
    session.get.return_value = _mock_json_response(
        [{"serial": "gw-1"}, {"serial": "gw-2"}],
    )

    gateway_serial = get_iot_mod.get_gateway_serial(
        session=session,
        access_token=token,
        cfg=cfg,
        log=None,
        auth_mod=auth_mod,
    )

    assert gateway_serial == "gw-1"
    _assert_called_with_bearer_header(
        session.get.call_args,
        expected_url=get_iot_mod.IOT_GATEWAYS_URL,
        token=token,
        timeout_seconds=cfg.timeout_seconds,
        ssl_verify=cfg.ssl_verify,
    )


def test_get_device_id_sets_bearer_header_and_picks_first() -> None:
    token = "test-token"
    cfg = _make_cfg(timeout_seconds=3.25, ssl_verify=True)
    session = Mock()
    session.get.return_value = _mock_json_response(
        {"data": [{"id": "dev-1"}, {"id": "dev-2"}]},
    )

    installation_id = "inst-123"
    gateway_serial = "gw-xyz"
    expected_url = get_iot_mod.IOT_DEVICES_URL_TMPL.format(installation_id=installation_id, gateway_serial=gateway_serial)

    device_id = get_iot_mod.get_device_id(
        session=session,
        access_token=token,
        installation_id=installation_id,
        gateway_serial=gateway_serial,
        cfg=cfg,
        log=None,
        auth_mod=auth_mod,
    )

    assert device_id == "dev-1"
    _assert_called_with_bearer_header(
        session.get.call_args,
        expected_url=expected_url,
        token=token,
        timeout_seconds=cfg.timeout_seconds,
        ssl_verify=cfg.ssl_verify,
    )


@pytest.mark.parametrize(
    "which, url, call_fn",
    [
        ("installations", "IOT_INSTALLATIONS_URL", "get_installation_id"),
        ("gateways", "IOT_GATEWAYS_URL", "get_gateway_serial"),
    ],
)
def test_empty_list_raises_clear_error(which: str, url: str, call_fn: str) -> None:
    token = "test-token"
    cfg = _make_cfg()
    session = Mock()
    session.get.return_value = _mock_json_response({"data": []})

    fn = getattr(get_iot_mod, call_fn)
    with pytest.raises(auth_mod.CliError) as e:
        fn(session=session, access_token=token, cfg=cfg, log=None, auth_mod=auth_mod)

    expected_url = getattr(get_iot_mod, url)
    assert "is empty" in str(e.value)
    assert expected_url in str(e.value)
    assert which in str(e.value)


def test_empty_devices_list_raises_clear_error() -> None:
    token = "test-token"
    cfg = _make_cfg()
    session = Mock()
    session.get.return_value = _mock_json_response({"data": []})

    installation_id = "inst-123"
    gateway_serial = "gw-xyz"
    url = get_iot_mod.IOT_DEVICES_URL_TMPL.format(installation_id=installation_id, gateway_serial=gateway_serial)

    with pytest.raises(auth_mod.CliError) as e:
        get_iot_mod.get_device_id(
            session=session,
            access_token=token,
            installation_id=installation_id,
            gateway_serial=gateway_serial,
            cfg=cfg,
            log=None,
            auth_mod=auth_mod,
        )

    assert "is empty" in str(e.value)
    assert url in str(e.value)
    assert "devices" in str(e.value)


@pytest.mark.parametrize(
    "which, payload, call_fn, expected_substring",
    [
        ("installations", {"data": [{"nope": "x"}]}, "get_installation_id", "Missing or invalid 'id'"),
        ("gateways", {"data": [{"nope": "x"}]}, "get_gateway_serial", "Missing or invalid 'serial'"),
    ],
)
def test_missing_required_key_raises_clear_error(which: str, payload, call_fn: str, expected_substring: str) -> None:
    token = "test-token"
    cfg = _make_cfg()
    session = Mock()
    session.get.return_value = _mock_json_response(payload)

    fn = getattr(get_iot_mod, call_fn)
    with pytest.raises(auth_mod.CliError) as e:
        fn(session=session, access_token=token, cfg=cfg, log=None, auth_mod=auth_mod)

    assert expected_substring in str(e.value)
    assert which in str(e.value)


def test_missing_device_id_key_raises_clear_error() -> None:
    token = "test-token"
    cfg = _make_cfg()
    session = Mock()
    session.get.return_value = _mock_json_response({"data": [{"nope": "x"}]})

    with pytest.raises(auth_mod.CliError) as e:
        get_iot_mod.get_device_id(
            session=session,
            access_token=token,
            installation_id="inst-123",
            gateway_serial="gw-xyz",
            cfg=cfg,
            log=None,
            auth_mod=auth_mod,
        )

    assert "Missing or invalid 'id'" in str(e.value)
    assert "devices" in str(e.value)
