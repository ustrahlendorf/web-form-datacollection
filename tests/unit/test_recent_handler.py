"""
Property-based tests for the recent submissions handler Lambda function.

Tests correctness properties of the recent handler using hypothesis and mocking.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from hypothesis import given, strategies as st, assume
from datetime import datetime, timezone, timedelta

from src.handlers.recent_handler import (
    lambda_handler,
    extract_user_id,
    format_error_response,
    format_success_response,
    get_three_days_ago,
)


# ============================================================================
# Property 17: Recent Submissions Limited to Three Days
# **Feature: data-collection-webapp, Property 17: Recent Submissions Limited to Three Days**
# **Validates: Requirements 3.5.1**
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_submissions_limited_to_three_days(mock_dynamodb):
    """
    For any user querying the /recent endpoint, the returned submissions SHALL only include submissions from the past 3 days (72 hours from current time).
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Create submissions: some within 3 days, some older
    now = datetime.now(timezone.utc)
    three_days_ago = now - timedelta(days=3)
    four_days_ago = now - timedelta(days=4)

    recent_submission = {
        "submission_id": "sub-recent",
        "user_id": "test-user",
        "timestamp_utc": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "datum": "15.12.2025",
        "uhrzeit": "10:00",
        "betriebsstunden": 100,
        "starts": 5,
        "verbrauch_qm": 10.5,
    }

    old_submission = {
        "submission_id": "sub-old",
        "user_id": "test-user",
        "timestamp_utc": (four_days_ago).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "datum": "11.12.2025",
        "uhrzeit": "10:00",
        "betriebsstunden": 100,
        "starts": 5,
        "verbrauch_qm": 10.5,
    }

    # Mock query to return only recent submission (DynamoDB query with timestamp filter)
    mock_table.query.return_value = {
        "Items": [recent_submission],
        "Count": 1,
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user",
                }
            }
        },
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    submissions = body.get("submissions", [])

    # Verify all returned submissions are within 3 days
    for submission in submissions:
        submission_time = datetime.fromisoformat(submission["timestamp_utc"].replace("Z", "+00:00"))
        time_diff = now - submission_time
        assert time_diff <= timedelta(days=3), f"Submission should be within 3 days, but is {time_diff} old"

    # Verify the query was called with correct timestamp filter
    call_kwargs = mock_table.query.call_args[1]
    assert ":three_days_ago" in call_kwargs["ExpressionAttributeValues"]


# ============================================================================
# Property 18: Recent Submissions Limited to Three Items
# **Feature: data-collection-webapp, Property 18: Recent Submissions Limited to Three Items**
# **Validates: Requirements 3.5.1**
# ============================================================================


@given(
    num_submissions=st.integers(min_value=4, max_value=20),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_submissions_limited_to_three_items(mock_dynamodb, num_submissions):
    """
    For any user querying the /recent endpoint, the returned array SHALL contain at most 3 submissions, even if more than 3 submissions exist within the past 3 days.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Create more than 3 submissions
    now = datetime.now(timezone.utc)
    submissions = []
    for i in range(num_submissions):
        timestamp = now - timedelta(hours=i)
        submissions.append({
            "submission_id": f"sub-{i}",
            "user_id": "test-user",
            "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datum": "15.12.2025",
            "uhrzeit": "10:00",
            "betriebsstunden": 100 + i,
            "starts": 5,
            "verbrauch_qm": 10.5,
        })

    # Mock query to return only first 3 submissions (DynamoDB Limit=3)
    mock_table.query.return_value = {
        "Items": submissions[:3],
        "Count": 3,
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user",
                }
            }
        },
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    returned_submissions = body.get("submissions", [])

    # Verify at most 3 submissions are returned
    assert len(returned_submissions) <= 3, f"Expected at most 3 submissions, got {len(returned_submissions)}"

    # Verify the query was called with Limit=3
    call_kwargs = mock_table.query.call_args[1]
    assert call_kwargs.get("Limit") == 3, "Query should have Limit=3"


# ============================================================================
# Property 19: Recent Submissions Sorted Descending
# **Feature: data-collection-webapp, Property 19: Recent Submissions Sorted Descending**
# **Validates: Requirements 3.5.2**
# ============================================================================


@given(
    num_submissions=st.integers(min_value=2, max_value=3),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_submissions_sorted_descending(mock_dynamodb, num_submissions):
    """
    For any user querying the /recent endpoint, the returned submissions SHALL be sorted by timestamp_utc in descending order (newest first).
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Create submissions with different timestamps
    now = datetime.now(timezone.utc)
    submissions = []
    for i in range(num_submissions):
        timestamp = now - timedelta(hours=i)
        submissions.append({
            "submission_id": f"sub-{i}",
            "user_id": "test-user",
            "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datum": "15.12.2025",
            "uhrzeit": "10:00",
            "betriebsstunden": 100 + i,
            "starts": 5,
            "verbrauch_qm": 10.5,
        })

    # Mock query to return submissions in descending order (newest first)
    mock_table.query.return_value = {
        "Items": submissions,
        "Count": len(submissions),
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user",
                }
            }
        },
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    returned_submissions = body.get("submissions", [])

    # Verify submissions are sorted by timestamp_utc descending
    timestamps = [sub["timestamp_utc"] for sub in returned_submissions]
    sorted_timestamps = sorted(timestamps, reverse=True)
    assert timestamps == sorted_timestamps, "Submissions should be sorted by timestamp_utc descending (newest first)"

    # Verify the query was called with ScanIndexForward=False
    call_kwargs = mock_table.query.call_args[1]
    assert call_kwargs.get("ScanIndexForward") is False, "Query should have ScanIndexForward=False for descending order"


