"""GET /heating/parameters/live und POST /heating/parameters/sync.

Live lesen darf jeder angemeldete User; Sync nur Gruppe ``heating-parameter-writers``.
"""
import json
import logging
import os

import boto3

from backend.heating_settings import logic, orchestration, reader
from backend.shared import auth, viessmann_credentials

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(logic.to_jsonable(body)),
    }


def _get_iot_config():
    from backend.heating.iot_data.get_iot_config import get_iot_config
    return get_iot_config(timeout_seconds=8.0, ssl_verify=True)


def _handleget_live(event):
    viessmann_credentials.load_into_env(_get_secrets_client())
    try:
        return _response(200, orchestration.get_live(_get_iot_config()))
    except Exception:
        logger.exception("live read failed")
        return _response(502, {"error": "Viessmann-Fehler beim Lesen der Live-Werte"})


def _handle_post_sync(event):
    if not auth.is_in_group(event):
        return _response(403, {"error": "forbidden"})
    viessmann_credentials.load_into_env(_get_secrets_client())
    pk = f"SYSTEM#{os.environ.get('SYSTEM_ID', 'haus')}"
    try:
        status, body = orchestration.sync_live(
            _get_table(), pk, _get_iot_config(), item_view=reader.project_item)
    except logic.ValidationError as exc:
        return _response(502, {"error": f"Live-Werte ungültig: {exc}"})
    return _response(status, body)


def lambda_handler(event, _context):
    if auth.get_user_id(event) is None:
        return _response(401, {"error": "Unauthorized"})
    route_key = event.get("routeKey", "")
    try:
        if route_key == "GET /heating/parameters/live":
            return _handleget_live(event)
        if route_key == "POST /heating/parameters/sync":
            return _handle_post_sync(event)
        return _response(404, {"error": "Not found"})
    except ValueError:
        logger.exception("configuration error")
        return _response(500, {"error": "Configuration error"})
    except Exception:
        logger.exception("unexpected error")
        return _response(500, {"error": "interner Fehler"})
