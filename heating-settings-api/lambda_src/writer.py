"""POST /changes – erfasst eine Änderung der Heizungseinstellungen."""
import base64
import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

import logic

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_table = None


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


def _body(event: dict):
    raw = event.get("body")
    if raw is None:
        raise logic.ValidationError("Body fehlt")
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise logic.ValidationError("kein gültiges JSON")


def handler(event, _context):
    pk = f"SYSTEM#{os.environ.get('SYSTEM_ID', 'haus')}"
    table = _get_table()
    try:
        _, now_local = logic.now_pair()
        parsed = logic.parse_payload(_body(event), now_local)
        sk = logic.sort_key(parsed["event_at"], parsed["request_id"])

        # Wiederholter Aufruf mit gleichem Schlüssel -> idempotent
        existing = table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")
        if existing:
            return _response(200, {"status": "duplicate", "item": existing})

        # Zustand direkt vor diesem Ereignis
        before = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").lt(sk),
            ScanIndexForward=False, Limit=1, ConsistentRead=True,
        )["Items"]
        merged, prev, changed = logic.compute_change(
            parsed["params"], logic.state_of(before[0] if before else None)
        )
        if not changed:
            return _response(200, {"status": "unchanged", "state": merged})

        # Nachträglich erfasst? Dann sind spätere Einträge nicht neu berechnet.
        quality = list(parsed["quality"])
        later = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").gt(sk),
            Limit=1, ConsistentRead=True,
        )["Items"]
        if later:
            quality.append("backdated_before_later_events")

        item = logic.build_item(pk, parsed, merged, prev, changed, quality, now_local)
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
        logger.info("stored %s changed=%s", sk, changed)
        return _response(201, {"status": "created", "item": item})

    except logic.ValidationError as exc:
        return _response(400, {"error": str(exc)})
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _response(409, {"error": "Eintrag existiert bereits"})
        logger.exception("DynamoDB error")
        return _response(500, {"error": "interner Fehler"})
    except Exception:
        logger.exception("unexpected error")
        return _response(500, {"error": "interner Fehler"})
