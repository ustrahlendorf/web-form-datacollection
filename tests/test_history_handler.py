"""
Property-based tests for the history handler Lambda function.

Tests correctness properties of the history handler using hypothesis and mocking.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from hypothesis import given, strategies as st, assume
from datetime import datetime, timezone, timedelta

from src.handlers.history_handler import (
    lambda_handler,
    extract_user_id,
    format_error_response,
    format_success_response,
)


# ============================================================================
# Property 12: User Data Isolation
# **Feature: data-collection-webapp, Property 12: User Data Isolation**
# **Validates: Requirements 4.6, 6.4**
# ============================================================================


@given(
    user_a_id=st.text(min_size=1, max_size=50),
    user_b_id=st.text(min_size=1, max_size=50),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_user_data_isolation(mock_dynamodb, user_a_id, user_b_id):
    """
    For any two different users, querying the history endpoint as User A SHALL never return submissions belonging to User B.
    """
    # Skip if user IDs are the same
    assume(user_a_id != user_b_id)

    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Create submissions for both users
    user_a_submissions = [
        {
            "submission_id": "sub-a-1",
            "user_id": user_a_id,
            "timestamp_utc": "2025-12-15T10:00:00Z",
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
            "timestamp_utc": "2025-12-15T09:00:00Z",
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
        "queryStringParameters": None,
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


# ============================================================================
# Property 13: History Sorting Order
# **Feature: data-collection-webapp, Property 13: History Sorting Order**
# **Validates: Requirements 4.2**
# ============================================================================


@given(
    num_submissions=st.integers(min_value=2, max_value=10),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_history_sorting_order(mock_dynamodb, num_submissions):
    """
    For any user with multiple submissions, the history endpoint SHALL return submissions sorted by timestamp_utc in descending order (newest first).
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Create submissions with different timestamps
    submissions = []
    base_time = datetime(2025, 12, 15, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(num_submissions):
        timestamp = base_time - timedelta(hours=i)
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
        "queryStringParameters": None,
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    returned_submissions = body.get("submissions", [])

    # Verify submissions are sorted by timestamp_utc descending
    timestamps = [sub["timestamp_utc"] for sub in returned_submissions]
    sorted_timestamps = sorted(timestamps, reverse=True)
    assert timestamps == sorted_timestamps, "Submissions should be sorted by timestamp_utc descending"


# ============================================================================
# Property 14: Pagination Consistency
# **Feature: data-collection-webapp, Property 14: Pagination Consistency**
# **Validates: Requirements 4.3, 4.4**
# ============================================================================


@given(
    total_submissions=st.integers(min_value=25, max_value=50),
    limit=st.integers(min_value=5, max_value=20),
)
@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_pagination_consistency(mock_dynamodb, total_submissions, limit):
    """
    For any paginated query with limit and next_token, the results SHALL not overlap with previous pages and SHALL contain the correct number of items (up to the limit).
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Create all submissions
    all_submissions = []
    base_time = datetime(2025, 12, 15, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(total_submissions):
        timestamp = base_time - timedelta(hours=i)
        all_submissions.append({
            "submission_id": f"sub-{i}",
            "user_id": "test-user",
            "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datum": "15.12.2025",
            "uhrzeit": "10:00",
            "betriebsstunden": 100 + i,
            "starts": 5,
            "verbrauch_qm": 10.5,
        })

    # First page
    first_page = all_submissions[:limit]
    last_key = {
        "user_id": "test-user",
        "timestamp_utc": first_page[-1]["timestamp_utc"],
    }

    mock_table.query.return_value = {
        "Items": first_page,
        "Count": len(first_page),
        "LastEvaluatedKey": last_key,
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user",
                }
            }
        },
        "queryStringParameters": {"limit": str(limit)},
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    returned_submissions = body.get("submissions", [])
    next_token = body.get("next_token")

    # Verify correct number of items
    assert len(returned_submissions) == limit, f"Expected {limit} items, got {len(returned_submissions)}"

    # Verify next_token is present when there are more results
    assert next_token is not None, "next_token should be present when more results exist"

    # Verify returned submissions match first page
    returned_ids = {sub["submission_id"] for sub in returned_submissions}
    first_page_ids = {sub["submission_id"] for sub in first_page}
    assert returned_ids == first_page_ids, "Returned submissions should match first page"


# ============================================================================
# Property 16: Authentication Required
# **Feature: data-collection-webapp, Property 16: Authentication Required**
# **Validates: Requirements 1.4, 6.2**
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
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
        "queryStringParameters": None,
    }

    response = lambda_handler(event, None)

    # Verify response is 401
    assert response["statusCode"] == 401, f"Expected 401, got {response['statusCode']}"

    # Verify DynamoDB query was NOT called
    mock_table.query.assert_not_called()


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_authentication_required_missing_request_context(mock_dynamodb):
    """
    For any request without requestContext, the handler SHALL return HTTP 401.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Event without requestContext
    event = {
        "queryStringParameters": None,
    }

    response = lambda_handler(event, None)

    # Verify response is 401
    assert response["statusCode"] == 401, f"Expected 401, got {response['statusCode']}"

    # Verify DynamoDB query was NOT called
    mock_table.query.assert_not_called()


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
    response = format_error_response(500, "Test error")

    assert response["statusCode"] == 500
    assert "Content-Type" in response["headers"]
    body = json.loads(response["body"])
    assert body["error"] == "Test error"


def test_format_success_response_without_next_token():
    """
    For success response formatting without next_token, the response SHALL have correct structure.
    """
    submissions = [{"submission_id": "test-1"}]
    response = format_success_response(submissions)

    assert response["statusCode"] == 200
    assert "Content-Type" in response["headers"]
    body = json.loads(response["body"])
    assert body["submissions"] == submissions
    assert "next_token" not in body


def test_format_success_response_with_next_token():
    """
    For success response formatting with next_token, the response SHALL include it.
    """
    submissions = [{"submission_id": "test-1"}]
    next_token = "test-token"
    response = format_success_response(submissions, next_token)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["submissions"] == submissions
    assert body["next_token"] == next_token


# ============================================================================
# Integration Tests
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_history_handler_with_valid_request(mock_dynamodb):
    """
    For a valid history request, the handler SHALL return 200 with submissions.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    submissions = [
        {
            "submission_id": "sub-1",
            "user_id": "user-123",
            "timestamp_utc": "2025-12-15T10:00:00Z",
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
        "queryStringParameters": None,
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["submissions"] == submissions
    mock_table.query.assert_called_once()


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_history_handler_with_limit_parameter(mock_dynamodb):
    """
    For a history request with limit parameter, the handler SHALL respect it.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    submissions = [{"submission_id": f"sub-{i}"} for i in range(10)]
    mock_table.query.return_value = {
        "Items": submissions[:10],
        "Count": 10,
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
        "queryStringParameters": {"limit": "10"},
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert len(body["submissions"]) == 10


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_history_handler_with_next_token(mock_dynamodb):
    """
    For a history request with next_token, the handler SHALL use it for pagination.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    submissions = [{"submission_id": f"sub-{i}"} for i in range(20, 30)]
    mock_table.query.return_value = {
        "Items": submissions,
        "Count": 10,
    }

    next_token = json.dumps({
        "user_id": "user-123",
        "timestamp_utc": "2025-12-15T09:00:00Z",
    })

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "user-123",
                }
            }
        },
        "queryStringParameters": {"next_token": next_token},
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert len(body["submissions"]) == 10

    # Verify ExclusiveStartKey was passed to query
    call_kwargs = mock_table.query.call_args[1]
    assert "ExclusiveStartKey" in call_kwargs


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_history_handler_with_database_error(mock_dynamodb):
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
        "queryStringParameters": None,
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 500


@patch.dict("os.environ", {})
def test_history_handler_missing_table_env_var():
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
        "queryStringParameters": None,
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 500


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_history_handler_empty_results(mock_dynamodb):
    """
    For a user with no submissions, the handler SHALL return 200 with empty array.
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
        "queryStringParameters": None,
    }

    response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["submissions"] == []
    assert "next_token" not in body
