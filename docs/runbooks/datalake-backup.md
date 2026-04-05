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

**Frequent auto-retrieval** (SchedulerFrequent stack) uses the same file format but a **separate** prefix so Glue/Athena can register a second table without mixing datasets:

- `exports/auto-retrieval-frequent/year=YYYY/month=MM/snapshot_at=.../part-000.jsonl.gz`
- `exports/auto-retrieval-frequent/year=YYYY/month=MM/snapshot_at=.../manifest.json`

**Passive submissions** (year table, not currently active for writes) exports use **`exports/submissions-passive/`** when you run Task **`export-datalake`** with `EXPORT_TARGET=passive` or `all` — same partition layout, distinct S3 prefix so Athena/Glue stays separate from active submissions.

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

### Taskfile: unified `export-datalake`

From the repo root, with `DATALAKE_BUCKET_NAME` (and for submissions/passive, `ACTIVE_SUBMISSIONS_TABLE_NAME` / `PASSIVE_SUBMISSIONS_TABLE_NAME`) in `taskfile.env` as for CDK:

| `EXPORT_TARGET` | DynamoDB source | S3 prefix base |
|-----------------|-----------------|----------------|
| `submissions` | `ACTIVE_SUBMISSIONS_TABLE_NAME` (via `--preset submissions`) | `exports/submissions/` |
| `passive` | `PASSIVE_SUBMISSIONS_TABLE_NAME` (`--table` + `--prefix-base`) | `exports/submissions-passive/` |
| `frequent` | `AUTO_RETRIEVAL_FREQUENT_TABLE_NAME` or default `submissions-auto-retrieval-frequent-<env>` | `exports/auto-retrieval-frequent/` |
| `all` | Runs **submissions**, then **passive**, then **frequent** (fail-fast) | (each prefix above) |

**Recommended (positional, after `--`):** pass **TARGET**, **YEAR**, **MONTH** as three arguments (go-task forwards them as `CLI_ARGS`):

```bash
task export-datalake -- submissions 2025 1
task export-datalake -- all 2025 1
```

**Alternative (named Task variables),** same as before:

```bash
task export-datalake EXPORT_TARGET=submissions EXPORT_YEAR=2025 EXPORT_MONTH=1
```

Restrictions for the positional form: exactly **three** tokens after `--`; **order** is fixed (`TARGET` then `YEAR` then `MONTH`); values must not contain spaces.

Frequent auto-retrieval only: `task export-datalake -- frequent YEAR MONTH` (same three-argument form).

### Frequent auto-retrieval table export (script)

The DynamoDB table name follows `submissions-auto-retrieval-frequent-<environment>` (for example `submissions-auto-retrieval-frequent-dev` from [scheduler_frequent_stack.py](../../infrastructure/stacks/scheduler_frequent_stack.py)).

Use **`--preset auto_retrieval_frequent`**, which sets the S3 prefix to `exports/auto-retrieval-frequent/` and reads the table name from **`AUTO_RETRIEVAL_FREQUENT_TABLE_NAME`** unless you pass **`--table`**.

```bash
export AUTO_RETRIEVAL_FREQUENT_TABLE_NAME=submissions-auto-retrieval-frequent-dev
export DATALAKE_BUCKET_NAME=data-collection-datalake-dev-123456789012-eu-central-1
python scripts/export_dynamodb_to_s3.py \
  --preset auto_retrieval_frequent \
  --bucket "$DATALAKE_BUCKET_NAME" \
  --region eu-central-1 \
  --year 2025 \
  --month 1
```

Or use Task: `task export-datalake -- frequent 2025 1`, or `EXPORT_TARGET=frequent` with named year/month.

Month filtering is the same as for submissions: **Scan + `datum_iso` range** for the requested calendar month. Items written by the frequent Lambda include `datum_iso` like the daily auto-retrieval path.

### Athena and AWS Glue

**Partitions:** Hive-style keys in the object path are `year`, `month`, and `snapshot_at`. In Athena, define these as **string** partition columns and point the table `LOCATION` at the dataset prefix (`exports/submissions/` or `exports/auto-retrieval-frequent/`).

**Manifest sidecar:** Each snapshot folder contains `manifest.json` next to `part-000.jsonl.gz`. Glue crawlers should **not** classify that file as data. Prefer either:

- a crawler **exclude pattern** that skips `**/manifest.json`, or
- a **data path** / classifier that only matches `*.jsonl.gz`.

**Data format:** One JSON object per line, gzip-compressed (`.jsonl.gz`). For Athena, a common choice is the **OpenX JSON SerDe** on a table with `STORED AS TEXTFILE` and data files ending in `.gz` (Athena recognizes gzip by suffix). You will likely need to run **`MSCK REPAIR TABLE`** (or use a Glue crawler) after new partitions appear, unless you configure **partition projection** on the table.

Example external table skeleton (replace bucket, adjust columns to match your items after a sample query):

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS auto_retrieval_frequent_export (
  user_id string,
  timestamp_utc string,
  datum string,
  datum_iso string,
  uhrzeit string,
  betriebsstunden bigint,
  starts bigint,
  verbrauch_qm string,
  delta_betriebsstunden bigint,
  delta_starts bigint,
  delta_verbrauch_qm string
  -- add optional vorlauf_temp, aussentemp, etc. as needed
)
PARTITIONED BY (
  year string,
  month string,
  snapshot_at string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES ('ignore.malformed.json' = 'true')
STORED AS TEXTFILE
LOCATION 's3://YOUR_DATALAKE_BUCKET/exports/auto-retrieval-frequent/'
TBLPROPERTIES ('classification'='json');
```

After uploading new snapshots, run `MSCK REPAIR TABLE auto_retrieval_frequent_export;` so partitions are discovered (or maintain a crawler on that prefix with the manifest excluded).

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
