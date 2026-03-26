"""
Integration tests for the Data Collection Web Application.

Tests end-to-end flows including authentication, form submission, history retrieval,
and user data isolation.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
from src.handlers.submit_handler import lambda_handler as submit_handler
from src.handlers.history_handler import lambda_handler as history_handler
from src.handlers.recent_handler import lambda_handler as recent_handler


# ============================================================================
# Integration Test: End-to-End Flow - Register User → Submit Form → View History
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
@patch("src.handlers.history_handler.dynamodb")
def test_end_to_end_flow_submit_and_retrieve(mock_history_dynamodb, mock_submit_dynamodb):
    """
    For an end-to-end flow, a user SHALL be able to submit a form and retrieve it from history.
    """
    # Setup mocks
    submit_table = MagicMock()
    mock_submit_dynamodb.Table.return_value = submit_table
    submit_table.query.return_value = {"Items": [], "Count": 0}
    
    history_table = MagicMock()
    mock_history_dynamodb.Table.return_value = history_table

    user_id = "test-user-123"
    submission_data = {
        "datum": "15.12.2025",
        "uhrzeit": "09:30",
        "betriebsstunden": 1234,
        "starts": 12,
        "verbrauch_qm": 19.5,
    }

    # Step 1: Submit form
    submit_event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_id,
                }
            }
        },
        "body": json.dumps(submission_data),
    }

    submit_response = submit_handler(submit_event, None)
    assert submit_response["statusCode"] == 200, "Submit should succeed"

    submit_body = json.loads(submit_response["body"])
    submission_id = submit_body["submission_id"]
    timestamp_utc = submit_body["timestamp_utc"]

    # Verify submission was stored
    submit_table.put_item.assert_called_once()
    stored_item = submit_table.put_item.call_args[1]["Item"]
    assert stored_item["submission_id"] == submission_id
    assert stored_item["user_id"] == user_id
    assert stored_item["delta_betriebsstunden"] == 0
    assert stored_item["delta_starts"] == 0
    assert stored_item["delta_verbrauch_qm"] == 0 or str(stored_item["delta_verbrauch_qm"]) == "0"

    # Step 2: Retrieve from history
    history_event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_id,
                }
            }
        },
        "queryStringParameters": None,
    }

    # Mock history query to return the submitted item
    history_table.query.return_value = {
        "Items": [stored_item],
        "Count": 1,
    }

    history_response = history_handler(history_event, None)
    assert history_response["statusCode"] == 200, "History retrieval should succeed"

    history_body = json.loads(history_response["body"])
    submissions = history_body.get("submissions", [])
    assert len(submissions) == 1, "Should retrieve the submitted item"
    assert submissions[0]["submission_id"] == submission_id
    assert submissions[0]["user_id"] == user_id


# ============================================================================
# Integration Test: Form Pre-Population with Current Date/Time
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_form_prepopulation_with_current_datetime(mock_dynamodb):
    """
    For form pre-population, the system SHALL use the current date and time.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table
    mock_table.query.return_value = {"Items": [], "Count": 0}

    # Get current date/time
    now = datetime.now(timezone.utc)
    current_date = f"{now.day:02d}.{now.month:02d}.{now.year}"
    current_time = f"{now.hour:02d}:{now.minute:02d}"

    # Submit with current date/time
    submission_data = {
        "datum": current_date,
        "uhrzeit": current_time,
        "betriebsstunden": 100,
        "starts": 5,
        "verbrauch_qm": 10.5,
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user",
                }
            }
        },
        "body": json.dumps(submission_data),
    }

    response = submit_handler(event, None)

    assert response["statusCode"] == 200
    mock_table.put_item.assert_called_once()
    stored_item = mock_table.put_item.call_args[1]["Item"]
    assert stored_item["datum"] == current_date
    assert stored_item["uhrzeit"] == current_time


