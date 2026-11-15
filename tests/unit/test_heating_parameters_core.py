"""Unit tests for backend.heating.iot_data.heating_parameters (mocked HTTP)."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

import backend.heating.iot_data.heating_parameters as hp
from backend.heating.iot_data.get_iot_config import IotConfig


def _cfg() -> IotConfig:
    return IotConfig(access_token="tok", installation_id="i", gateway_serial="g", device_id="d")


def _features(komfort=22, normal=20, reduziert=16, slope=1.4, shift=0):
    def prog(v):
        return {"properties": {"temperature": {"type": "number", "value": v, "unit": "celsius"}}}

    return [
        {"feature": "heating.circuits.0.operating.programs.comfort", **prog(komfort)},
        {"feature": "heating.circuits.0.operating.programs.normal", **prog(normal)},
        {"feature": "heating.circuits.0.operating.programs.reduced", **prog(reduziert)},
        {"feature": "heating.circuits.0.heating.curve",
         "properties": {"slope": {"value": slope}, "shift": {"value": shift}}},
    ]


def _resp(status=200):
    r = MagicMock()
    r.status_code = status
    r.text = "err" if status >= 400 else ""
    return r


def test_read_mapping_and_missing():
    live = hp.get_heating_parameters(_cfg(), features_data=_features())
    assert (live["komfort"], live["normal"], live["reduziert"]) == (22, 20, 16)
    assert live["neigung"] == 1.4 and live["niveau"] == 0
    assert "fetched_at" in live
    empty = hp.get_heating_parameters(_cfg(), features_data=[])
    assert all(empty[k] is None for k in hp.PARAMETER_NAMES)


def test_read_uses_single_batch_call():
    with patch.object(hp, "get_device_features", return_value=_features()) as g:
        hp.get_heating_parameters(_cfg())
    assert g.call_count == 1


def test_invalid_name_and_value():
    with pytest.raises(ValueError):
        hp.apply_heating_parameters({"foo": 1}, _cfg())
    with pytest.raises(ValueError):
        hp.apply_heating_parameters({"komfort": "x"}, _cfg())
    with pytest.raises(ValueError):
        hp.apply_heating_parameters({"niveau": 1.5}, _cfg())


def test_only_changed_written_and_verified():
    reads = [_features(), _features(komfort=23)]
    with patch.object(hp, "get_device_features", side_effect=reads), \
         patch.object(hp.requests, "post", return_value=_resp()) as post:
        res = hp.apply_heating_parameters(
            {"komfort": Decimal("23"), "normal": 20, "reduziert": 16}, _cfg())
    assert post.call_count == 1
    url = post.call_args.args[0]
    assert url.endswith("operating.programs.comfort/commands/setTemperature")
    assert post.call_args.kwargs["json"] == {"targetTemperature": 23}
    assert res["applied"] == {"komfort": {"from": 22, "to": 23, "ok": True}}
    assert res["live_after"]["komfort"] == 23
    assert res["error"] is None and res["partial"] is False


def test_unchanged_writes_nothing():
    with patch.object(hp, "get_device_features", return_value=_features()) as g, \
         patch.object(hp.requests, "post") as post:
        res = hp.apply_heating_parameters({"komfort": 22, "neigung": 1.4}, _cfg())
    assert post.call_count == 0 and g.call_count == 1
    assert res["applied"] == {} and res["partial"] is False


def test_setcurve_single_command_with_partner_from_live():
    reads = [_features(), _features(slope=1.6)]
    with patch.object(hp, "get_device_features", side_effect=reads), \
         patch.object(hp.requests, "post", return_value=_resp()) as post:
        res = hp.apply_heating_parameters({"neigung": 1.6}, _cfg())
    assert post.call_count == 1
    assert post.call_args.args[0].endswith("heating.curve/commands/setCurve")
    assert post.call_args.kwargs["json"] == {"slope": 1.6, "shift": 0}
    assert res["applied"]["neigung"]["ok"] is True and "niveau" not in res["applied"]


def test_setcurve_both_changed_one_command():
    with patch.object(hp, "get_device_features", side_effect=[_features(), _features(slope=1.2, shift=2)]), \
         patch.object(hp.requests, "post", return_value=_resp()) as post:
        res = hp.apply_heating_parameters({"neigung": 1.2, "niveau": 2}, _cfg())
    assert post.call_count == 1
    assert post.call_args.kwargs["json"] == {"slope": 1.2, "shift": 2}
    assert set(res["applied"]) == {"neigung", "niveau"}


def test_partial_failure_aborts_and_verifies():
    reads = [_features(), _features(komfort=23)]
    posts = [_resp(), _resp(500)]
    with patch.object(hp, "get_device_features", side_effect=reads), \
         patch.object(hp.requests, "post", side_effect=posts) as post:
        res = hp.apply_heating_parameters(
            {"komfort": 23, "normal": 21, "neigung": 1.0}, _cfg())
    assert post.call_count == 2  # curve never attempted
    assert res["applied"]["komfort"]["ok"] is True
    assert res["applied"]["normal"]["ok"] is False
    assert "neigung" not in res["applied"]
    assert "HTTP 500" in res["error"]
    assert res["partial"] is True
    assert res["live_after"]["komfort"] == 23 and res["live_after"]["normal"] == 20


def test_first_command_fails_not_partial():
    with patch.object(hp, "get_device_features", side_effect=[_features(), _features()]), \
         patch.object(hp.requests, "post", return_value=_resp(500)):
        res = hp.apply_heating_parameters({"komfort": 23}, _cfg())
    assert res["error"] and res["partial"] is False


def test_shift_non_integer_allowed_when_configured():
    with patch.object(hp, "SHIFT_INTEGER_ONLY", False), \
         patch.object(hp, "get_device_features", side_effect=[_features(), _features(shift=1.5)]), \
         patch.object(hp.requests, "post", return_value=_resp()) as post:
        hp.apply_heating_parameters({"niveau": 1.5}, _cfg())
    assert post.call_args.kwargs["json"] == {"slope": 1.4, "shift": 1.5}
