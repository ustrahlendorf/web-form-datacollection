"""
Property-based tests for the validators module.

Tests correctness properties of validation functions using hypothesis.
"""

import pytest
from datetime import datetime, timedelta
from hypothesis import given, strategies as st, assume
from src.validators import (
    validate_date,
    validate_time,
    validate_integer,
    validate_float_range,
    validate_submission,
    trim_whitespace,
    normalize_decimal,
    ValidationResult,
)


# ============================================================================
# Property 1: Date Validation Accepts Valid Dates
# **Feature: data-collection-webapp, Property 1: Date Validation Accepts Valid Dates**
# **Validates: Requirements 2.2**
# ============================================================================


@given(
    day=st.integers(min_value=1, max_value=31),
    month=st.integers(min_value=1, max_value=12),
    year=st.integers(min_value=1900, max_value=2100),
)
def test_date_validation_accepts_valid_dates(day, month, year):
    """
    For any valid date in dd.mm.yyyy format, the validation function SHALL accept it.
    """
    # Filter out invalid calendar dates
    try:
        datetime(year, month, day)
    except ValueError:
        assume(False)

    date_str = f"{day:02d}.{month:02d}.{year:04d}"
    is_valid, error_msg = validate_date(date_str)

    assert is_valid is True, f"Valid date {date_str} was rejected with error: {error_msg}"


# ============================================================================
# Property 2: Date Validation Rejects Invalid Dates
# **Feature: data-collection-webapp, Property 2: Date Validation Rejects Invalid Dates**
# **Validates: Requirements 2.2**
# ============================================================================


@given(st.text(min_size=1))
def test_date_validation_rejects_invalid_dates(invalid_date):
    """
    For any invalid date string, the validation function SHALL reject it.
    """
    # Filter out valid dates
    try:
        parts = invalid_date.split(".")
        if len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            datetime(year, month, day)
            assume(False)  # Skip valid dates
    except (ValueError, IndexError):
        pass

    is_valid, error_msg = validate_date(invalid_date)

    assert is_valid is False, f"Invalid date {invalid_date} was accepted"
    assert error_msg, "Error message should be provided for invalid date"


# ============================================================================
# Property 3: Time Validation Accepts Valid Times
# **Feature: data-collection-webapp, Property 3: Time Validation Accepts Valid Times**
# **Validates: Requirements 2.3**
# ============================================================================


@given(
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
)
def test_time_validation_accepts_valid_times(hour, minute):
    """
    For any valid time in hh:mm format (24-hour), the validation function SHALL accept it.
    """
    time_str = f"{hour:02d}:{minute:02d}"
    is_valid, error_msg = validate_time(time_str)

    assert is_valid is True, f"Valid time {time_str} was rejected with error: {error_msg}"


# ============================================================================
# Property 4: Time Validation Rejects Invalid Times
# **Feature: data-collection-webapp, Property 4: Time Validation Rejects Invalid Times**
# **Validates: Requirements 2.3**
# ============================================================================


@given(st.text(min_size=1))
def test_time_validation_rejects_invalid_times(invalid_time):
    """
    For any invalid time string, the validation function SHALL reject it.
    """
    # Filter out valid times
    try:
        parts = invalid_time.split(":")
        if len(parts) == 2:
            hour, minute = int(parts[0]), int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                assume(False)  # Skip valid times
    except (ValueError, IndexError):
        pass

    is_valid, error_msg = validate_time(invalid_time)

    assert is_valid is False, f"Invalid time {invalid_time} was accepted"
    assert error_msg, "Error message should be provided for invalid time"


# ============================================================================
# Property 5: Integer Validation for Non-Negative Values
# **Feature: data-collection-webapp, Property 5: Integer Validation for Non-Negative Values**
# **Validates: Requirements 2.4, 2.5**
# ============================================================================


@given(value=st.integers(min_value=0, max_value=1000000))
def test_integer_validation_accepts_non_negative(value):
    """
    For any non-negative integer, the validation function SHALL accept it.
    """
    is_valid, error_msg = validate_integer(value, "test_field", min_value=0)

    assert is_valid is True, f"Valid non-negative integer {value} was rejected with error: {error_msg}"


@given(value=st.integers(max_value=-1))
def test_integer_validation_rejects_negative(value):
    """
    For any negative integer, the validation function SHALL reject it.
    """
    is_valid, error_msg = validate_integer(value, "test_field", min_value=0)

    assert is_valid is False, f"Negative integer {value} was accepted"
    assert error_msg, "Error message should be provided for negative integer"


# ============================================================================
# Property 6: Float Range Validation for Consumption
# **Feature: data-collection-webapp, Property 6: Float Range Validation for Consumption**
# **Validates: Requirements 2.6**
# ============================================================================


@given(value=st.floats(min_value=0.01, max_value=19.99, allow_nan=False, allow_infinity=False))
def test_float_range_validation_accepts_valid_consumption(value):
    """
    For any float value where 0 < value < 20.0, the validation function SHALL accept it.
    """
    is_valid, error_msg = validate_float_range(value, "verbrauch_qm", min_value=0, max_value=20.0)

    assert is_valid is True, f"Valid consumption value {value} was rejected with error: {error_msg}"


