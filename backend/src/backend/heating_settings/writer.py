"""Schreib-Logik für Heizungsparameter-Änderungen (gemeinsam für IAM- und JWT-Route).

Idempotent über den Sortierschlüssel (event_at + request_id); der Vorgängerzustand wird
per Query ermittelt, neue Einträge per bedingtem PutItem angelegt.
"""
import base64
import json
import logging

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.heating_settings import logic

logger = logging.getLogger()


def decode_body(event: dict):
    raw = event.get("body")
    if raw is None:
        raise logic.ValidationError("Body fehlt")
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise logic.ValidationError("kein gültiges JSON")


def write_change(table, pk: str, body, source: str = "api", item_view=None) -> tuple[int, dict]:
    """Verarbeitet eine Änderung und liefert (HTTP-Status, Antwort-Body).

    ``item_view`` projiziert Items für die Antwort (Standard: unverändert).
    Wirft ``logic.ValidationError`` bei ungültiger Eingabe.
    """
    view = item_view or (lambda item: item)
    _, now_local = logic.now_pair()
    parsed = logic.parse_payload(body, now_local)
    sk = logic.sort_key(parsed["event_at"], parsed["request_id"])

    # Wiederholter Aufruf mit gleichem Schlüssel -> idempotent
    existing = table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")
    if existing:
        return 200, {"status": "duplicate", "item": view(existing)}

    # Zustand direkt vor diesem Ereignis
    before = table.query(
        KeyConditionExpression=Key("PK").eq(pk) & Key("SK").lt(sk),
        ScanIndexForward=False, Limit=1, ConsistentRead=True,
    )["Items"]
    merged, prev, changed = logic.compute_change(
        parsed["params"], logic.state_of(before[0] if before else None)
    )
    if not changed:
        return 200, {"status": "unchanged", "state": merged}

    item = logic.build_item(pk, parsed, merged, prev, now_local, source=source)
    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return 409, {"error": "Eintrag existiert bereits"}
        raise
    logger.info("stored %s changed=%s source=%s", sk, changed, source)
    return 201, {"status": "created", "item": view(item)}
