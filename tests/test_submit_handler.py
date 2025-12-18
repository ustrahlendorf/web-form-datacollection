"""
Property-based tests for the submit handler Lambda function.

Tests correctness properties of the submit handler using hypothesis and mocking.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from hypothesis import given, strategies as st, assume
from datetime import datetime, timezone
from decimal import Decimal

from src.handlers.submit_handler import (
    lambda_handler,
    extract_user_id,
    format_error_response,
    format_success_response,
)


# ============================================================================
# Property 11: Submission Storage Round Trip
# **Feature: data-collection-webapp, Property 11: Submission Storage Round Trip**
# **Validates: Requirements 3.1, 3.2**
# ============================================================================


@given(
    user_id=st.text(min_size=1, max_size=100),
    datum=st.just("15.12.2025"),
    uhrzeit=st.just("09:30"),
    betriebsstunden=st.integers(min_value=0, max_value=100000),
    starts=st.integers(min_value=0, max_value=100000),
    verbrauch_qm=st.floats(min_value=0.01, max_value=19.99, allow_nan=False, allow_infinity=False),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_submission_storage_round_trip(
    mock_dynamodb, user_id, datum, uhrzeit, betriebsstunden, starts, verbrauch_qm
):
    """
    For any valid submission submitted via POST /submit, the stored data SHALL match the input.
    """
    # Mock DynamoDB table
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Create event
    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_id,
                }
            }
        },
        "body": json.dumps({
            "datum": datum,
            "uhrzeit": uhrzeit,
            "betriebsstunden": betriebsstunden,
            "starts": starts,
            "verbrauch_qm": verbrauch_qm,
        }),
    }

    # Call handler
    response = lambda_handler(event, None)

    # Verify response is successful
    assert response["statusCode"] == 200, f"Expected 200, got {response['statusCode']}"

    # Verify DynamoDB put_item was called
    mock_table.put_item.assert_called_once()

    # Extract the stored item
    stored_item = mock_table.put_item.call_args[1]["Item"]

    # Verify all fields are stored correctly
    assert stored_item["user_id"] == user_id, "user_id should match"
    assert stored_item["datum"] == datum, "datum should match"
    assert stored_item["uhrzeit"] == uhrzeit, "uhrzeit should match"
    assert stored_item["betriebsstunden"] == betriebsstunden, "betriebsstunden should match"
    assert stored_item["starts"] == starts, "starts should match"
    # DynamoDB stores verbrauch_qm as Decimal, so compare as Decimal
    assert stored_item["verbrauch_qm"] == Decimal(str(verbrauch_qm)), "verbrauch_qm should match"
    assert "submission_id" in stored_item, "submission_id should be present"
    assert "timestamp_utc" in stored_item, "timestamp_utc should be present"


# ============================================================================
# Property 15: Invalid Data Rejection
# **Feature: data-collection-webapp, Property 15: Invalid Data Rejection**
# **Validates: Requirements 2.10, 3.4**
# ============================================================================


@given(
    invalid_datum=st.text(min_size=1).filter(lambda x: x not in ["15.12.2025"]),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_invalid_data_rejection_bad_date(mock_dynamodb, invalid_datum):
    """
    For any submission with invalid datum, the handler SHALL return HTTP 400 and not store data.
    """
    # Skip if the generated string happens to be a valid date
    try:
        parts = invalid_datum.split(".")
        if len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            datetime(year, month, day)
            assume(False)  # Skip valid dates
    except (ValueError, IndexError):
        pass

    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user",
                }
            }
        },
        "body": json.dumps({
            "datum": invalid_datum,
            "uhrzeit": "09:30",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        }),
    }

    response = lambda_handler(event, None)

    # Verify response is 400
    assert response["statusCode"] == 400, f"Expected 400, got {response['statusCode']}"

    # Verify DynamoDB put_item was NOT called
    mock_table.put_item.assert_not_called()


@given(
    invalid_verbrauch=st.floats(allow_nan=False, allow_infinity=False).filter(
        lambda x: x <= 0 or x >= 20.0
    ),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_invalid_data_rejection_bad_consumption(mock_dynamodb, invalid_verbrauch):
    """
    For any submission with invalid verbrauch_qm, the handler SHALL return HTTP 400 and not store data.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user",
                }
            }
        },
        "body": json.dumps({
            "datum": "15.12.2025",
            "uhrzeit": "09:30",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": invalid_verbrauch,
        }),
    }

    response = lambda_handler(event, None)

    # Verify response is 400
    assert response["statusCode"] == 400, f"Expected 400, got {response['statusCode']}"

    # Verify DynamoDB put_item was NOT called
    mock_table.put_item.assert_not_called()


