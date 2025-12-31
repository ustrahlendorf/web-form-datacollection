"""
One-off CSV importer for the Data Collection application.

Purpose
-------
Import historical submission rows from a prepared CSV file into a DynamoDB table
(defaults to `ACTIVE_SUBMISSIONS_TABLE_NAME` / `SUBMISSIONS_TABLE` if set; otherwise require `--table`).

The prepared CSV matches the `submissions-dev` item attribute layout, but the
primary key attributes (`user_id`, `timestamp_utc`) may be missing. This script
injects them during import:
  - user_id: constant (CLI option; defaults to provided UUID)
  - timestamp_utc: generated as an ISO-8601 UTC timestamp per row, starting at
    a base timestamp and adding a fixed offset (+10 seconds per row by default)
    to guarantee uniqueness.

Notes
-----
- This is intentionally a *one-off ops tool* (no app UI).
- Re-running the import will create additional items (new timestamps).
"""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4


DEFAULT_REGION = "eu-central-1"
DEFAULT_USER_ID = "53e4e8d2-0061-7063-6f27-aeb8e89b9515"


@dataclass(frozen=True)
class ImportConfig:
    csv_path: Path
    table_name: str
    region: str
    user_id: str
    start_timestamp_utc: datetime
    step_seconds: int
    delimiter: str
    dry_run: bool
    limit: Optional[int]

def _default_table_name_from_env() -> Optional[str]:
    """
    Prefer the active submissions table name from deployment/runtime configuration.

    Supported env vars:
    - ACTIVE_SUBMISSIONS_TABLE_NAME (preferred)
    - SUBMISSIONS_TABLE
    """
    return os.environ.get("ACTIVE_SUBMISSIONS_TABLE_NAME") or os.environ.get("SUBMISSIONS_TABLE")


