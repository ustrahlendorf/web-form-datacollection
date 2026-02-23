"""
Shared logic for storing Viessmann API data as DynamoDB submissions.

Used by the auto-retrieval Lambda to map heating values to the submission schema,
compute deltas, check for duplicates, and store. Validation is relaxed for
auto-retrieved data (verbrauch_qm may exceed 20 m³).
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Optional

from src.models import create_submission


def _format_datum(dt: datetime) -> str:
    """Format datetime as dd.mm.yyyy."""
    return dt.strftime("%d.%m.%Y")


def _format_uhrzeit(dt: datetime) -> str:
    """Format datetime as hh:mm (24-hour)."""
    return dt.strftime("%H:%M")


def _viessmann_to_submission_values(
    values: dict[str, Any],
    retrieval_time: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Map Viessmann API response to submission field values.

    Uses yesterday's date for datum since gas_consumption_m3_yesterday refers to
    the previous day. Uhrzeit is from retrieval time.

    Args:
        values: Dict from get_heating_values() with keys:
            gas_consumption_m3_today, gas_consumption_m3_yesterday,
            betriebsstunden, starts, supply_temp, outside_temp, fetched_at
        retrieval_time: Optional override for datum/uhrzeit (default: now UTC)

    Returns:
        Dict with datum, uhrzeit, betriebsstunden, starts, verbrauch_qm,
        vorlauf_temp, aussentemp
    """
    now = retrieval_time or datetime.now(timezone.utc)
    # gas_consumption_m3_yesterday = consumption for yesterday; datum = yesterday
    yesterday = now - timedelta(days=1)
    datum = _format_datum(yesterday)
    uhrzeit = _format_uhrzeit(now)

    verbrauch_raw = values.get("gas_consumption_m3_yesterday")
    if verbrauch_raw is None:
        verbrauch_raw = values.get("gas_consumption_m3_today") or 0
    verbrauch_qm = Decimal(str(verbrauch_raw))

    betriebsstunden = values.get("betriebsstunden")
    if betriebsstunden is None:
        betriebsstunden = 0
    betriebsstunden = int(betriebsstunden)

    starts = values.get("starts")
    if starts is None:
        starts = 0
    starts = int(starts)

    vorlauf_temp = None
    if values.get("supply_temp") is not None:
        vorlauf_temp = Decimal(str(values["supply_temp"]))

    aussentemp = None
    if values.get("outside_temp") is not None:
        aussentemp = Decimal(str(values["outside_temp"]))

    return {
        "datum": datum,
        "uhrzeit": uhrzeit,
        "betriebsstunden": betriebsstunden,
        "starts": starts,
        "verbrauch_qm": verbrauch_qm,
        "vorlauf_temp": vorlauf_temp,
        "aussentemp": aussentemp,
    }


def _datum_to_iso(datum: str) -> str:
    """Convert dd.mm.yyyy to YYYY-MM-DD."""
    d = datetime.strptime(datum.strip(), "%d.%m.%Y").date()
    return d.isoformat()


def store_viessmann_submission(
    user_id: str,
    values: dict[str, Any],
    table: Any,
    *,
    skip_if_duplicate: bool = True,
) -> tuple[bool, Optional[str]]:
    """
    Store Viessmann heating values as a DynamoDB submission.

    Maps values to submission schema, computes deltas vs previous submission,
    and optionally skips if a submission for the same datum_iso already exists.

    Args:
        user_id: Cognito user_id (sub) for the installation owner
        values: Dict from get_heating_values()
        table: DynamoDB Table resource
        skip_if_duplicate: If True, skip storing when datum_iso already exists

    Returns:
        Tuple of (stored: bool, submission_id: Optional[str]).
        stored=False when skipped as duplicate.
    """
    mapped = _viessmann_to_submission_values(values)
    datum_iso = _datum_to_iso(mapped["datum"])

    if skip_if_duplicate:
        try:
            result = table.query(
                KeyConditionExpression="user_id = :user_id",
                FilterExpression="datum_iso = :datum_iso",
                ExpressionAttributeValues={
                    ":user_id": user_id,
                    ":datum_iso": datum_iso,
                },
                Limit=1,
            )
            items = result.get("Items") or []
            if items:
                return (False, None)
        except Exception as e:
            print(f"Duplicate check failed: {e}, proceeding with store")

    # Query previous submission for deltas
    previous_item = None
    try:
        prev_result = table.query(
            KeyConditionExpression="user_id = :user_id",
            ExpressionAttributeValues={":user_id": user_id},
            ScanIndexForward=False,
            Limit=1,
        )
        items = (prev_result or {}).get("Items") or []
        if items and isinstance(items[0], dict):
            previous_item = items[0]
    except Exception as e:
        print(f"DynamoDB query error (previous submission): {e}")

    betriebsstunden = mapped["betriebsstunden"]
    starts = mapped["starts"]
    verbrauch_qm = mapped["verbrauch_qm"]

    if previous_item:
        prev_betriebsstunden = int(previous_item.get("betriebsstunden", 0))
        prev_starts = int(previous_item.get("starts", 0))
        prev_verbrauch = previous_item.get("verbrauch_qm", Decimal("0"))
        prev_verbrauch_decimal = (
            prev_verbrauch
            if isinstance(prev_verbrauch, Decimal)
            else Decimal(str(prev_verbrauch))
        )
        delta_betriebsstunden = betriebsstunden - prev_betriebsstunden
        delta_starts = starts - prev_starts
        delta_verbrauch_qm = verbrauch_qm - prev_verbrauch_decimal
    else:
        delta_betriebsstunden = 0
        delta_starts = 0
        delta_verbrauch_qm = Decimal("0")

    submission = create_submission(
        user_id=user_id,
        datum=mapped["datum"],
        uhrzeit=mapped["uhrzeit"],
        betriebsstunden=betriebsstunden,
        starts=starts,
        verbrauch_qm=verbrauch_qm,
        delta_betriebsstunden=delta_betriebsstunden,
        delta_starts=delta_starts,
        delta_verbrauch_qm=delta_verbrauch_qm,
        vorlauf_temp=mapped["vorlauf_temp"],
        aussentemp=mapped["aussentemp"],
    )

    table.put_item(Item=submission.to_dict())
    return (True, submission.submission_id)