# ============================================================================
# Integration Test: Recent Submissions Display on Form Page
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_submissions_display_on_form_page(mock_dynamodb):
    """
    For the form page, the system SHALL display the last 3 submissions from the past 3 days.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    user_id = "test-user"
    now = datetime.now(timezone.utc)

    # Create 3 recent submissions
    recent_submissions = []
    for i in range(3):
        timestamp = now - timedelta(hours=i)
        recent_submissions.append({
            "submission_id": f"sub-{i}",
            "user_id": user_id,
            "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datum": "15.12.2025",
            "uhrzeit": f"{9+i:02d}:00",
            "betriebsstunden": 100 + i,
            "starts": 5,
            "verbrauch_qm": 10.5 + i,
        })

    mock_table.query.return_value = {
        "Items": recent_submissions,
        "Count": 3,
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_id,
                }
            }
        },
    }

    response = recent_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    submissions = body.get("submissions", [])
    assert len(submissions) == 3, "Should return 3 recent submissions"

    # Verify they are sorted descending (newest first)
    timestamps = [sub["timestamp_utc"] for sub in submissions]
    assert timestamps == sorted(timestamps, reverse=True), "Should be sorted newest first"


# ============================================================================
# Integration Test: Pagination on History Page
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_pagination_on_history_page(mock_dynamodb):
    """
    For the history page, the system SHALL support pagination with limit and next_token.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    user_id = "test-user"
    now = datetime.now(timezone.utc)

    # Create first page of submissions (20 items)
    first_page = []
    for i in range(20):
        timestamp = now - timedelta(hours=i)
        first_page.append({
            "submission_id": f"sub-{i}",
            "user_id": user_id,
            "timestamp_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datum": "15.12.2025",
            "uhrzeit": "09:00",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        })

    # Mock first page query
    mock_table.query.return_value = {
        "Items": first_page,
        "Count": 20,
        "LastEvaluatedKey": {
            "user_id": user_id,
            "timestamp_utc": first_page[-1]["timestamp_utc"],
        },
    }

    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_id,
                }
            }
        },
        "queryStringParameters": {"limit": "20"},
    }

    response = history_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    submissions = body.get("submissions", [])
    assert len(submissions) == 20, "First page should have 20 items"
    assert "next_token" in body, "Should provide next_token for pagination"


# ============================================================================
# Integration Test: User Data Isolation
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.history_handler.dynamodb")
def test_user_data_isolation_in_history(mock_dynamodb):
    """
    For user data isolation, User A SHALL never see submissions from User B.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    user_a_id = "user-a"
    user_b_id = "user-b"
    now = datetime.now(timezone.utc)

    # Create submissions for User A
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

    # Create submissions for User B
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

    # Query as User A
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

    response = history_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    submissions = body.get("submissions", [])

    # Verify only User A's submissions are returned
    for submission in submissions:
        assert submission["user_id"] == user_a_id, "Should only return User A's submissions"

    # Verify User B's submissions are not included
    user_b_ids = {sub["submission_id"] for sub in user_b_submissions}
    returned_ids = {sub["submission_id"] for sub in submissions}
    assert not user_b_ids.intersection(returned_ids), "User B's submissions should not be visible"


# ============================================================================
# Integration Test: Error Handling - Invalid Inputs
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_error_handling_invalid_inputs(mock_dynamodb):
    """
    For invalid inputs, the system SHALL return HTTP 400 with error details.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    # Test invalid date
    event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": "test-user",
                }
            }
        },
        "body": json.dumps({
            "datum": "31.02.2025",  # Invalid date
            "uhrzeit": "09:30",
            "betriebsstunden": 100,
            "starts": 5,
            "verbrauch_qm": 10.5,
        }),
    }

    response = submit_handler(event, None)

    assert response["statusCode"] == 400, "Should return 400 for invalid date"
    mock_table.put_item.assert_not_called()

    # Test invalid consumption value
    event["body"] = json.dumps({
        "datum": "15.12.2025",
        "uhrzeit": "09:30",
        "betriebsstunden": 100,
        "starts": 5,
        "verbrauch_qm": 25.0,  # Out of range (must be < 20.0)
    })

    response = submit_handler(event, None)

    assert response["statusCode"] == 400, "Should return 400 for out-of-range consumption"
    mock_table.put_item.assert_not_called()


