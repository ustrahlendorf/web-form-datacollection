#!/usr/bin/env python3
"""
Copy all items from one DynamoDB table to another.

The target table must already exist (or use --create-target to create it from the
source schema). Uses Scan + BatchWriteItem with automatic pagination and retries.

Usage:
    python copy_dynamodb_table.py SOURCE_TABLE TARGET_TABLE [--region REGION]
    python copy_dynamodb_table.py SOURCE_TABLE TARGET_TABLE --create-target

Example:
    python copy_dynamodb_table.py my-old-table my-new-table
    python copy_dynamodb_table.py prod-submissions dev-submissions --create-target
    python copy_dynamodb_table.py prod-submissions dev-submissions --region eu-central-1 -q
"""

import argparse
import sys

import boto3
from botocore.exceptions import ClientError


def _table_exists(client, table_name: str) -> bool:
    """Return True if the table exists."""
    try:
        client.describe_table(TableName=table_name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def _build_create_table_params(source_desc: dict, target_table_name: str) -> dict:
    """
    Build create_table parameters from a describe_table response.

    Copies KeySchema, AttributeDefinitions, BillingMode, ProvisionedThroughput,
    GlobalSecondaryIndexes, LocalSecondaryIndexes, and StreamSpecification.
    """
    table = source_desc["Table"]
    params = {
        "TableName": target_table_name,
        "AttributeDefinitions": table["AttributeDefinitions"],
        "KeySchema": table["KeySchema"],
    }

    billing_mode = table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
    params["BillingMode"] = billing_mode

    if billing_mode == "PROVISIONED":
        pt = table.get("ProvisionedThroughput", {})
        params["ProvisionedThroughput"] = {
            "ReadCapacityUnits": pt.get("ReadCapacityUnits", 5),
            "WriteCapacityUnits": pt.get("WriteCapacityUnits", 5),
        }

    # GlobalSecondaryIndexes
    gsis = table.get("GlobalSecondaryIndexes", [])
    if gsis:
        params["GlobalSecondaryIndexes"] = []
        for gsi in gsis:
            gsi_def = {
                "IndexName": gsi["IndexName"],
                "KeySchema": gsi["KeySchema"],
                "Projection": gsi["Projection"],
            }
            if billing_mode == "PROVISIONED" and "ProvisionedThroughput" in gsi:
                gsi_def["ProvisionedThroughput"] = {
                    "ReadCapacityUnits": gsi["ProvisionedThroughput"]["ReadCapacityUnits"],
                    "WriteCapacityUnits": gsi["ProvisionedThroughput"]["WriteCapacityUnits"],
                }
            params["GlobalSecondaryIndexes"].append(gsi_def)

    # LocalSecondaryIndexes
    lsis = table.get("LocalSecondaryIndexes", [])
    if lsis:
        params["LocalSecondaryIndexes"] = [
            {
                "IndexName": lsi["IndexName"],
                "KeySchema": lsi["KeySchema"],
                "Projection": lsi["Projection"],
            }
            for lsi in lsis
        ]

    # StreamSpecification (optional)
    stream_spec = table.get("StreamSpecification")
    if stream_spec and stream_spec.get("StreamEnabled"):
        params["StreamSpecification"] = {
            "StreamEnabled": True,
            "StreamViewType": stream_spec["StreamViewType"],
        }

    return params


def _create_target_table(
    client,
    source_table_name: str,
    target_table_name: str,
    *,
    verbose: bool = True,
) -> None:
    """Create the target table with the same schema as the source table."""
    if verbose:
        print(f"Describing source table '{source_table_name}'...", file=sys.stderr)
    source_desc = client.describe_table(TableName=source_table_name)
    params = _build_create_table_params(source_desc, target_table_name)

    if verbose:
        print(f"Creating target table '{target_table_name}'...", file=sys.stderr)
    client.create_table(**params)

    # Wait for table to become ACTIVE
    if verbose:
        print("Waiting for table to become ACTIVE...", file=sys.stderr)
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=target_table_name)


def copy_table(
    source_table_name: str,
    target_table_name: str,
    *,
    region: str | None = None,
    create_target: bool = False,
    verbose: bool = True,
) -> int:
    """
    Copy all items from source DynamoDB table to target table.

    If create_target is True and the target table does not exist, it will be
    created with the same schema as the source (KeySchema, AttributeDefinitions,
    GSIs, LSIs, BillingMode, StreamSpecification).

    Returns the number of items copied.
    """
    kwargs = {} if region is None else {"region_name": region}
    client = boto3.client("dynamodb", **kwargs)
    dynamodb = boto3.resource("dynamodb", **kwargs)

    if create_target and not _table_exists(client, target_table_name):
        _create_target_table(
            client,
            source_table_name,
            target_table_name,
            verbose=verbose,
        )
    elif create_target and _table_exists(client, target_table_name):
        if verbose:
            print(f"Target table '{target_table_name}' already exists, skipping creation.", file=sys.stderr)

    source_table = dynamodb.Table(source_table_name)
    target_table = dynamodb.Table(target_table_name)

    total_copied = 0
    scan_kwargs = {}

    while True:
        response = source_table.scan(**scan_kwargs)
        items = response.get("Items", [])

        if items:
            with target_table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
                    total_copied += 1

            if verbose:
                print(f"Copied {total_copied} items so far...", file=sys.stderr)

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    return total_copied


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy all items from one DynamoDB table to another.",
        epilog="Use --create-target to create the target table from the source schema if it does not exist.",
    )
    parser.add_argument(
        "source_table",
        help="Name of the source DynamoDB table",
    )
    parser.add_argument(
        "target_table",
        help="Name of the target DynamoDB table (must already exist unless --create-target)",
    )
    parser.add_argument(
        "--create-target",
        action="store_true",
        help="Create the target table if it does not exist, using the source table schema",
    )
    parser.add_argument(
        "--region",
        help="AWS region (default: from env/config)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    args = parser.parse_args()

    try:
        count = copy_table(
            args.source_table,
            args.target_table,
            region=args.region or None,
            create_target=args.create_target,
            verbose=not args.quiet,
        )
        print(count)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
