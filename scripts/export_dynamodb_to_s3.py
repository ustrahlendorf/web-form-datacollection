"""
Manual DynamoDB -> S3 snapshot export (small-table “batch export”).

Why this exists
---------------
The DynamoDB submissions table is small (~365 rows / year). Instead of using
DynamoDB's managed export-to-S3 features, we can do a simple ops-friendly export:
- Scan the table (with a business-date filter for a given month)
- Serialize items to JSON Lines (one item per line)
- Gzip the payload
- Upload to a private, versioned S3 “mini DataLake” bucket

The output layout is designed to be analytics-friendly (Athena/Glue partitions):
  exports/submissions/year=YYYY/month=MM/snapshot_at=YYYY-MM-DDTHHMMSSZ/
    - part-000.jsonl.gz
    - manifest.json

Security notes
--------------
- This script does not embed credentials. It relies on standard AWS credential
  resolution (env vars, shared config, SSO, instance profile, etc.).
- The target bucket is expected to be private, encrypted, and versioned.

Operational notes
-----------------
- For the current table design (PK=user_id, SK=timestamp_utc), we cannot do a
  global Query by time across users, so we use Scan + FilterExpression.
- Business-date filtering uses `datum_iso` (YYYY-MM-DD) derived from user input
  `datum` (dd.mm.yyyy). Using ISO date strings allows correct lexicographic
  range filtering in DynamoDB.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple


DEFAULT_REGION = "eu-central-1"
DEFAULT_PREFIX_BASE = "exports/submissions"


@dataclass(frozen=True)
class ExportConfig:
    table_name: str
    region: str
    bucket: str
    prefix_base: str
    year: int
    month: int
    dry_run: bool
    limit: Optional[int]

def _default_table_name_from_env() -> Optional[str]:
    """
    Prefer the active submissions table name from the deployment configuration.

    We support both names for convenience:
    - ACTIVE_SUBMISSIONS_TABLE_NAME (preferred for CDK-driven deployments)
    - SUBMISSIONS_TABLE (runtime Lambda env var name)
    """
    return os.environ.get("ACTIVE_SUBMISSIONS_TABLE_NAME") or os.environ.get("SUBMISSIONS_TABLE")


def _format_iso_utc(dt: datetime) -> str:
    """
    Format as UTC ISO-8601 with Z suffix (seconds precision).

    Example: 2025-12-21T14:03:12Z
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_snapshot_folder_timestamp(dt: datetime) -> str:
    """
    Format a timestamp suitable for use inside an S3 key prefix.

    We avoid ':' characters for readability in tools, while keeping ISO shape:
      YYYY-MM-DDTHHMMSSZ
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _month_window_iso_date(year: int, month: int) -> Tuple[str, str]:
    """
    Return [start, end) bounds for a given month as ISO date strings (YYYY-MM-DD).

    - start is inclusive
    - end is exclusive (first day of next month)
    """
    if year < 1970 or year > 9999:
        raise ValueError("year out of supported range")
    if month < 1 or month > 12:
        raise ValueError("month must be 1..12")

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def _json_default(value: Any) -> Any:
    """
    JSON serializer for DynamoDB-style values.

    DynamoDB often returns Decimal for numeric types; JSON can't encode Decimal,
    and casting to float may introduce artifacts. We serialize as string to keep
    exactness (analytics code can parse to Decimal as needed).
    """
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _iter_scan_items(
    table,
    *,
    start_datum_iso: str,
    end_datum_iso: str,
    limit: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """
    Scan the DynamoDB table and yield items whose datum_iso is in [start,end).
    """
    # Import lazily so unit tests that only use helper functions can run without boto3/botocore.
    from boto3.dynamodb.conditions import Attr

    # FilterExpression is applied server-side after scan reads items.
    # With ~365 rows total this is fine; later we can rework schema/index if needed.
    filter_expr = Attr("datum_iso").gte(start_datum_iso) & Attr("datum_iso").lt(end_datum_iso)

    scanned = 0
    last_evaluated_key = None
    while True:
        scan_kwargs: Dict[str, Any] = {"FilterExpression": filter_expr}
        if last_evaluated_key:
            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

        resp = table.scan(**scan_kwargs)
        items = resp.get("Items") or []
        for item in items:
            yield item
            scanned += 1
            if limit is not None and scanned >= limit:
                return

        last_evaluated_key = resp.get("LastEvaluatedKey")
        if not last_evaluated_key:
            return


def _build_s3_keys(
    *,
    prefix_base: str,
    year: int,
    month: int,
    snapshot_at: str,
) -> Tuple[str, str]:
    """
    Build (data_key, manifest_key) for the snapshot.
    """
    mm = f"{month:02d}"
    folder = f"{prefix_base}/year={year}/month={mm}/snapshot_at={snapshot_at}"
    return f"{folder}/part-000.jsonl.gz", f"{folder}/manifest.json"


def _encode_jsonl_gz(items: Iterable[Dict[str, Any]]) -> Tuple[bytes, int, str]:
    """
    Encode items as gzipped JSONL.

    Returns: (payload_bytes, row_count, sha256_hex)
    """
    # Build in-memory since the dataset is tiny by requirement (~365 rows).
    # If this grows later, switch to streaming upload via multipart.
    row_count = 0
    h = hashlib.sha256()
    lines: list[bytes] = []

    for item in items:
        row_count += 1
        line = (json.dumps(item, ensure_ascii=False, default=_json_default) + "\n").encode("utf-8")
        lines.append(line)
        h.update(line)

    raw = b"".join(lines)
    gz = gzip.compress(raw)
    return gz, row_count, h.hexdigest()


def parse_args(argv: Optional[list[str]] = None) -> ExportConfig:
    parser = argparse.ArgumentParser(
        description="Export DynamoDB monthly snapshot to S3 (gzipped JSONL + manifest)."
    )
    parser.add_argument("--bucket", required=True, help="Target S3 bucket name (DataLake bucket)")
    parser.add_argument("--table", default=None, help="Source DynamoDB table name")
    parser.add_argument("--region", default=DEFAULT_REGION, help="AWS region")
    parser.add_argument(
        "--prefix-base",
        default=DEFAULT_PREFIX_BASE,
        help=f"S3 prefix base (default: {DEFAULT_PREFIX_BASE})",
    )
    parser.add_argument("--year", type=int, required=True, help="Year to export (e.g. 2025)")
    parser.add_argument("--month", type=int, required=True, help="Month to export (1-12)")
    parser.add_argument("--dry-run", action="store_true", help="Do not upload; print what would happen")
    parser.add_argument("--limit", type=int, default=None, help="Export at most N items (debug/testing)")

    args = parser.parse_args(argv)

    table_name = str(args.table).strip() if args.table else (_default_table_name_from_env() or "").strip()
    if not table_name:
        raise SystemExit(
            "Missing DynamoDB table name. Provide --table or set ACTIVE_SUBMISSIONS_TABLE_NAME "
            "(preferred) / SUBMISSIONS_TABLE."
        )

    prefix_base = str(args.prefix_base).strip().strip("/")
    if not prefix_base:
        raise SystemExit("prefix-base must not be empty")

    return ExportConfig(
        table_name=table_name,
        region=str(args.region),
        bucket=str(args.bucket),
        prefix_base=prefix_base,
        year=int(args.year),
        month=int(args.month),
        dry_run=bool(args.dry_run),
        limit=args.limit,
    )


def main(argv: Optional[list[str]] = None) -> int:
    cfg = parse_args(argv)

    # Import lazily so unit tests can import this module without AWS dependencies.
    import boto3

    start_datum_iso, end_datum_iso = _month_window_iso_date(cfg.year, cfg.month)
    snapshot_dt = datetime.now(timezone.utc)
    snapshot_at = _format_snapshot_folder_timestamp(snapshot_dt)

    data_key, manifest_key = _build_s3_keys(
        prefix_base=cfg.prefix_base,
        year=cfg.year,
        month=cfg.month,
        snapshot_at=snapshot_at,
    )

    dynamodb = boto3.resource("dynamodb", region_name=cfg.region)
    table = dynamodb.Table(cfg.table_name)

    items_iter = _iter_scan_items(
        table,
        start_datum_iso=start_datum_iso,
        end_datum_iso=end_datum_iso,
        limit=cfg.limit,
    )

    payload, row_count, sha256_hex = _encode_jsonl_gz(items_iter)

    manifest = {
        "exported_at_utc": _format_iso_utc(snapshot_dt),
        "source": {
            "dynamodb_table": cfg.table_name,
            "region": cfg.region,
        },
        "range": {
            "filter_field": "datum_iso",
            "datum_iso_start_inclusive": start_datum_iso,
            "datum_iso_end_exclusive": end_datum_iso,
        },
        "output": {
            "bucket": cfg.bucket,
            "data_key": data_key,
            "manifest_key": manifest_key,
            "format": "jsonl.gz",
            "row_count": row_count,
            "sha256_jsonl_uncompressed": sha256_hex,
        },
    }

    if cfg.dry_run:
        print("DRY RUN")
        print(f"- table: {cfg.table_name} ({cfg.region})")
        print(f"- month window: [{start_datum_iso}, {end_datum_iso})")
        print(f"- rows: {row_count}")
        print(f"- s3://{cfg.bucket}/{data_key}")
        print(f"- s3://{cfg.bucket}/{manifest_key}")
        return 0

    s3 = boto3.client("s3", region_name=cfg.region)

    s3.put_object(
        Bucket=cfg.bucket,
        Key=data_key,
        Body=payload,
        ContentType="application/json",
        ContentEncoding="gzip",
        Metadata={
            "exported_at_utc": manifest["exported_at_utc"],
            "source_table": cfg.table_name,
            "range_start": start_datum_iso,
            "range_end": end_datum_iso,
        },
    )

    s3.put_object(
        Bucket=cfg.bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
        Metadata={
            "exported_at_utc": manifest["exported_at_utc"],
            "source_table": cfg.table_name,
        },
    )

    print("EXPORT OK")
    print(f"- rows: {row_count}")
    print(f"- s3://{cfg.bucket}/{data_key}")
    print(f"- s3://{cfg.bucket}/{manifest_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


