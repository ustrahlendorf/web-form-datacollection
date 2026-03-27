"""
Validation module for data collection web application.

Provides validation functions for all input fields with structured error handling.
"""

from datetime import datetime
from typing import Dict, List, Any, Tuple, Union


class ValidationError:
    """Represents a single validation error."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary representation."""
        return {"field": self.field, "message": self.message}


class ValidationResult:
    """Result of validation containing errors if any."""

    def __init__(self, is_valid: bool, errors: List[ValidationError] = None):
        self.is_valid = is_valid
        self.errors = errors or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "is_valid": self.is_valid,
            "errors": [error.to_dict() for error in self.errors],
        }


def trim_whitespace(value: str) -> str:
    """
    Trim leading and trailing whitespace from a string.

    Args:
        value: The string to trim

    Returns:
        The trimmed string
    """
    if not isinstance(value, str):
        return value
    return value.strip()


def normalize_decimal(value: str) -> str:
    """
    Normalize decimal notation from comma to dot.

    Args:
        value: The decimal string (may use comma or dot)

    Returns:
        The normalized string with dot notation
    """
    if not isinstance(value, str):
        return str(value)
    return value.replace(",", ".")


def validate_date(value: str) -> Tuple[bool, str]:
    """
    Validate date in dd.mm.yyyy format.

    Args:
        value: The date string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(value, str):
        return False, "Date must be a string"

    value = trim_whitespace(value)

    # Check format
    if len(value) != 10 or value[2] != "." or value[5] != ".":
        return False, "Invalid date format. Expected dd.mm.yyyy"

    try:
        day_str, month_str, year_str = value.split(".")
        day = int(day_str)
        month = int(month_str)
        year = int(year_str)
    except ValueError:
        return False, "Invalid date format. Expected dd.mm.yyyy"

    # Validate calendar date
    try:
        datetime(year, month, day)
        return True, ""
    except ValueError:
        return False, "Invalid calendar date"


def validate_time(value: str) -> Tuple[bool, str]:
    """
    Validate time in hh:mm 24-hour format.

    Args:
        value: The time string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(value, str):
        return False, "Time must be a string"

    value = trim_whitespace(value)

    # Check format
    if len(value) != 5 or value[2] != ":":
        return False, "Invalid time format. Expected hh:mm"

    try:
        hour_str, minute_str = value.split(":")
        hour = int(hour_str)
        minute = int(minute_str)
    except ValueError:
        return False, "Invalid time format. Expected hh:mm"

    # Validate 24-hour format
    if hour < 0 or hour > 23:
        return False, "Hour must be between 0 and 23"

    if minute < 0 or minute > 59:
        return False, "Minute must be between 0 and 59"

    return True, ""


def validate_integer(value: Union[int, str], field_name: str, min_value: int = 0) -> Tuple[bool, str]:
    """
    Validate integer value with optional minimum constraint.

    Args:
        value: The value to validate
        field_name: Name of the field (for error messages)
        min_value: Minimum allowed value (default: 0)

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        if isinstance(value, str):
            value = trim_whitespace(value)
            int_value = int(value)
        else:
            int_value = int(value)
    except (ValueError, TypeError):
        return False, f"{field_name} must be an integer"

    if int_value < min_value:
        return False, f"{field_name} must be >= {min_value}"

    return True, ""


def validate_float_range(
    value: Union[float, str], field_name: str, min_value: float = None, max_value: float = None
) -> Tuple[bool, str]:
    """
    Validate float value within a range (exclusive bounds).

    Args:
        value: The value to validate
        field_name: Name of the field (for error messages)
        min_value: Minimum allowed value (exclusive, default: None)
        max_value: Maximum allowed value (exclusive, default: None)

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        if isinstance(value, str):
            value = trim_whitespace(value)
            value = normalize_decimal(value)
            float_value = float(value)
        else:
            float_value = float(value)
    except (ValueError, TypeError):
        return False, f"{field_name} must be a number"

    if min_value is not None and float_value <= min_value:
        return False, f"{field_name} must be > {min_value}"

    if max_value is not None and float_value >= max_value:
        return False, f"{field_name} must be < {max_value}"

    return True, ""


def validate_temperature(value: Union[float, str], field_name: str) -> Tuple[bool, str]:
    """
    Validate temperature in Celsius, range -99.9 to 99.9 inclusive.

    Args:
        value: The value to validate
        field_name: Name of the field (for error messages)

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        if isinstance(value, str):
            value = trim_whitespace(value)
            value = normalize_decimal(value)
            float_value = float(value)
        else:
            float_value = float(value)
    except (ValueError, TypeError):
        return False, f"{field_name} must be a number"

    if float_value < -99.9 or float_value > 99.9:
        return False, f"{field_name} must be between -99.9 and 99.9 °C"

    return True, ""


def validate_submission(submission_data: Dict[str, Any]) -> ValidationResult:
    """
    Validate complete submission data.

    Args:
        submission_data: Dictionary containing all submission fields

    Returns:
        ValidationResult with any validation errors
    """
    errors: List[ValidationError] = []

    # Validate datum (date)
    if "datum" not in submission_data:
        errors.append(ValidationError("datum", "Field is required"))
    else:
        is_valid, error_msg = validate_date(submission_data["datum"])
        if not is_valid:
            errors.append(ValidationError("datum", error_msg))

    # Validate uhrzeit (time)
    if "uhrzeit" not in submission_data:
        errors.append(ValidationError("uhrzeit", "Field is required"))
    else:
        is_valid, error_msg = validate_time(submission_data["uhrzeit"])
        if not is_valid:
            errors.append(ValidationError("uhrzeit", error_msg))

    # Validate betriebsstunden (operating hours)
    if "betriebsstunden" not in submission_data:
        errors.append(ValidationError("betriebsstunden", "Field is required"))
    else:
        is_valid, error_msg = validate_integer(submission_data["betriebsstunden"], "betriebsstunden", min_value=0)
        if not is_valid:
            errors.append(ValidationError("betriebsstunden", error_msg))

    # Validate starts
    if "starts" not in submission_data:
        errors.append(ValidationError("starts", "Field is required"))
    else:
        is_valid, error_msg = validate_integer(submission_data["starts"], "starts", min_value=0)
        if not is_valid:
            errors.append(ValidationError("starts", error_msg))

    # Validate verbrauch_qm (consumption)
    if "verbrauch_qm" not in submission_data:
        errors.append(ValidationError("verbrauch_qm", "Field is required"))
    else:
        is_valid, error_msg = validate_float_range(
            submission_data["verbrauch_qm"], "verbrauch_qm", min_value=0, max_value=20.0
        )
        if not is_valid:
            errors.append(ValidationError("verbrauch_qm", error_msg))

    # Validate vorlauf_temp (supply temperature, optional)
    vorlauf = submission_data.get("vorlauf_temp")
    if vorlauf is not None and not (isinstance(vorlauf, str) and trim_whitespace(vorlauf) == ""):
        is_valid, error_msg = validate_temperature(vorlauf, "vorlauf_temp")
        if not is_valid:
            errors.append(ValidationError("vorlauf_temp", error_msg))

    # Validate aussentemp (outside temperature, optional)
    aussentemp = submission_data.get("aussentemp")
    if aussentemp is not None and not (isinstance(aussentemp, str) and trim_whitespace(aussentemp) == ""):
        is_valid, error_msg = validate_temperature(aussentemp, "aussentemp")
        if not is_valid:
            errors.append(ValidationError("aussentemp", error_msg))

    return ValidationResult(is_valid=len(errors) == 0, errors=errors)
