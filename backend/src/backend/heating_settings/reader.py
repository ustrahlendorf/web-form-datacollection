"""Lese-Logik für die Heizungsparameter-Tabelle (Paginierung, Projektion).

Wird vom JWT-geschützten Endpunkt ``GET /heating/parameters`` und vom IAM-geschützten
Reader genutzt. Reine Funktionen plus eine Query gegen eine übergebene Tabelle.
"""
import base64
import json

from boto3.dynamodb.conditions import Key

from backend.heating_settings import logic

DEFAULT_LIMIT, MAX_LIMIT = 50, 100

# Allowlist: nur diese Attribute verlassen das Backend (insbesondere nicht PK/SK).
PUBLIC_FIELDS = ("event_at", "created_at", *logic.PARAMS, "prev", "source")


def encode_token(key: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def decode_token(token: str, pk: str) -> dict:
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


def parse_limit(value) -> int:
    try:
        limit = int(DEFAULT_LIMIT if value is None else value)
    except (TypeError, ValueError):
        raise logic.ValidationError("limit: ganze Zahl erwartet")
    if not 1 <= limit <= MAX_LIMIT:
        raise logic.ValidationError(f"limit: 1 bis {MAX_LIMIT}")
    return limit


def project_item(item: dict) -> dict:
    """Reduziert ein Tabellen-Item auf die öffentlichen Felder (``prev`` immer ein dict)."""
    out = {k: item[k] for k in PUBLIC_FIELDS if k in item}
    out.setdefault("prev", {})
    return out


def list_parameters(table, pk: str, qs: dict | None) -> dict:
    """Neueste Einträge zuerst; ``next_token`` nur, wenn es weitere Einträge geben kann."""
    qs = qs or {}
    limit = parse_limit(qs.get("limit"))
    kwargs = dict(
        KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("EVT#"),
        ScanIndexForward=False, Limit=limit,
    )
    if qs.get("next_token"):
        kwargs["ExclusiveStartKey"] = decode_token(qs["next_token"], pk)
    result = table.query(**kwargs)
    items = [project_item(i) for i in result["Items"]]
    body = {"items": items, "count": len(items)}
    if "LastEvaluatedKey" in result:
        body["next_token"] = encode_token(result["LastEvaluatedKey"])
    return body
