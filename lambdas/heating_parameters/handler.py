"""GET /heating/parameters – Heizungsparameter-Historie (Cognito-JWT, nur lesend)."""
import json
import logging
import os

import boto3

from backend.heating_settings import logic, reader

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


def lambda_handler(event, _context):
    pk = f"SYSTEM#{os.environ.get('SYSTEM_ID', 'haus')}"
    try:
        body = reader.list_parameters(
            _get_table(), pk, event.get("queryStringParameters") or {}
        )
        return _response(200, body)
    except logic.ValidationError as exc:
        return _response(400, {"error": str(exc)})
    except Exception:
        logger.exception("unexpected error")
        return _response(500, {"error": "interner Fehler"})
