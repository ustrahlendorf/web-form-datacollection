"""POST /heating/parameters – Heizungsparameter in die Gastherme schreiben und erfassen.

Nur Cognito-Gruppe ``heating-parameter-writers``. Logik: backend.heating_settings.orchestration.
"""
import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

from backend.heating_settings import logic, orchestration, reader, writer
from backend.shared import auth, viessmann_credentials

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SOURCE = "web"
_table = None
_secrets = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def _get_secrets_client():
    global _secrets
    if _secrets is None:
        _secrets = boto3.client("secretsmanager")
    return _secrets


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(logic.to_jsonable(body)),
    }


def _get_iot_config():
    from backend.heating.iot_data.get_iot_config import get_iot_config
    return get_iot_config(timeout_seconds=8.0, ssl_verify=True)


def lambda_handler(event, _context):
    if not auth.is_in_group(event):
        return _response(403, {"error": "forbidden"})
    pk = f"SYSTEM#{os.environ.get('SYSTEM_ID', 'haus')}"
    try:
        body = writer.decode_body(event)
        viessmann_credentials.load_into_env(_get_secrets_client())
        status, out = orchestration.write_parameters(
            _get_table(), pk, body, _get_iot_config(),
            source=SOURCE, item_view=reader.project_item,
        )
        return _response(status, out)
    except logic.ValidationError as exc:
        return _response(400, {"error": str(exc)})
    except ClientError:
        logger.exception("AWS error")
        return _response(500, {"error": "interner Fehler"})
    except Exception:
        logger.exception("unexpected error")
        return _response(500, {"error": "interner Fehler"})
