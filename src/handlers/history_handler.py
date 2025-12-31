"""
Lambda handler for history endpoint.

Handles GET /history requests, retrieves user submissions from DynamoDB,
and returns paginated results sorted by timestamp descending.
"""

import json
import os
from typing import Dict, Any, Optional
from decimal import Decimal


# Lazily initialized DynamoDB resource (tests patch this symbol).
dynamodb = None


def _json_default(obj):
    """
    JSON serializer for DynamoDB Decimal types.
    
    DynamoDB returns numeric values as Decimal, which json.dumps cannot serialize.
    This helper converts Decimal to float for JSON encoding.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


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
        }, default=_json_default),
        "headers": {
            "Content-Type": "application/json",
        },
    }


def format_success_response(submissions: list, next_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Format a success response for the API.

    Args:
        submissions: List of submission dictionaries
        next_token: Optional pagination token for next page

    Returns:
        Dictionary with statusCode and body for API Gateway response
    """
    body = {
        "submissions": submissions,
    }
    if next_token:
        body["next_token"] = next_token

    return {
        "statusCode": 200,
        "body": json.dumps(body, default=_json_default),
        "headers": {
            "Content-Type": "application/json",
        },
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Handle GET /history requests.

    Retrieves user submissions from DynamoDB with pagination support.

    Args:
        event: Lambda event containing query parameters and context
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

        # Extract query parameters
        query_params = event.get("queryStringParameters") or {}
        limit = int(query_params.get("limit", 20))
        next_token = query_params.get("next_token")

        # Validate limit
        if limit < 1 or limit > 100:
            limit = 20

        # Query DynamoDB
        try:
            table = get_table()

            # Build query parameters
            query_kwargs = {
                "KeyConditionExpression": "user_id = :user_id",
                "ExpressionAttributeValues": {
                    ":user_id": user_id,
                },
                "ScanIndexForward": False,  # Sort descending by sort key (timestamp_utc)
                "Limit": limit,
            }

            # Add pagination token if provided
            if next_token:
                query_kwargs["ExclusiveStartKey"] = json.loads(next_token)

            # Execute query
            response = table.query(**query_kwargs)

            # Extract submissions
            submissions = response.get("Items", [])

            # Generate next_token if there are more results
            next_token_response = None
            if response.get("LastEvaluatedKey"):
                next_token_response = json.dumps(response["LastEvaluatedKey"])

            # Return success response
            return format_success_response(submissions, next_token_response)

        except Exception as e:
            print(f"DynamoDB query error: {str(e)}")
            return format_error_response(500, "Failed to retrieve submissions")

    except Exception as e:
        print(f"Unexpected error in history handler: {str(e)}")
        return format_error_response(500, "Internal server error")
