## DynamoDB → S3 DataLake snapshots (dev)

This repo keeps the *operational* dataset in DynamoDB (small, ~365 rows/year) and
exports monthly "snapshots" into a versioned S3 bucket that acts as a **mini DataLake**
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
- The **DynamoDB table** exists (use the current active table; see `runbooks/year-rollover.md`)

### Find the DataLake bucket name

When you deploy CDK, the output includes `DataLakeBucketName`.
You can also look up the CloudFormation export:

- `DataCollectionDataLakeBucketName-dev`

### Manual monthly export (recommended)

Run from the repo root `web-form-verbrauch/`:

```bash
# Using env var (preferred)
export ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2025
python scripts/export_dynamodb_to_s3.py \
  --bucket data-collection-datalake-dev-123456789012-eu-central-1 \
  --region eu-central-1 \
  --year 2025 \
  --month 1

# Or using --table explicitly
python scripts/export_dynamodb_to_s3.py \
  --table submissions-2025 \
  --bucket data-collection-datalake-dev-123456789012-eu-central-1 \
  --region eu-central-1 \
  --year 2025 \
  --month 1
```

Dry-run (no upload; prints what would happen):

```bash
export ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2025
python scripts/export_dynamodb_to_s3.py \
  --bucket data-collection-datalake-dev-123456789012-eu-central-1 \
  --region eu-central-1 \
  --year 2025 \
  --month 1 \
  --dry-run
```

### How month filtering works (important)

The table key schema is:
- partition key: `user_id`
- sort key: `timestamp_utc`

Because we can't query "all users by time" efficiently without a GSI, the exporter uses:
- **Scan + FilterExpression** on `datum_iso`

This is acceptable because the table is intentionally tiny. Filtering assumes:
- `datum` is stored as dd.mm.yyyy (example: `03.01.2025`)
- `datum_iso` is stored as YYYY-MM-DD (example: `2025-01-03`)

### Year rollover

For switching active ↔ passive DynamoDB tables at year end, see `runbooks/year-rollover.md`.
Before cutover, run final exports for the outgoing year (e.g. December).
