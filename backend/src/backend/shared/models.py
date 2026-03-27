"""
Data models for the data collection web application.

Provides Submission dataclass and helper functions for creating submissions
with UUID v4 identifiers and ISO-8601 UTC timestamps.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional, Union
from decimal import Decimal


@dataclass
class Submission:
    """
    Represents a single data submission from a user.

    Attributes:
        submission_id: Unique identifier (UUID v4) for the submission
        user_id: Cognito subject identifier of the authenticated user
        timestamp_utc: ISO-8601 formatted UTC timestamp of submission creation
        datum: Date in dd.mm.yyyy format
        datum_iso: Date in YYYY-MM-DD format (derived from datum; used for filtering/analytics)
        uhrzeit: Time in hh:mm format (24-hour)
        betriebsstunden: Operating hours (integer >= 0)
        starts: Number of starts (integer >= 0)
        verbrauch_qm: Consumption per square meter (float, 0 < value < 20.0)
        delta_betriebsstunden: Delta to previous submission's operating hours (int; can be negative)
        delta_starts: Delta to previous submission's starts (int; can be negative)
        delta_verbrauch_qm: Delta to previous submission's consumption (Decimal; can be negative)
        vorlauf_temp: Optional supply temperature in Celsius (-99.9 to 99.9)
        aussentemp: Optional outside temperature in Celsius (-99.9 to 99.9)
    """

    submission_id: str
    user_id: str
    timestamp_utc: str
    datum: str
    datum_iso: str
    uhrzeit: str
    betriebsstunden: int
    starts: int
    verbrauch_qm: Decimal
    delta_betriebsstunden: int = 0
    delta_starts: int = 0
    delta_verbrauch_qm: Decimal = Decimal("0")
    vorlauf_temp: Optional[Decimal] = None
    aussentemp: Optional[Decimal] = None

    def to_dict(self) -> dict:
        """
        Convert submission to dictionary representation.

        Returns:
            Dictionary with all submission fields
        """
        result = {
            "submission_id": self.submission_id,
            "user_id": self.user_id,
            "timestamp_utc": self.timestamp_utc,
            "datum": self.datum,
            "datum_iso": self.datum_iso,
            "uhrzeit": self.uhrzeit,
            "betriebsstunden": self.betriebsstunden,
            "starts": self.starts,
            "verbrauch_qm": self.verbrauch_qm,
            "delta_betriebsstunden": self.delta_betriebsstunden,
            "delta_starts": self.delta_starts,
            "delta_verbrauch_qm": self.delta_verbrauch_qm,
        }
        if self.vorlauf_temp is not None:
            result["vorlauf_temp"] = self.vorlauf_temp
        if self.aussentemp is not None:
            result["aussentemp"] = self.aussentemp
        return result


def generate_submission_id() -> str:
    """
    Generate a unique submission identifier using UUID v4.

    Returns:
        UUID v4 string in standard format (8-4-4-4-12 hex digits)
    """
    return str(uuid4())


def generate_timestamp_utc() -> str:
    """
    Generate current timestamp in ISO-8601 UTC format.

    Returns:
        ISO-8601 formatted UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def datum_to_iso(datum: str) -> str:
    """
    Convert a business date in dd.mm.yyyy format to ISO format (YYYY-MM-DD).

    We store `datum` for UX and backwards compatibility, but `datum_iso` is the
    canonical field for range filtering and partitioning because lexical order
    matches chronological order.
    """
    if not isinstance(datum, str):
        raise TypeError("datum must be a string")
    d = datetime.strptime(datum.strip(), "%d.%m.%Y").date()
    return d.isoformat()


def create_submission(
    user_id: str,
    datum: str,
    uhrzeit: str,
    betriebsstunden: int,
    starts: int,
    verbrauch_qm: Union[Decimal, int, float, str],
    delta_betriebsstunden: int = 0,
    delta_starts: int = 0,
    delta_verbrauch_qm: Union[Decimal, int, float, str] = Decimal("0"),
    vorlauf_temp: Optional[Union[Decimal, int, float, str]] = None,
    aussentemp: Optional[Union[Decimal, int, float, str]] = None,
    submission_id: Optional[str] = None,
    timestamp_utc: Optional[str] = None,
) -> Submission:
    """
    Create a new Submission instance with auto-generated ID and timestamp.

    Args:
        user_id: Cognito subject identifier of the authenticated user
        datum: Date in dd.mm.yyyy format
        uhrzeit: Time in hh:mm format (24-hour)
        betriebsstunden: Operating hours (integer >= 0)
        starts: Number of starts (integer >= 0)
        verbrauch_qm: Consumption per square meter (stored as Decimal)
        delta_betriebsstunden: Delta to previous submission's operating hours (stored as int)
        delta_starts: Delta to previous submission's starts (stored as int)
        delta_verbrauch_qm: Delta to previous submission's consumption (stored as Decimal)
        vorlauf_temp: Optional supply temperature in Celsius (-99.9 to 99.9)
        aussentemp: Optional outside temperature in Celsius (-99.9 to 99.9)
        submission_id: Optional pre-generated UUID (auto-generated if not provided)
        timestamp_utc: Optional pre-generated timestamp (auto-generated if not provided)

    Returns:
        Submission instance with all fields populated
    """
    # Coerce to Decimal for stable storage/serialization and to avoid float artifacts.
    # Use Decimal(str(x)) so property tests (which do the same) match exactly.
    verbrauch_qm_decimal = verbrauch_qm if isinstance(verbrauch_qm, Decimal) else Decimal(str(verbrauch_qm))
    delta_verbrauch_qm_decimal = (
        delta_verbrauch_qm if isinstance(delta_verbrauch_qm, Decimal) else Decimal(str(delta_verbrauch_qm))
    )

    vorlauf_temp_decimal = None
    if vorlauf_temp is not None:
        vorlauf_temp_decimal = vorlauf_temp if isinstance(vorlauf_temp, Decimal) else Decimal(str(vorlauf_temp))
    aussentemp_decimal = None
    if aussentemp is not None:
        aussentemp_decimal = aussentemp if isinstance(aussentemp, Decimal) else Decimal(str(aussentemp))

    return Submission(
        submission_id=submission_id or generate_submission_id(),
        user_id=user_id,
        timestamp_utc=timestamp_utc or generate_timestamp_utc(),
        datum=datum,
        datum_iso=datum_to_iso(datum),
        uhrzeit=uhrzeit,
        betriebsstunden=betriebsstunden,
        starts=starts,
        verbrauch_qm=verbrauch_qm_decimal,
        delta_betriebsstunden=delta_betriebsstunden,
        delta_starts=delta_starts,
        delta_verbrauch_qm=delta_verbrauch_qm_decimal,
        vorlauf_temp=vorlauf_temp_decimal,
        aussentemp=aussentemp_decimal,
    )
