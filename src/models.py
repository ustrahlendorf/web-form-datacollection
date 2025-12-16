"""
Data models for the data collection web application.

Provides Submission dataclass and helper functions for creating submissions
with UUID v4 identifiers and ISO-8601 UTC timestamps.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional


@dataclass
class Submission:
    """
    Represents a single data submission from a user.

    Attributes:
        submission_id: Unique identifier (UUID v4) for the submission
        user_id: Cognito subject identifier of the authenticated user
        timestamp_utc: ISO-8601 formatted UTC timestamp of submission creation
        datum: Date in dd.mm.yyyy format
        uhrzeit: Time in hh:mm format (24-hour)
        betriebsstunden: Operating hours (integer >= 0)
        starts: Number of starts (integer >= 0)
        verbrauch_qm: Consumption per square meter (float, 0 < value < 20.0)
    """

    submission_id: str
    user_id: str
    timestamp_utc: str
    datum: str
    uhrzeit: str
    betriebsstunden: int
    starts: int
    verbrauch_qm: float

    def to_dict(self) -> dict:
        """
        Convert submission to dictionary representation.

        Returns:
            Dictionary with all submission fields
        """
        return {
            "submission_id": self.submission_id,
            "user_id": self.user_id,
            "timestamp_utc": self.timestamp_utc,
            "datum": self.datum,
            "uhrzeit": self.uhrzeit,
            "betriebsstunden": self.betriebsstunden,
            "starts": self.starts,
            "verbrauch_qm": self.verbrauch_qm,
        }


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


def create_submission(
    user_id: str,
    datum: str,
    uhrzeit: str,
    betriebsstunden: int,
    starts: int,
    verbrauch_qm: float,
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
        verbrauch_qm: Consumption per square meter (float, 0 < value < 20.0)
        submission_id: Optional pre-generated UUID (auto-generated if not provided)
        timestamp_utc: Optional pre-generated timestamp (auto-generated if not provided)

    Returns:
        Submission instance with all fields populated
    """
    return Submission(
        submission_id=submission_id or generate_submission_id(),
        user_id=user_id,
        timestamp_utc=timestamp_utc or generate_timestamp_utc(),
        datum=datum,
        uhrzeit=uhrzeit,
        betriebsstunden=betriebsstunden,
        starts=starts,
        verbrauch_qm=verbrauch_qm,
    )
