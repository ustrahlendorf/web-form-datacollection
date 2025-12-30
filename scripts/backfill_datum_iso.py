"""
One-off backfill tool: add/update `datum_iso` (YYYY-MM-DD) for existing items.

Why:
- `datum` is stored as dd.mm.yyyy for UX.
- Range filtering by month should use an ISO date string where lexical order matches chronological order.

This script:
- Scans the table
- Parses `datum`
- Updates `datum_iso` for each item using UpdateItem (keys: user_id, timestamp_utc)

Safety:
- Uses a ConditionExpression so it does not rewrite unchanged items.
- Does NOT log any PII (no user_id values printed).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError


DEFAULT_TABLE_NAME = "submissions-2025"
DEFAULT_REGION = "eu-central-1"


@dataclass(frozen=True)
class BackfillConfig:
    table_name: str
    region: str
    dry_run: bool
    limit: Optional[int]


def _datum_to_iso(datum_ddmmyyyy: str) -> str:
    v = (datum_ddmmyyyy or "").strip()
    return datetime.strptime(v, "%d.%m.%Y").date().isoformat()


def parse_args(argv: Optional[list[str]] = None) -> BackfillConfig:
    parser = argparse.ArgumentParser(description="Backfill datum_iso on existing DynamoDB items.")
    parser.add_argument("--table", default=DEFAULT_TABLE_NAME, help="DynamoDB table name")
    parser.add_argument("--region", default=DEFAULT_REGION, help="AWS region")
    parser.add_argument("--dry-run", action="store_true", help="Compute counts but do not update items")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N items (debug/testing)")
    args = parser.parse_args(argv)
    return BackfillConfig(
        table_name=str(args.table),
        region=str(args.region),
        dry_run=bool(args.dry_run),
        limit=args.limit,
    )


def main(argv: Optional[list[str]] = None) -> int:
    cfg = parse_args(argv)
    dynamodb = boto3.resource("dynamodb", region_name=cfg.region)
    table = dynamodb.Table(cfg.table_name)

    scanned = 0
    updated = 0
    unchanged = 0
    invalid_datum = 0
    missing_datum = 0
    last_evaluated_key: Optional[Dict[str, Any]] = None

    while True:
        scan_kwargs: Dict[str, Any] = {}
        if last_evaluated_key:
            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

        resp = table.scan(**scan_kwargs)
        items = resp.get("Items") or []

        for item in items:
            scanned += 1
            if cfg.limit is not None and scanned > cfg.limit:
                break

            datum = item.get("datum")
            if not datum:
                missing_datum += 1
                continue

            try:
                datum_iso = _datum_to_iso(str(datum))
            except Exception:
                invalid_datum += 1
                continue

            # Skip if already correct
            if item.get("datum_iso") == datum_iso:
                unchanged += 1
                continue

            if cfg.dry_run:
                updated += 1
                continue

            try:
                table.update_item(
                    Key={"user_id": item["user_id"], "timestamp_utc": item["timestamp_utc"]},
                    UpdateExpression="SET datum_iso = :v",
                    ConditionExpression="attribute_not_exists(datum_iso) OR datum_iso <> :v",
                    ExpressionAttributeValues={":v": datum_iso},
                )
                updated += 1
            except ClientError as e:
                # If condition fails, treat as unchanged (race / already updated).
                if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                    unchanged += 1
                    continue
                raise

        if cfg.limit is not None and scanned >= cfg.limit:
            break

        last_evaluated_key = resp.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    print(
        {
            "table": cfg.table_name,
            "region": cfg.region,
            "dry_run": cfg.dry_run,
            "scanned": scanned,
            "updated_or_would_update": updated,
            "unchanged": unchanged,
            "missing_datum": missing_datum,
            "invalid_datum": invalid_datum,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


