"""
Property-based tests for the models module.

Tests correctness properties of submission model and helper functions using hypothesis.
"""

import pytest
from datetime import datetime, timezone
from uuid import UUID
from hypothesis import given, strategies as st
from decimal import Decimal
from src.models import (
    Submission,
    generate_submission_id,
    generate_timestamp_utc,
    create_submission,
)


# ============================================================================
# Property 9: Submission Creation Generates Valid UUID
# **Feature: data-collection-webapp, Property 9: Submission Creation Generates Valid UUID**
# **Validates: Requirements 2.9**
# ============================================================================


@given(st.just(None))
def test_submission_id_is_valid_uuid(unused):
    """
    For any submission created, the submission_id field SHALL be a valid UUID v4 format.
    """
    submission_id = generate_submission_id()

    # Verify it's a valid UUID by parsing it
    try:
        parsed_uuid = UUID(submission_id)
        assert str(parsed_uuid) == submission_id, "UUID string representation should match"
    except ValueError:
        pytest.fail(f"Generated submission_id {submission_id} is not a valid UUID")


@given(st.integers(min_value=0, max_value=100))
def test_submission_id_uniqueness(count):
    """
    For any number of submissions created, each submission_id SHALL be unique.
    """
    ids = [generate_submission_id() for _ in range(count + 1)]
    unique_ids = set(ids)

    assert len(unique_ids) == len(ids), "All generated submission IDs should be unique"


# ============================================================================
# Property 10: Submission Creation Generates Valid Timestamp
# **Feature: data-collection-webapp, Property 10: Submission Creation Generates Valid Timestamp**
# **Validates: Requirements 2.9**
# ============================================================================


@given(st.just(None))
def test_timestamp_is_iso8601_utc_format(unused):
    """
    For any submission created, the timestamp_utc field SHALL be in ISO-8601 UTC format.
    """
    timestamp = generate_timestamp_utc()

    # Verify format: YYYY-MM-DDTHH:MM:SSZ
    assert len(timestamp) == 20, f"Timestamp should be 20 characters, got {len(timestamp)}"
    assert timestamp[10] == "T", "Timestamp should have T separator"
    assert timestamp[19] == "Z", "Timestamp should end with Z"

    # Verify it can be parsed back
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None, "Parsed timestamp should have timezone info"
    except ValueError:
        pytest.fail(f"Generated timestamp {timestamp} is not valid ISO-8601 format")


@given(st.just(None))
def test_timestamp_is_recent(unused):
    """
    For any timestamp generated, it SHALL be within the last second of current time.
    """
    before = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp_str = generate_timestamp_utc()
    after = datetime.now(timezone.utc).replace(microsecond=0)

    # Parse the generated timestamp
    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

    # Verify it's between before and after (allowing 1 second tolerance)
    assert before <= timestamp <= after or (after - timestamp).total_seconds() <= 1, "Generated timestamp should be current time"


# ============================================================================
# Submission Creation and Dataclass Tests
# ============================================================================


@given(
    user_id=st.text(min_size=1, max_size=100),
    datum=st.just("15.12.2025"),
    uhrzeit=st.just("09:30"),
    betriebsstunden=st.integers(min_value=0, max_value=100000),
    starts=st.integers(min_value=0, max_value=100000),
    verbrauch_qm=st.floats(min_value=0.01, max_value=19.99, allow_nan=False, allow_infinity=False),
)
def test_create_submission_generates_valid_submission(
    user_id, datum, uhrzeit, betriebsstunden, starts, verbrauch_qm
):
    """
    For any valid input parameters, create_submission SHALL return a Submission with all fields populated.
    """
    submission = create_submission(
        user_id=user_id,
        datum=datum,
        uhrzeit=uhrzeit,
        betriebsstunden=betriebsstunden,
        starts=starts,
        verbrauch_qm=verbrauch_qm,
    )

    assert isinstance(submission, Submission), "Should return Submission instance"
    assert submission.user_id == user_id, "user_id should match input"
    assert submission.datum == datum, "datum should match input"
    assert submission.uhrzeit == uhrzeit, "uhrzeit should match input"
    assert submission.betriebsstunden == betriebsstunden, "betriebsstunden should match input"
    assert submission.starts == starts, "starts should match input"
    # verbrauch_qm is Decimal in the model now
    assert submission.verbrauch_qm == Decimal(str(verbrauch_qm)), "verbrauch_qm should match input"
    assert submission.submission_id, "submission_id should be generated"
    assert submission.timestamp_utc, "timestamp_utc should be generated"


