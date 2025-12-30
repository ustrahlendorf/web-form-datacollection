## DynamoDB → S3 DataLake snapshots (dev)

This repo keeps the *operational* dataset in DynamoDB (small, ~365 rows/year) and
exports monthly “snapshots” into a versioned S3 bucket that acts as a **mini DataLake**
for later analysis (graphs, Athena/Glue, batch jobs, etc.).

The first implementation is intentionally **manual**. A later revision can schedule
it monthly (EventBridge → Lambda).

### Where the data goes (S3 layout)

The export script writes to an Athena/Glue-friendly prefix structure:

- `exports/submissions/year=YYYY/month=MM/snapshot_at=YYYY-MM-DDTHHMMSSZ/part-000.jsonl.gz`
- `exports/submissions/year=YYYY/month=MM/snapshot_at=YYYY-MM-DDTHHMMSSZ/manifest.json`

Notes:
- `snapshot_at=...` allows multiple snapshots per month without overwriting.
- The bucket is **versioned**, so even overwrites are recoverable.

### Prerequisites

- **AWS credentials** available to `boto3` (env vars, shared config, SSO, instance profile, …)
- The **DataLake bucket** exists (created by CDK stack `DataCollectionDataLake-dev`)
- The **DynamoDB table** exists (currently `submissions-2025`)

### Find the DataLake bucket name

When you deploy CDK, the output includes `DataLakeBucketName`.
You can also look up the CloudFormation export:

- `DataCollectionDataLakeBucketName-dev`

### Manual monthly export (recommended)

Run from the repo folder `web-form-verbrauch/`:

```bash
python scripts/export_dynamodb_to_s3.py \
  --bucket data-collection-datalake-dev-123456789012-eu-central-1 \
  --table submissions-2025 \
  --region eu-central-1 \
  --year 2025 \
  --month 1
```

Dry-run (no upload; prints what would happen):

```bash
python scripts/export_dynamodb_to_s3.py \
  --bucket data-collection-datalake-dev-123456789012-eu-central-1 \
  --table submissions-2025 \
  --region eu-central-1 \
  --year 2025 \
  --month 1 \
  --dry-run
```

### How month filtering works (important)

The table key schema is:
- partition key: `user_id`
- sort key: `timestamp_utc`

Because we can’t query “all users by time” efficiently without a GSI, the exporter uses:
- **Scan + FilterExpression** on `datum_iso`

This is acceptable because the table is intentionally tiny. Filtering assumes:
- `datum` is stored as dd.mm.yyyy (example: `03.01.2025`)
- `datum_iso` is stored as YYYY-MM-DD (example: `2025-01-03`)

### Year rollover runbook (recommended approach)

This repo already models submissions as **year-specific DynamoDB tables** (e.g. `submissions-2025`).
That matches the “clean start each year” requirement well.

At year end / on Jan 1:
- **Step 1: Final exports**: export the remaining months (or export the full year one last time).
- **Step 2: New-year table**: create a new DynamoDB table for the new year (e.g. `submissions-2026`) and repoint the app.
- **Step 3: Keep last quarter for comparison** (optional):
  - Keep Q4 data available for comparison either by:
    - keeping the previous-year DynamoDB table, or
    - relying on the S3 DataLake (preferred “source of truth” for historical data).

If you want DynamoDB to only keep the last quarter:
- After confirming the full-year export exists in S3, run an explicit cleanup job that deletes
  items older than ~90 days.
  - This is intentionally a manual, controlled action (not automated) to avoid accidental loss.


