"""
Lambda handler for form submission endpoint.

Handles POST /submit requests, validates input data, creates submissions,
and stores them in DynamoDB.
"""

import json
import os
from typing import Dict, Any
from decimal import Decimal

from src.models import create_submission
from src.validators import validate_submission


# Lazily initialized DynamoDB resource (tests patch this symbol).
dynamodb = None


def get_table():
    """
    Get DynamoDB table for submissions.

    Returns:
        DynamoDB Table resource

    Raises:
        KeyError: If SUBMISSIONS_TABLE environment variable is not set
    """
    global dynamodb
    if dynamodb is None:
        # Import boto3 lazily so unit tests that don't need AWS dependencies can import this module.
        import boto3
        dynamodb = boto3.resource("dynamodb")

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
                # Parse JSON numbers as Decimal for DynamoDB compatibility (boto3 rejects float).
                body = json.loads(event["body"], parse_float=Decimal)
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
        try:
            table = get_table()
            # Find latest previous submission for this user to compute deltas
            previous_item = None
            try:
                previous_result = table.query(
                    KeyConditionExpression="user_id = :user_id",
                    ExpressionAttributeValues={":user_id": user_id},
                    ScanIndexForward=False,
                    Limit=1,
                )
                if not isinstance(previous_result, dict):
                    previous_result = {}
                items = previous_result.get("Items") or []
                if not isinstance(items, list):
                    items = []
                if items and isinstance(items[0], dict):
                    previous_item = items[0]
            except Exception as e:
                # If this fails, fall back to 0 deltas (do not block submission).
                print(f"DynamoDB query error (previous submission): {str(e)}")

            betriebsstunden = int(body["betriebsstunden"])
            starts = int(body["starts"])
            # Normalize to Decimal for DynamoDB compatibility and safe arithmetic.
            # - If body came from json.loads(..., parse_float=Decimal), this is already Decimal.
            # - If body is a dict (e.g., tests / non-APIGW invocations), this may be float/int/str.
            verbrauch_qm_raw = body["verbrauch_qm"]
            verbrauch_qm = (
                verbrauch_qm_raw
                if isinstance(verbrauch_qm_raw, Decimal)
                else Decimal(str(verbrauch_qm_raw))
            )

            if previous_item:
                prev_betriebsstunden = int(previous_item.get("betriebsstunden", 0))
                prev_starts = int(previous_item.get("starts", 0))
                prev_verbrauch = previous_item.get("verbrauch_qm", Decimal("0"))
                prev_verbrauch_decimal = prev_verbrauch if isinstance(prev_verbrauch, Decimal) else Decimal(str(prev_verbrauch))

                delta_betriebsstunden = betriebsstunden - prev_betriebsstunden
                delta_starts = starts - prev_starts
                delta_verbrauch_qm = verbrauch_qm - prev_verbrauch_decimal
            else:
                delta_betriebsstunden = 0
                delta_starts = 0
                delta_verbrauch_qm = Decimal("0")

            submission = create_submission(
                user_id=user_id,
                datum=body["datum"],
                uhrzeit=body["uhrzeit"],
                betriebsstunden=betriebsstunden,
                starts=starts,
                verbrauch_qm=verbrauch_qm,
                delta_betriebsstunden=delta_betriebsstunden,
                delta_starts=delta_starts,
                delta_verbrauch_qm=delta_verbrauch_qm,
            )

            table.put_item(Item=submission.to_dict())
        except Exception as e:
            print(f"DynamoDB write error: {str(e)}")
            return format_error_response(500, "Failed to store submission")

        # Return success response
        return format_success_response(submission.submission_id, submission.timestamp_utc)

    except Exception as e:
        print(f"Unexpected error in submit handler: {str(e)}")
        return format_error_response(500, "Internal server error")