@given(
    user_id=st.text(min_size=1, max_size=100),
    datum=st.just("15.12.2025"),
    uhrzeit=st.just("09:30"),
    betriebsstunden=st.integers(min_value=0, max_value=100000),
    starts=st.integers(min_value=0, max_value=100000),
    verbrauch_qm=st.floats(min_value=0.01, max_value=19.99, allow_nan=False, allow_infinity=False),
)
def test_submission_to_dict_contains_all_fields(
    user_id, datum, uhrzeit, betriebsstunden, starts, verbrauch_qm
):
    """
    For any Submission instance, to_dict() SHALL return a dictionary with all fields.
    """
    submission = create_submission(
        user_id=user_id,
        datum=datum,
        uhrzeit=uhrzeit,
        betriebsstunden=betriebsstunden,
        starts=starts,
        verbrauch_qm=verbrauch_qm,
    )

    submission_dict = submission.to_dict()

    assert isinstance(submission_dict, dict), "to_dict() should return a dictionary"
    assert "submission_id" in submission_dict, "Dictionary should contain submission_id"
    assert "user_id" in submission_dict, "Dictionary should contain user_id"
    assert "timestamp_utc" in submission_dict, "Dictionary should contain timestamp_utc"
    assert "datum" in submission_dict, "Dictionary should contain datum"
    assert "datum_iso" in submission_dict, "Dictionary should contain datum_iso"
    assert "uhrzeit" in submission_dict, "Dictionary should contain uhrzeit"
    assert "betriebsstunden" in submission_dict, "Dictionary should contain betriebsstunden"
    assert "starts" in submission_dict, "Dictionary should contain starts"
    assert "verbrauch_qm" in submission_dict, "Dictionary should contain verbrauch_qm"

    # Verify values match
    assert submission_dict["user_id"] == user_id
    assert submission_dict["datum"] == datum
    assert submission_dict["datum_iso"] == datetime.strptime(datum, "%d.%m.%Y").date().isoformat()
    assert submission_dict["uhrzeit"] == uhrzeit
    assert submission_dict["betriebsstunden"] == betriebsstunden
    assert submission_dict["starts"] == starts
    # verbrauch_qm is Decimal in the model
    assert submission_dict["verbrauch_qm"] == Decimal(str(verbrauch_qm))


@given(
    user_id=st.text(min_size=1, max_size=100),
    custom_id=st.text(min_size=1, max_size=100),
    custom_timestamp=st.just("2025-12-15T09:30:00Z"),
)
def test_create_submission_respects_custom_id_and_timestamp(user_id, custom_id, custom_timestamp):
    """
    For any custom submission_id and timestamp_utc provided, create_submission SHALL use them instead of generating new ones.
    """
    submission = create_submission(
        user_id=user_id,
        datum="15.12.2025",
        uhrzeit="09:30",
        betriebsstunden=100,
        starts=5,
        verbrauch_qm=10.5,
        submission_id=custom_id,
        timestamp_utc=custom_timestamp,
    )

    assert submission.submission_id == custom_id, "Should use provided submission_id"
    assert submission.timestamp_utc == custom_timestamp, "Should use provided timestamp_utc"


def test_create_submission_with_optional_temperatures():
    """
    For create_submission with vorlauf_temp and aussentemp, the Submission SHALL include them.
    """
    submission = create_submission(
        user_id="user-123",
        datum="15.12.2025",
        uhrzeit="09:30",
        betriebsstunden=100,
        starts=5,
        verbrauch_qm=10.5,
        vorlauf_temp=45.5,
        aussentemp=-2.3,
    )
    assert submission.vorlauf_temp == Decimal("45.5")
    assert submission.aussentemp == Decimal("-2.3")
    d = submission.to_dict()
    assert d["vorlauf_temp"] == Decimal("45.5")
    assert d["aussentemp"] == Decimal("-2.3")


def test_create_submission_without_temperatures_omits_from_dict():
    """
    For create_submission without vorlauf_temp and aussentemp, to_dict SHALL not include them.
    """
    submission = create_submission(
        user_id="user-123",
        datum="15.12.2025",
        uhrzeit="09:30",
        betriebsstunden=100,
        starts=5,
        verbrauch_qm=10.5,
    )
    assert submission.vorlauf_temp is None
    assert submission.aussentemp is None
    d = submission.to_dict()
    assert "vorlauf_temp" not in d
    assert "aussentemp" not in d