def _parse_iso_utc_timestamp(value: str) -> datetime:
    """
    Parse a UTC ISO-8601 timestamp.

    Accepts:
    - 2025-12-21T14:03:12Z
    - 2025-12-21T14:03:12.123Z
    """
    v = (value or "").strip()
    if not v:
        raise ValueError("start timestamp is empty")

    if v.endswith("Z"):
        v = v[:-1] + "+00:00"

    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        # Treat naive timestamps as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso_utc(dt: datetime) -> str:
    """
    Format as UTC ISO-8601 with Z suffix (seconds precision), matching app format.
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _datum_to_iso(datum_ddmmyyyy: str) -> str:
    """
    Convert dd.mm.yyyy -> YYYY-MM-DD for correct lexical range filtering.
    """
    v = (datum_ddmmyyyy or "").strip()
    return datetime.strptime(v, "%d.%m.%Y").date().isoformat()


def _coerce_int(value: Any, field: str) -> int:
    v = "" if value is None else str(value).strip()
    if v == "":
        raise ValueError(f"Missing required int field: {field}")
    return int(v)


def _coerce_optional_int(value: Any, default: int = 0) -> int:
    v = "" if value is None else str(value).strip()
    if v == "":
        return default
    return int(v)


def _coerce_decimal(value: Any, field: str) -> Decimal:
    v = "" if value is None else str(value).strip()
    if v == "":
        raise ValueError(f"Missing required decimal field: {field}")
    try:
        return Decimal(v)
    except InvalidOperation as e:
        raise ValueError(f"Invalid decimal for {field}: {v}") from e


def _coerce_optional_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    v = "" if value is None else str(value).strip()
    if v == "":
        return default
    try:
        return Decimal(v)
    except InvalidOperation as e:
        raise ValueError(f"Invalid decimal: {v}") from e


def row_to_item(
    row: Dict[str, Any],
    *,
    user_id: str,
    timestamp_utc: str,
) -> Dict[str, Any]:
    """
    Convert a CSV row (dict of string->string) to a DynamoDB item dict.

    The CSV is expected to contain the same attributes stored in DynamoDB items,
    except it may omit the primary keys.

    Required fields (based on the app model/validators):
    - datum, uhrzeit, betriebsstunden, starts, verbrauch_qm
    """
    item: Dict[str, Any] = {}

    # Primary keys injected
    item["user_id"] = user_id
    item["timestamp_utc"] = timestamp_utc

    # submission_id: keep if present, otherwise generate
    submission_id = (row.get("submission_id") or "").strip()
    item["submission_id"] = submission_id if submission_id else str(uuid4())

    # Required business fields
    item["datum"] = (row.get("datum") or "").strip()
    item["uhrzeit"] = (row.get("uhrzeit") or "").strip()
    if not item["datum"]:
        raise ValueError("Missing required field: datum")
    if not item["uhrzeit"]:
        raise ValueError("Missing required field: uhrzeit")

    # Derived field for filtering/analytics
    item["datum_iso"] = _datum_to_iso(item["datum"])

    item["betriebsstunden"] = _coerce_int(row.get("betriebsstunden"), "betriebsstunden")
    item["starts"] = _coerce_int(row.get("starts"), "starts")
    item["verbrauch_qm"] = _coerce_decimal(row.get("verbrauch_qm"), "verbrauch_qm")

    # Optional delta fields (default to 0)
    item["delta_betriebsstunden"] = _coerce_optional_int(row.get("delta_betriebsstunden"), 0)
    item["delta_starts"] = _coerce_optional_int(row.get("delta_starts"), 0)
    item["delta_verbrauch_qm"] = _coerce_optional_decimal(row.get("delta_verbrauch_qm"), Decimal("0"))

    # Preserve any additional columns that might exist in the dataset (best-effort).
    # Avoid overriding keys we set above.
    for k, v in row.items():
        if k in item:
            continue
        if v is None:
            continue
        vv = str(v).strip()
        if vv == "":
            continue
        item[k] = vv

    return item


def iter_items_from_csv(
    csv_path: Path,
    *,
    user_id: str,
    start_timestamp_utc: datetime,
    step_seconds: int,
    delimiter: str = ";",
    limit: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """
    Yield DynamoDB item dicts from a CSV file, injecting keys as configured.
    """
    if step_seconds <= 0:
        raise ValueError("step_seconds must be > 0")

    if not isinstance(delimiter, str) or len(delimiter) != 1:
        raise ValueError("delimiter must be a single character")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("CSV has no header / no columns detected")

        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            ts = start_timestamp_utc + timedelta(seconds=i * step_seconds)
            yield row_to_item(
                row,
                user_id=user_id,
                timestamp_utc=_format_iso_utc(ts),
            )


def parse_args(argv: Optional[list[str]] = None) -> ImportConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Import prepared submissions CSV into DynamoDB "
            "(uses ACTIVE_SUBMISSIONS_TABLE_NAME / SUBMISSIONS_TABLE by default)."
        )
    )
    parser.add_argument("--csv", required=True, help="Path to prepared CSV file")
    parser.add_argument("--table", default=None, help="Target DynamoDB table name")
    parser.add_argument("--region", default=DEFAULT_REGION, help="AWS region")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="Constant user_id to inject")
    parser.add_argument(
        "--delimiter",
        default=";",
        help="CSV delimiter character (default: ';')",
    )
    parser.add_argument(
        "--start-timestamp-utc",
        default=None,
        help="Base timestamp (UTC ISO-8601). If omitted, uses current UTC time.",
    )
    parser.add_argument(
        "--step-seconds",
        type=int,
        default=10,
        help="Seconds to add per row (default: 10) to guarantee unique sort keys",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and print summary only; do not write")
    parser.add_argument("--limit", type=int, default=None, help="Only import first N rows (for testing)")

    args = parser.parse_args(argv)

    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV file does not exist: {csv_path}")

    table_name = str(args.table).strip() if args.table else (_default_table_name_from_env() or "").strip()
    if not table_name:
        raise SystemExit(
            "Missing DynamoDB table name. Provide --table or set ACTIVE_SUBMISSIONS_TABLE_NAME "
            "(preferred) / SUBMISSIONS_TABLE."
        )

    if args.start_timestamp_utc:
        start_dt = _parse_iso_utc_timestamp(args.start_timestamp_utc)
    else:
        start_dt = datetime.now(timezone.utc)

    return ImportConfig(
        csv_path=csv_path,
        table_name=table_name,
        region=str(args.region),
        user_id=str(args.user_id),
        start_timestamp_utc=start_dt,
        step_seconds=int(args.step_seconds),
        delimiter=str(args.delimiter),
        dry_run=bool(args.dry_run),
        limit=args.limit,
    )


def main(argv: Optional[list[str]] = None) -> int:
    cfg = parse_args(argv)

    # Import lazily so unit tests that only use helper functions can run without boto3/botocore.
    import boto3

    count = 0
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None

    if cfg.dry_run:
        for item in iter_items_from_csv(
            cfg.csv_path,
            user_id=cfg.user_id,
            start_timestamp_utc=cfg.start_timestamp_utc,
            step_seconds=cfg.step_seconds,
            delimiter=cfg.delimiter,
            limit=cfg.limit,
        ):
            count += 1
            ts = item["timestamp_utc"]
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        print(
            f"DRY RUN OK: rows={count}, table={cfg.table_name}, user_id={cfg.user_id}, "
            f"first_ts={first_ts}, last_ts={last_ts}, step_seconds={cfg.step_seconds}"
        )
        return 0

    dynamodb = boto3.resource("dynamodb", region_name=cfg.region)
    table = dynamodb.Table(cfg.table_name)

    with table.batch_writer() as batch:
        for item in iter_items_from_csv(
            cfg.csv_path,
            user_id=cfg.user_id,
            start_timestamp_utc=cfg.start_timestamp_utc,
            step_seconds=cfg.step_seconds,
            delimiter=cfg.delimiter,
            limit=cfg.limit,
        ):
            count += 1
            ts = item["timestamp_utc"]
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            batch.put_item(Item=item)

    print(
        f"IMPORT OK: rows={count}, table={cfg.table_name}, user_id={cfg.user_id}, "
        f"first_ts={first_ts}, last_ts={last_ts}, step_seconds={cfg.step_seconds}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


