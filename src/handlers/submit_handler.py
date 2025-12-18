"""
Lambda handler for form submission endpoint.

Handles POST /submit requests, validates input data, creates submissions,
and stores them in DynamoDB.
"""

import json
import os
import boto3
from typing import Dict, Any

from src.models import create_submission
from src.validators import validate_submission


# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")


def get_table():
    """
    Get DynamoDB table for submissions.

    Returns:
        DynamoDB Table resource

    Raises:
        KeyError: If SUBMISSIONS_TABLE environment variable is not set
    """
    table_name = os.environ.get("SUBMISSIONS_TABLE")
    if not table_name:
        raise KeyError("SUBMISSIONS_TABLE environment variable not set")
    return dynamodb.Table(table_name)


def extract_user_id(event: Dict[str, Any]) -> str:
    """
    Extract user_id from JWT claims in the Lambda event.

    Args:
        event: Lambda event containing request context with JWT claims

    Returns:
        The user_id (Cognito subject identifier)

    Raises:
        KeyError: If user_id cannot be extracted from JWT claims
    """
    try:
        # HTTP API JWT authorizer shape:
        #   requestContext.authorizer.jwt.claims.sub
        # Legacy/test shape:
        #   requestContext.authorizer.claims.sub
        authorizer = (event.get("requestContext") or {}).get("authorizer") or {}

        claims = None
        jwt_block = authorizer.get("jwt")
        if isinstance(jwt_block, dict):
            claims = jwt_block.get("claims")

        if not isinstance(claims, dict):
            claims = authorizer.get("claims")

        if not isinstance(claims, dict):
            claims = {}

        user_id = claims.get("sub")
        if not user_id:
            raise KeyError("sub claim missing")

        return user_id
    except Exception as e:
        raise KeyError(f"Could not extract user_id from JWT claims: {e}")


def format_error_response(status_code: int, error_message: str, details: list = None) -> Dict[str, Any]:
    """
    Format an error response for the API.

    Args:
        status_code: HTTP status code
        error_message: Main error message
        details: Optional list of detailed error objects

    Returns:
        Dictionary with statusCode and body for API Gateway response
    """
    body = {
        "error": error_message,
    }
    if details:
        body["details"] = details

    return {
        "statusCode": status_code,
        "body": json.dumps(body),
        "headers": {
            "Content-Type": "application/json",
        },
    }


def format_success_response(submission_id: str, timestamp_utc: str) -> Dict[str, Any]:
    """
    Format a success response for the API.

    Args:
        submission_id: The generated submission ID
        timestamp_utc: The submission timestamp

    Returns:
        Dictionary with statusCode and body for API Gateway response
    """
    return {
        "statusCode": 200,
        "body": json.dumps({
            "submission_id": submission_id,
            "timestamp_utc": timestamp_utc,
        }),
        "headers": {
            "Content-Type": "application/json",
        },
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle POST /submit requests.

    Validates form data, creates a submission, and stores it in DynamoDB.

    Args:
        event: Lambda event containing request body and context
        context: Lambda context object

    Returns:
        API Gateway response with statusCode and body
    """
    try:
        # Extract user_id from JWT claims
        try:
            user_id = extract_user_id(event)
        except KeyError as e:
            return format_error_response(401, "Unauthorized", [{"message": str(e)}])

        # Parse request body
        try:
            if isinstance(event.get("body"), str):
                body = json.loads(event["body"])
            else:
                body = event.get("body", {})
        except json.JSONDecodeError:
            return format_error_response(400, "Invalid JSON in request body")

        # Validate submission data
        validation_result = validate_submission(body)
        if not validation_result.is_valid:
            error_details = [error.to_dict() for error in validation_result.errors]
            return format_error_response(400, "Validation failed", error_details)

        # Create submission object
        submission = create_submission(
            user_id=user_id,
            datum=body["datum"],
            uhrzeit=body["uhrzeit"],
            betriebsstunden=int(body["betriebsstunden"]),
            starts=int(body["starts"]),
            verbrauch_qm=float(body["verbrauch_qm"]),
        )

        # Write to DynamoDB
        try:
            table = get_table()
            table.put_item(Item=submission.to_dict())
        except Exception as e:
            print(f"DynamoDB write error: {str(e)}")
            return format_error_response(500, "Failed to store submission")

        # Return success response
        return format_success_response(submission.submission_id, submission.timestamp_utc)

    except Exception as e:
        print(f"Unexpected error in submit handler: {str(e)}")
        return format_error_response(500, "Internal server error")
