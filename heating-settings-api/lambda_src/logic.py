"""Reine Geschäftslogik (ohne AWS-Abhängigkeiten, daher gut testbar).

Datenmodell: Ein Item = eine Änderung der Heizungseinstellungen mit dem
kompletten neuen Zustand. ``prev`` enthält die Alt-Werte der geänderten
Parameter, ``changed`` deren Namen.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

PARAMS = ("komfort", "normal", "reduziert", "neigung", "niveau")

# name: (min, max, Nachkommastellen)
LIMITS = {
    "komfort": (5, 30, 0),
    "normal": (5, 30, 0),
    "reduziert": (5, 30, 0),
    "neigung": (Decimal("0.2"), Decimal("3.5"), 1),
    "niveau": (Decimal("-10"), Decimal("10"), 1),
}

LOCAL_TZ = ZoneInfo("Europe/Berlin")
_EVENT_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_UPPER = "￿"  # größer als jedes Zeichen in Sortierschlüsseln


class ValidationError(ValueError):
    """Ungültige Eingabe (führt zu HTTP 400)."""


def sort_key(event_at: str, request_id: str) -> str:
    return f"EVT#{event_at}#{request_id}"


def range_bounds(date_from: str | None, date_to: str | None) -> tuple[str, str]:
    """Untere/obere Sortierschlüssel-Grenze (inklusive) für einen Zeitraum."""
    lo = f"EVT#{date_from}" if date_from else "EVT#"
    hi = f"EVT#{date_to}{_UPPER}" if date_to else f"EVT#{_UPPER}"
    return lo, hi


def check_date_param(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not _EVENT_AT_RE.match(value):
        raise ValidationError(f"{name}: erwartet YYYY-MM-DD oder YYYY-MM-DDTHH:MM")
    try:
        datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"{name}: ungültiges Datum")
    return value


def _to_decimal(name: str, value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValidationError(f"{name}: Zahl erwartet")
    try:
        # Über str, damit 1.4 nicht als 1.399999… landet
        dec = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError(f"{name}: ungültige Zahl")
    if not dec.is_finite():
        raise ValidationError(f"{name}: ungültige Zahl")
    lo, hi, places = LIMITS[name]
    quant = Decimal(1).scaleb(-places)
    if dec != dec.quantize(quant):
        raise ValidationError(
            f"{name}: höchstens {places} Nachkommastelle(n) erlaubt"
            if places else f"{name}: ganze Zahl erwartet"
        )
    if not (lo <= dec <= hi):
        raise ValidationError(f"{name}: erlaubt sind {lo} bis {hi}")
    return dec.quantize(quant)


def parse_event_at(value, now_local: datetime) -> tuple[str, list[str]]:
    """Liefert (event_at, quality). Ohne Angabe gilt die aktuelle Ortszeit."""
    quality: list[str] = []
    if value is None:
        return now_local.strftime("%Y-%m-%dT%H:%M"), quality
    if not isinstance(value, str) or not _EVENT_AT_RE.match(value):
        raise ValidationError("event_at: erwartet YYYY-MM-DD oder YYYY-MM-DDTHH:MM")
    if "T" not in value:
        value += "T00:00"
        quality.append("time_unknown")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise ValidationError("event_at: ungültiges Datum/Uhrzeit")
    if parsed > now_local.replace(tzinfo=None) + timedelta(days=1):
        raise ValidationError("event_at: liegt in der Zukunft")
    return value, quality


def parse_payload(body, now_local: datetime) -> dict:
    """Prüft den Request-Body. Teilangaben sind erlaubt (mind. ein Parameter)."""
    if not isinstance(body, dict):
        raise ValidationError("JSON-Objekt erwartet")
    unknown = set(body) - set(PARAMS) - {"event_at", "request_id"}
    if unknown:
        raise ValidationError(f"unbekannte Felder: {', '.join(sorted(unknown))}")
    params = {k: _to_decimal(k, body[k]) for k in PARAMS if k in body}
    if not params:
        raise ValidationError("mindestens ein Parameter erforderlich: " + ", ".join(PARAMS))
    event_at, quality = parse_event_at(body.get("event_at"), now_local)

    request_id = body.get("request_id")
    if request_id is None:
        canonical = json.dumps(
            {"event_at": event_at, **{k: str(v) for k, v in sorted(params.items())}},
            sort_keys=True,
        )
        request_id = hashlib.sha256(canonical.encode()).hexdigest()[:10]
    elif not isinstance(request_id, str) or not _REQUEST_ID_RE.match(request_id):
        raise ValidationError("request_id: 1-64 Zeichen aus A-Z a-z 0-9 _ -")

    return {"params": params, "event_at": event_at, "request_id": request_id, "quality": quality}


def state_of(item: dict | None) -> dict:
    """Extrahiert den Parameterzustand aus einem gespeicherten Item."""
    if not item:
        return {}
    return {k: item[k] for k in PARAMS if k in item}


def compute_change(params: dict, base: dict) -> tuple[dict, dict, list[str]]:
    """Gibt (neuer Zustand, prev, changed) zurück.

    Ohne Vorgängerzustand müssen alle Parameter angegeben werden.
    """
    merged = {**base, **params}
    missing = [k for k in PARAMS if k not in merged]
    if missing:
        raise ValidationError(
            "erster Eintrag: alle Parameter erforderlich, es fehlen: " + ", ".join(missing)
        )
    changed = [k for k in PARAMS if k in params and base.get(k) != params[k]]
    prev = {k: base[k] for k in changed if k in base}
    return merged, prev, changed


def build_item(pk: str, parsed: dict, merged: dict, prev: dict, changed: list[str],
               quality: list[str], now_utc: datetime) -> dict:
    return {
        "PK": pk,
        "SK": sort_key(parsed["event_at"], parsed["request_id"]),
        "event_at": parsed["event_at"],
        "created_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **{k: merged[k] for k in PARAMS},
        "prev": prev,
        "changed": changed,
        "quality": quality,
        "source": "api",
    }


def now_pair() -> tuple[datetime, datetime]:
    utc = datetime.now(timezone.utc)
    return utc, utc.astimezone(LOCAL_TZ)


def to_jsonable(value):
    """Decimal -> int/float, Sets -> Listen (für json.dumps)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    return value