# ============================================================================
# Property 20: Recent Submissions User Isolation
# **Feature: data-collection-webapp, Property 20: Recent Submissions User Isolation**
# **Validates: Requirements 3.5.3**
# ============================================================================


@given(
    user_a_id=st.text(min_size=1, max_size=50),
    user_b_id=st.text(min_size=1, max_size=50),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_submissions_user_isolation(mock_dynamodb, user_a_id, user_b_id):
    """
    For any two different users, querying the /recent endpoint as User A SHALL never return submissions belonging to User B.
    """
    # Skip if user IDs are the same
    assume(user_a_id != user_b_id)

    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Create submissions for both users
    now = datetime.now(timezone.utc)

    user_a_submissions = [
        {
            "submission_id": "sub-a-1",
            "user_id": user_a_id,
            "timestamp_utc": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datum": "15.12.2025",
            "uhrzeit": "10:00",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        }
    ]

    user_b_submissions = [
        {
            "submission_id": "sub-b-1",
            "user_id": user_b_id,
            "timestamp_utc": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datum": "15.12.2025",
            "uhrzeit": "09:00",
            "betriebsstunden": 200,
            "starts": 10,
            "verbrauch_qm": 15.5,
        }
    ]

    # Mock query to return only User A's submissions when querying as User A
    mock_table.query.return_value = {
        "Items": user_a_submissions,
        "Count": 1,
    }

    # Create event for User A
    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_a_id,
                }
            }
        },
    }

    # Call handler
    response = lambda_handler(event, None)

    # Verify response is successful
    assert response["statusCode"] == 200, f"Expected 200, got {response['statusCode']}"

    # Parse response body
    body = json.loads(response["body"])
    submissions = body.get("submissions", [])

    # Verify all returned submissions belong to User A
    for submission in submissions:
        assert submission["user_id"] == user_a_id, f"Submission should belong to {user_a_id}, not {submission['user_id']}"

    # Verify no User B submissions are returned
    user_b_submission_ids = {sub["submission_id"] for sub in user_b_submissions}
    returned_submission_ids = {sub["submission_id"] for sub in submissions}
    assert not user_b_submission_ids.intersection(returned_submission_ids), "User B submissions should not be returned"

    # Verify the query was called with correct user_id filter
    call_kwargs = mock_table.query.call_args[1]
    assert call_kwargs["ExpressionAttributeValues"][":user_id"] == user_a_id


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


def test_get_three_days_ago():
    """
    For get_three_days_ago, the returned timestamp SHALL be approximately 3 days in the past.
    """
    now = datetime.now(timezone.utc)
    three_days_ago_str = get_three_days_ago()
    three_days_ago = datetime.fromisoformat(three_days_ago_str.replace("Z", "+00:00"))

    time_diff = now - three_days_ago
    # Allow 1 minute tolerance for execution time
    assert timedelta(days=3) - timedelta(minutes=1) <= time_diff <= timedelta(days=3) + timedelta(minutes=1)


def test_format_error_response():
    """
    For error response formatting, the response SHALL have correct structure.
    """
    response = format_error_response(500, "Test error")

    assert response["statusCode"] == 500
    assert "Content-Type" in response["headers"]
    body = json.loads(response["body"])
    assert body["error"] == "Test error"


def test_format_success_response():
    """
    For success response formatting, the response SHALL have correct structure.
    """
    submissions = [{"submission_id": "test-1"}]
    response = format_success_response(submissions)

    assert response["statusCode"] == 200
    assert "Content-Type" in response["headers"]
    body = json.loads(response["body"])
    assert body["submissions"] == submissions


# ============================================================================
# Integration Tests
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_handler_with_valid_request(mock_dynamodb):
    """
    For a valid recent submissions request, the handler SHALL return 200 with submissions.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    now = datetime.now(timezone.utc)
    submissions = [
        {
            "submission_id": "sub-1",
            "user_id": "user-123",
            "timestamp_utc": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datum": "15.12.2025",
            "uhrzeit": "10:00",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        }
    ]

    mock_table.query.return_value = {
        "Items": submissions,
        "Count": 1,
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["submissions"] == submissions
    mock_table.query.assert_called_once()


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_handler_with_no_submissions(mock_dynamodb):
    """
    For a user with no recent submissions, the handler SHALL return 200 with empty array.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    mock_table.query.return_value = {
        "Items": [],
        "Count": 0,
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["submissions"] == []


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_handler_with_database_error(mock_dynamodb):
    """
    For a database error during query, the handler SHALL return 500.
    """
    mock_table = MagicMock()
    mock_table.query.side_effect = Exception("Database error")
    mock_dynamodb.Table.return_value = mock_table

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 500


@patch.dict("os.environ", {})
def test_recent_handler_missing_table_env_var():
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
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 500


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_handler_authentication_required_missing_jwt(mock_dynamodb):
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
    }

    response = lambda_handler(event, None)

    # Verify response is 401
    assert response["statusCode"] == 401, f"Expected 401, got {response['statusCode']}"

    # Verify DynamoDB query was NOT called
    mock_table.query.assert_not_called()


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_handler_authentication_required_missing_request_context(mock_dynamodb):
    """
    For any request without requestContext, the handler SHALL return HTTP 401.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Event without requestContext
    event = {}

    response = lambda_handler(event, None)

    # Verify response is 401
    assert response["statusCode"] == 401, f"Expected 401, got {response['statusCode']}"

    # Verify DynamoDB query was NOT called
    mock_table.query.assert_not_called()