# ============================================================================
# Integration Test: Error Handling - Database Errors
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_error_handling_database_errors(mock_dynamodb):
    """
    For database errors, the system SHALL return HTTP 500.
    """
    mock_table = MagicMock()
    mock_table.put_item.side_effect = Exception("Database connection failed")
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
            "verbrauch_qm": 10.5,
        }),
    }

    response = submit_handler(event, None)

    assert response["statusCode"] == 500, "Should return 500 for database error"


# ============================================================================
# Integration Test: Error Handling - Authentication Errors
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
def test_error_handling_authentication_errors(mock_dynamodb):
    """
    For missing authentication, the system SHALL return HTTP 401.
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

    response = submit_handler(event, None)

    assert response["statusCode"] == 401, "Should return 401 for missing authentication"
    mock_table.put_item.assert_not_called()


# ============================================================================
# Integration Test: Multiple Submissions and History Retrieval
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.submit_handler.dynamodb")
@patch("src.handlers.history_handler.dynamodb")
def test_multiple_submissions_and_history_retrieval(mock_history_dynamodb, mock_submit_dynamodb):
    """
    For multiple submissions, the system SHALL store all and retrieve them in correct order.
    """
    submit_table = MagicMock()
    mock_submit_dynamodb.Table.return_value = submit_table
    # Default: no previous items; specific deltas are not asserted in this integration test
    submit_table.query.return_value = {"Items": [], "Count": 0}
    
    history_table = MagicMock()
    mock_history_dynamodb.Table.return_value = history_table

    user_id = "test-user"
    now = datetime.now(timezone.utc)

    # Submit 3 submissions
    stored_items = []
    for i in range(3):
        submission_data = {
            "datum": "15.12.2025",
            "uhrzeit": f"{9+i:02d}:00",
            "betriebsstunden": 100 + i,
            "starts": 5,
            "verbrauch_qm": 10.5 + i,
        }

        event = {
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": user_id,
                    }
                }
            },
            "body": json.dumps(submission_data),
        }

        response = submit_handler(event, None)
        assert response["statusCode"] == 200

        # Capture stored item
        stored_item = submit_table.put_item.call_args[1]["Item"]
        stored_item["timestamp_utc"] = (now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stored_items.append(stored_item)

    # Retrieve history
    history_table.query.return_value = {
        "Items": stored_items,
        "Count": 3,
    }

    history_event = {
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": user_id,
                }
            }
        },
        "queryStringParameters": None,
    }

    response = history_handler(history_event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    submissions = body.get("submissions", [])
    assert len(submissions) == 3, "Should retrieve all 3 submissions"

    # Verify they are sorted by timestamp descending
    timestamps = [sub["timestamp_utc"] for sub in submissions]
    assert timestamps == sorted(timestamps, reverse=True), "Should be sorted newest first"


# ============================================================================
# Integration Test: Recent Submissions with Time Window
# ============================================================================


@patch.dict("os.environ", {"SUBMISSIONS_TABLE": "test-table"})
@patch("src.handlers.recent_handler.dynamodb")
def test_recent_submissions_respects_three_day_window(mock_dynamodb):
    """
    For recent submissions, the system SHALL only return submissions from the past 3 days.
    """
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table

    user_id = "test-user"
    now = datetime.now(timezone.utc)

    # Create submissions: some within 3 days, some older
    recent_submission = {
        "submission_id": "sub-recent",
        "user_id": user_id,
        "timestamp_utc": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "datum": "15.12.2025",
        "uhrzeit": "10:00",
        "betriebsstunden": 100,
        "starts": 5,
        "verbrauch_qm": 10.5,
    }

    old_submission = {
        "submission_id": "sub-old",
        "user_id": user_id,
        "timestamp_utc": (now - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
                    "sub": user_id,
                }
            }
        },
    }

    response = recent_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    submissions = body.get("submissions", [])

    # Verify only recent submission is returned
    assert len(submissions) == 1, "Should return only recent submission"
    assert submissions[0]["submission_id"] == "sub-recent"

    # Verify the query was called with correct timestamp filter
    call_kwargs = mock_table.query.call_args[1]
    assert ":three_days_ago" in call_kwargs["ExpressionAttributeValues"]
