"""Orchestrierung: Heizungsparameter zwischen Web-GUI, Viessmann-API und DynamoDB.

Schreib-Ablauf: validieren -> Live lesen -> Diff -> Commands -> Verifikations-Read ->
DynamoDB-Eintrag mit den verifizierten Werten. Die Viessmann-Funktionen werden lazy
importiert bzw. können für Tests injiziert werden.
"""
import json
import logging
from datetime import datetime
from decimal import Decimal

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.heating_settings import logic

logger = logging.getLogger()

WRITE_OK_EVENT = "heating_parameter_write"
WRITE_FAILED_EVENT = "heating_parameter_write_failed"  # Ziel des CloudWatch-MetricFilters


def get_live(iot_config, get_fn=None):
    if get_fn is None:
        from backend.heating.iot_data.heating_parameters import get_heating_parameters as get_fn
    return get_fn(iot_config, timeout_seconds=8.0, ssl_verify=True)


def _apply(changes, iot_config, apply_fn=None):
    if apply_fn is None:
        from backend.heating.iot_data.heating_parameters import apply_heating_parameters as apply_fn
    return apply_fn(changes, iot_config, timeout_seconds=8.0, ssl_verify=True)


def to_decimal(name: str, value) -> Decimal | None:
    """Live-Wert (float/int/None) -> Decimal in der Genauigkeit des Parameters."""
    if value is None or isinstance(value, bool):
        return None
    _, _, places = logic.LIMITS[name]
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places))


def live_state(live: dict) -> dict:
    """Nicht-None-Parameterwerte eines Live-Reads als Decimal-Zustand."""
    out = {}
    for k in logic.PARAMS:
        d = to_decimal(k, (live or {}).get(k))
        if d is not None:
            out[k] = d
    return out


def latest_item(table, pk: str) -> dict | None:
    items = table.query(
        KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("EVT#"),
        ScanIndexForward=False, Limit=1, ConsistentRead=True,
    )["Items"]
    return items[0] if items else None


def _put(table, item: dict) -> bool:
    """Bedingtes PutItem; False bei bereits existierendem Schlüssel."""
    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def _log_write(event: str, level: int, **fields) -> None:
    """Strukturierter Logeintrag (nie Tokens/Credentials übergeben)."""
    logger.log(level, json.dumps({"event": event, **logic.to_jsonable(fields)}, default=str))


def _error(status: int, message: str, **extra) -> tuple[int, dict]:
    return status, {"error": message, **extra}


def write_parameters(table, pk: str, body, iot_config, *, item_view=None, source: str = "web",
                     get_fn=None, apply_fn=None, now_local: datetime | None = None
                     ) -> tuple[int, dict]:
    """POST /heating/parameters. Wirft ``logic.ValidationError`` bei ungültiger Eingabe."""
    view = item_view or (lambda i: i)
    now_local = now_local or logic.now_pair()[1]
    if isinstance(body, dict):  # Client-event_at wird ignoriert, Server setzt "jetzt"
        body = {k: v for k, v in body.items() if k != "event_at"}
    parsed = logic.parse_payload(body, now_local)
    params = parsed["params"]

    try:
        live_before = get_live(iot_config, get_fn)
    except Exception:
        logger.exception("live read failed")
        _log_write(WRITE_FAILED_EVENT, logging.ERROR, stage="read_live", requested=params)
        return _error(502, "Viessmann-Fehler beim Lesen der Live-Werte", partial=False,
                      applied={}, item=None)

    base = live_state(live_before)
    if any(k not in base for k in logic.PARAMS):  # fehlende Live-Werte aus DB ergänzen
        base = {**logic.state_of(latest_item(table, pk)), **base}
    merged, _prev, changed = logic.compute_change(params, base)
    if not changed:
        return 200, {"status": "unchanged", "state": merged}

    changes = {k: params[k] for k in changed}
    try:
        result = _apply(logic.to_jsonable(changes), iot_config, apply_fn)
    except ValueError as exc:  # Eingabe von der Therme nicht darstellbar (z. B. niveau-Schrittweite)
        return _error(400, str(exc), partial=False, applied={}, item=None)
    except Exception:
        logger.exception("apply failed")
        _log_write(WRITE_FAILED_EVENT, logging.ERROR, stage="apply", requested=changes)
        return _error(502, "Viessmann-Fehler beim Schreiben", partial=False, applied={}, item=None)

    applied = result.get("applied") or {}
    live_after = result.get("live_after") or {}
    error = result.get("error")

    # Verifizierter Zustand: live_after; Fallback je Parameter auf Ziel (ok) bzw. Ausgangswert
    verified = {}
    for k in logic.PARAMS:
        d = to_decimal(k, live_after.get(k))
        if d is None:
            d = merged[k] if (k not in changes or applied.get(k, {}).get("ok")) \
                else base.get(k, merged[k])
        verified[k] = d
    actual = [k for k in logic.PARAMS if k not in base or base[k] != verified[k]]
    prev = {k: base[k] for k in actual if k in base}

    for k in changes:
        a = applied.get(k, {})
        _log_write(WRITE_OK_EVENT if a.get("ok") else WRITE_FAILED_EVENT,
                   logging.INFO if a.get("ok") else logging.ERROR,
                   parameter=k, old=a.get("from", base.get(k)), new=a.get("to", changes[k]),
                   ok=bool(a.get("ok")), error=error)

    item = None
    if actual:
        parsed = {"event_at": now_local.strftime("%Y-%m-%dT%H:%M"), "request_id": parsed["request_id"]}
        item = logic.build_item(pk, parsed, verified, prev, now_local, source=source)
        if not _put(table, item):
            return _error(409, "Eintrag existiert bereits")

    if error or result.get("partial"):
        return 502, {"error": error or "Teilfehler", "partial": bool(result.get("partial")),
                     "applied": applied, "item": view(item) if item else None}
    if item is None:
        return 200, {"status": "unchanged", "state": verified}
    return 201, {"status": "created", "item": view(item), "applied": applied}


def sync_live(table, pk: str, iot_config, *, item_view=None, get_fn=None,
              now_local: datetime | None = None) -> tuple[int, dict]:
    """POST /heating/parameters/sync: Live-Werte als Eintrag (source=viessmann) übernehmen."""
    view = item_view or (lambda i: i)
    now_local = now_local or logic.now_pair()[1]
    try:
        live = get_live(iot_config, get_fn)
    except Exception:
        logger.exception("live read failed")
        return _error(502, "Viessmann-Fehler beim Lesen der Live-Werte")

    base = logic.state_of(latest_item(table, pk))
    state = {**base, **live_state(live)}
    missing = [k for k in logic.PARAMS if k not in state]
    if missing:
        return _error(502, "Live-Werte unvollständig: " + ", ".join(missing))

    changed = [k for k in logic.PARAMS if base.get(k) != state[k]]
    if not changed:
        return 200, {"status": "unchanged", "state": state}

    parsed = logic.parse_payload(logic.to_jsonable(state), now_local)
    prev = {k: base[k] for k in changed if k in base}
    item = logic.build_item(pk, parsed, state, prev, now_local, source="viessmann")
    if not _put(table, item):
        return _error(409, "Eintrag existiert bereits")
    _log_write("heating_parameter_sync", logging.INFO, changed=changed)
    return 201, {"status": "created", "item": view(item)}