# ============================================================================
# Property 16: Authentication Required
# **Feature: data-collection-webapp, Property 16: Authentication Required**
# **Validates: Requirements 1.4, 6.2**
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_authentication_required_missing_jwt(mock_dynamodb):
    """
    For any request without valid JWT token, the handler SHALL return HTTP 401.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Event without JWT claims
    event = {
        "requestContext": {
            "authorizer": {
                "claims": {}
            }
        },
        "body": json.dumps({
            "datum": "15.12.2025",
            "uhrzeit": "09:30",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        }),
    }

    response = lambda_handler(event, None)

    # Verify response is 401
    assert response["statusCode"] == 401, f"Expected 401, got {response['statusCode']}"

    # Verify DynamoDB put_item was NOT called
    mock_table.put_item.assert_not_called()


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_authentication_required_missing_request_context(mock_dynamodb):
    """
    For any request without requestContext, the handler SHALL return HTTP 401.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Event without requestContext
    event = {
        "body": json.dumps({
            "datum": "15.12.2025",
            "uhrzeit": "09:30",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        }),
    }

    response = lambda_handler(event, None)

    # Verify response is 401
    assert response["statusCode"] == 401, f"Expected 401, got {response['statusCode']}"

    # Verify DynamoDB put_item was NOT called
    mock_table.put_item.assert_not_called()


# ============================================================================
# Helper Function Tests
# ============================================================================


def test_extract_user_id_success():
    """
    For a valid event with JWT claims, extract_user_id SHALL return the user_id.
    """
    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user-123",
                }
            }
        }
    }

    user_id = extract_user_id(event)

    assert user_id == "test-user-123", "Should extract user_id from JWT claims"


def test_extract_user_id_missing_claims():
    """
    For an event without JWT claims, extract_user_id SHALL raise KeyError.
    """
    event = {
        "requestContext": {
            "authorizer": {}
        }
    }

    with pytest.raises(KeyError):
        extract_user_id(event)


def test_format_error_response():
    """
    For error response formatting, the response SHALL have correct structure.
    """
    response = format_error_response(400, "Test error", [{"field": "test", "message": "error"}])

    assert response["statusCode"] == 400
    assert "Content-Type" in response["headers"]
    body = json.loads(response["body"])
    assert body["error"] == "Test error"
    assert "details" in body


def test_format_success_response():
    """
    For success response formatting, the response SHALL have correct structure.
    """
    response = format_success_response("test-id", "2025-12-15T09:30:00Z")

    assert response["statusCode"] == 200
    assert "Content-Type" in response["headers"]
    body = json.loads(response["body"])
    assert body["submission_id"] == "test-id"
    assert body["timestamp_utc"] == "2025-12-15T09:30:00Z"


# ============================================================================
# Integration Tests
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_submit_handler_with_valid_data(mock_dynamodb):
    """
    For a valid submission request, the handler SHALL return 200 and store the data.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
        "body": json.dumps({
            "datum": "15.12.2025",
            "uhrzeit": "09:30",
            "betriebsstunden": 1234,
            "starts": 12,
            "verbrauch_qm": 19.5,
        }),
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "submission_id" in body
    assert "timestamp_utc" in body
    mock_table.put_item.assert_called_once()


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_submit_handler_with_missing_field(mock_dynamodb):
    """
    For a submission with missing required field, the handler SHALL return 400.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
        "body": json.dumps({
            "datum": "15.12.2025",
            "uhrzeit": "09:30",
            # Missing betriebsstunden, starts, verbrauch_qm
        }),
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 400
    mock_table.put_item.assert_not_called()


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_submit_handler_with_database_error(mock_dynamodb):
    """
    For a database error during write, the handler SHALL return 500.
    """
    mock_table = MagicMock()
    mock_table.put_item.side_effect = Exception("Database error")
    mock_dynamodb.Table.return_value = mock_table

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
        "body": json.dumps({
            "datum": "15.12.2025",
            "uhrzeit": "09:30",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        }),
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 500


@patch.dict("os.environ", {})
def test_submit_handler_missing_table_env_var():
    """
    For a missing SUBMISSIONS_TABLE environment variable, the handler SHALL return 500.
    """
    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
        "body": json.dumps({
            "datum": "15.12.2025",
            "uhrzeit": "09:30",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        }),
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 500
