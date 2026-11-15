"""POST /heating/parameters – Heizungsparameter erfassen (Cognito-JWT)."""
import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

from backend.heating_settings import logic, reader, writer

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SOURCE = "web"
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
        status, body = writer.write_change(
            _get_table(), pk, writer.decode_body(event),
            source=SOURCE, item_view=reader.project_item,
        )
        return _response(status, body)
    except logic.ValidationError as exc:
        return _response(400, {"error": str(exc)})
    except ClientError:
        logger.exception("DynamoDB error")
        return _response(500, {"error": "interner Fehler"})
    except Exception:
        logger.exception("unexpected error")
        return _response(500, {"error": "interner Fehler"})
