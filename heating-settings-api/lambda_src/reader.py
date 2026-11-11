"""GET /current und GET /changes – liest Einstellungen aus DynamoDB."""
import base64
import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

import logic

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_table = None
DEFAULT_LIMIT, MAX_LIMIT = 50, 100


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(logic.to_jsonable(body)),
    }


def _encode_token(key: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def _decode_token(token: str, pk: str) -> dict:
    try:
        key = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        ok = (isinstance(key, dict) and key.get("PK") == pk
              and isinstance(key.get("SK"), str) and key["SK"].startswith("EVT#")
              and set(key) == {"PK", "SK"})
    except Exception:
        ok = False
    if not ok:
        raise logic.ValidationError("next_token ungültig")
    return key


def _current(table, pk):
    items = table.query(
        KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("EVT#"),
        ScanIndexForward=False, Limit=1, ConsistentRead=True,
    )["Items"]
    if not items:
        return _response(404, {"error": "noch keine Einträge"})
    return _response(200, items[0])


def _changes(table, pk, qs):
    date_from = logic.check_date_param(qs.get("from"), "from")
    date_to = logic.check_date_param(qs.get("to"), "to")
    order = qs.get("order", "asc")
    if order not in ("asc", "desc"):
        raise logic.ValidationError("order: asc oder desc")
    try:
        limit = int(qs.get("limit", DEFAULT_LIMIT))
    except ValueError:
        raise logic.ValidationError("limit: ganze Zahl erwartet")
    if not 1 <= limit <= MAX_LIMIT:
        raise logic.ValidationError(f"limit: 1 bis {MAX_LIMIT}")

    lo, hi = logic.range_bounds(date_from, date_to)
    kwargs = dict(
        KeyConditionExpression=Key("PK").eq(pk) & Key("SK").between(lo, hi),
        ScanIndexForward=(order == "asc"), Limit=limit,
    )
    if qs.get("next_token"):
        kwargs["ExclusiveStartKey"] = _decode_token(qs["next_token"], pk)
    result = table.query(**kwargs)
    body = {"items": result["Items"], "count": len(result["Items"])}
    if "LastEvaluatedKey" in result:
        body["next_token"] = _encode_token(result["LastEvaluatedKey"])
    return _response(200, body)


def handler(event, _context):
    pk = f"SYSTEM#{os.environ.get('SYSTEM_ID', 'haus')}"
    table = _get_table()
    route = event.get("routeKey", "")
    try:
        if route == "GET /current":
            return _current(table, pk)
        if route == "GET /changes":
            return _changes(table, pk, event.get("queryStringParameters") or {})
        return _response(404, {"error": "unbekannte Route"})
    except logic.ValidationError as exc:
        return _response(400, {"error": str(exc)})
    except Exception:
        logger.exception("unexpected error")
        return _response(500, {"error": "interner Fehler"})