@given(value=st.floats(allow_nan=False, allow_infinity=False))
def test_float_range_validation_rejects_out_of_range(value):
    """
    For any float value outside the range (0, 20.0), the validation function SHALL reject it.
    """
    # Filter to only out-of-range values
    assume(value <= 0 or value >= 20.0)

    is_valid, error_msg = validate_float_range(value, "verbrauch_qm", min_value=0, max_value=20.0)

    assert is_valid is False, f"Out-of-range consumption value {value} was accepted"
    assert error_msg, "Error message should be provided for out-of-range value"


# ============================================================================
# Property 7: Decimal Normalization
# **Feature: data-collection-webapp, Property 7: Decimal Normalization**
# **Validates: Requirements 2.7**
# ============================================================================


@given(st.floats(min_value=0.01, max_value=19.99, allow_nan=False, allow_infinity=False))
def test_decimal_normalization_comma_to_dot(value):
    """
    For any decimal input with comma notation, normalization SHALL convert it to dot notation.
    """
    # Create a string with comma notation
    value_str = f"{value:.2f}".replace(".", ",")

    normalized = normalize_decimal(value_str)

    assert "." in normalized, f"Normalized value {normalized} should contain dot"
    assert "," not in normalized, f"Normalized value {normalized} should not contain comma"
    # Verify numeric value is preserved
    assert abs(float(normalized) - value) < 0.01, "Numeric value should be preserved"


@given(st.floats(min_value=0.01, max_value=19.99, allow_nan=False, allow_infinity=False))
def test_decimal_normalization_preserves_dot(value):
    """
    For any decimal input already in dot notation, normalization SHALL preserve it.
    """
    value_str = f"{value:.2f}"

    normalized = normalize_decimal(value_str)

    assert normalized == value_str, "Dot notation should be preserved"


# ============================================================================
# Property 8: Whitespace Trimming
# **Feature: data-collection-webapp, Property 8: Whitespace Trimming**
# **Validates: Requirements 2.8**
# ============================================================================


@given(
    text=st.text(min_size=1),
    leading_spaces=st.integers(min_value=0, max_value=10),
    trailing_spaces=st.integers(min_value=0, max_value=10),
)
def test_whitespace_trimming(text, leading_spaces, trailing_spaces):
    """
    For any string with leading/trailing whitespace, trimming SHALL remove it.
    """
    # Skip if text is only whitespace
    assume(text.strip())

    padded = " " * leading_spaces + text + " " * trailing_spaces
    trimmed = trim_whitespace(padded)

    assert trimmed == text.strip(), f"Trimmed value should equal original stripped text"
    assert not trimmed.startswith(" "), "Trimmed value should not start with space"
    assert not trimmed.endswith(" "), "Trimmed value should not end with space"


# ============================================================================
# Property 9: Submission Creation Generates Valid UUID
# **Feature: data-collection-webapp, Property 9: Submission Creation Generates Valid UUID**
# **Validates: Requirements 2.9**
# ============================================================================

# Note: This property is tested in the models module, not validators
# Validators module does not generate UUIDs


# ============================================================================
# Property 10: Submission Creation Generates Valid Timestamp
# **Feature: data-collection-webapp, Property 10: Submission Creation Generates Valid Timestamp**
# **Validates: Requirements 2.9**
# ============================================================================

# Note: This property is tested in the models module, not validators
# Validators module does not generate timestamps


# ============================================================================
# Additional: Comprehensive Submission Validation
# **Feature: data-collection-webapp, Property 15: Invalid Data Rejection**
# **Validates: Requirements 2.10, 3.4**
# ============================================================================


@given(
    day=st.integers(min_value=1, max_value=31),
    month=st.integers(min_value=1, max_value=12),
    year=st.integers(min_value=1900, max_value=2100),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    betriebsstunden=st.integers(min_value=0, max_value=100000),
    starts=st.integers(min_value=0, max_value=100000),
    verbrauch=st.floats(min_value=0.01, max_value=19.99, allow_nan=False, allow_infinity=False),
)
def test_submission_validation_accepts_valid_data(
    day, month, year, hour, minute, betriebsstunden, starts, verbrauch
):
    """
    For any valid submission data, validate_submission SHALL return is_valid=True.
    """
    # Filter out invalid calendar dates
    try:
        datetime(year, month, day)
    except ValueError:
        assume(False)

    submission = {
        "datum": f"{day:02d}.{month:02d}.{year:04d}",
        "uhrzeit": f"{hour:02d}:{minute:02d}",
        "betriebsstunden": betriebsstunden,
        "starts": starts,
        "verbrauch_qm": verbrauch,
    }

    result = validate_submission(submission)

    assert result.is_valid is True, f"Valid submission was rejected with errors: {result.errors}"


@given(
    submission=st.fixed_dictionaries(
        {
            "datum": st.just("invalid-date"),
            "uhrzeit": st.just("25:99"),
            "betriebsstunden": st.just(-1),
            "starts": st.just(-5),
            "verbrauch_qm": st.just(25.0),
        }
    )
)
def test_submission_validation_rejects_invalid_data(submission):
    """
    For any submission with invalid fields, validate_submission SHALL return is_valid=False.
    """
    result = validate_submission(submission)

    assert result.is_valid is False, "Invalid submission should be rejected"
    assert len(result.errors) > 0, "Errors should be provided for invalid submission"
