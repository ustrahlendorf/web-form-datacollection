"""
Lambda handler for recent submissions endpoint.

Handles GET /recent requests, retrieves user's recent submissions from DynamoDB
(past 3 days, limited to 3 items), and returns them sorted by timestamp descending.
"""

import json
import os
import boto3
from typing import Dict, Any
from datetime import datetime, timezone, timedelta


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


def get_three_days_ago() -> str:
    """
    Get ISO-8601 UTC timestamp for 3 days ago.

    Returns:
        ISO-8601 formatted UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)
    """
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    return three_days_ago.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_error_response(status_code: int, error_message: str) -> Dict[str, Any]:
    """
    Format an error response for the API.

    Args:
        status_code: HTTP status code
        error_message: Error message

    Returns:
        Dictionary with statusCode and body for API Gateway response
    """
    return {
        "statusCode": status_code,
        "body": json.dumps({
            "error": error_message,
        }),
        "headers": {
            "Content-Type": "application/json",
        },
    }


def format_success_response(submissions: list) -> Dict[str, Any]:
    """
    Format a success response for the API.

    Args:
        submissions: List of submission dictionaries

    Returns:
        Dictionary with statusCode and body for API Gateway response
    """
    return {
        "statusCode": 200,
        "body": json.dumps({
            "submissions": submissions,
        }),
        "headers": {
            "Content-Type": "application/json",
        },
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle GET /recent requests.

    Retrieves user's recent submissions from the past 3 days (limited to 3 items)
    sorted by timestamp_utc descending.

    Args:
        event: Lambda event containing request context
        context: Lambda context object

    Returns:
        API Gateway response with statusCode and body
    """
    try:
        # Extract user_id from JWT claims
        try:
            user_id = extract_user_id(event)
        except KeyError as e:
            return format_error_response(401, "Unauthorized")

        # Get timestamp for 3 days ago
        three_days_ago = get_three_days_ago()

        # Query DynamoDB
        try:
            table = get_table()

            # Query for submissions from the past 3 days
            # Sort descending and limit to 3 items
            response = table.query(
                KeyConditionExpression="user_id = :user_id AND timestamp_utc > :three_days_ago",
                ExpressionAttributeValues={
                    ":user_id": user_id,
                    ":three_days_ago": three_days_ago,
                },
                ScanIndexForward=False,  # Sort descending by sort key (timestamp_utc)
                Limit=3,
            )

            # Extract submissions
            submissions = response.get("Items", [])

            # Return success response
            return format_success_response(submissions)

        except Exception as e:
            print(f"DynamoDB query error: {str(e)}")
            return format_error_response(500, "Failed to retrieve recent submissions")

    except Exception as e:
        print(f"Unexpected error in recent handler: {str(e)}")
        return format_error_response(500, "Internal server error")
