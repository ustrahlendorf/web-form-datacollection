# Year Roll-Over Runbook (2025 → 2026)

This repository currently models submissions as **year-specific DynamoDB tables** (e.g. `submissions-2025`). The year roll-over is therefore primarily an **infrastructure + configuration switch**: create the new year table and repoint the API Lambdas to it.

This document is the operational runbook for the cutover.

---

### Key facts (how the system is wired)

- **DynamoDB**
  - The DynamoDB table name is currently fixed to `submissions-2025` in CDK (`DynamoDBStack`).
  - The table schema is:
    - Partition key: `user_id`
    - Sort key: `timestamp_utc` (ISO-8601 UTC string)
  - Table uses **PITR** and **RemovalPolicy.RETAIN**.

- **API / Lambda**
  - Lambda handlers do **not** hardcode a year; they read the table from env var `SUBMISSIONS_TABLE`.
  - CDK (`APIStack`) sets `SUBMISSIONS_TABLE` based on a CloudFormation export and grants DynamoDB permissions based on the exported table ARN.

- **DataLake / S3 backups**
  - The S3 DataLake bucket is long-lived (one bucket across years) and stores exports under:
    - `exports/submissions/year=YYYY/month=MM/snapshot_at=.../part-000.jsonl.gz`
    - `exports/submissions/year=YYYY/month=MM/snapshot_at=.../manifest.json`

---

### What must change for a new year

#### Stacks (required)

- **Create a new DynamoDB table**: `submissions-2026`
  - Recommended: keep `submissions-2025` unchanged and **add** a second table for 2026.
  - Add new CloudFormation exports for 2026:
    - `DataCollectionSubmissionsTableName2026-<env>`
    - `DataCollectionSubmissionsTableArn2026-<env>`

- **Repoint the API stack to 2026**
  - Update `APIStack` to import the `...2026...` exports
  - Update Lambda execution role policy to allow actions on the **2026 table ARN**
  - Update Lambda environment variable `SUBMISSIONS_TABLE` to the **2026 table name**

#### Application behavior (choose intentionally)

No backend validator blocks year 2026. However, switching to a new table changes behavior:

- **History / Analyze**
  - The UI (Analyze page) uses `/history` to compute YTD stats.
  - After cutover, `/history` will show **only 2026** because it reads only the currently configured table.

- **Deltas**
  - The submit handler computes deltas from the previous submission for the user by querying the same table.
  - After cutover, the first 2026 record will have deltas of **0** (no previous item in the 2026 table).

If you need **cross-year history** or **cross-year deltas**, implement it explicitly (e.g., query both tables, or fall back to the 2025 table when 2026 has no prior record). That is an intentional product decision and requires app + IAM changes.

#### Ops scripts (recommended)

Several ops scripts default to `submissions-2025`. For 2026 operations, always pass `--table submissions-2026` (recommended), and/or update defaults:

- `scripts/export_dynamodb_to_s3.py` has `DEFAULT_TABLE_NAME = "submissions-2025"`
- `scripts/backfill_datum_iso.py` has `DEFAULT_TABLE_NAME = "submissions-2025"`
- `scripts/import_submissions_csv.py` has `DEFAULT_TABLE_NAME = "submissions-2025"`

---

### Cutover sequence (safe order)

The safe order matters because `APIStack` imports table values from exports.

#### T-2 days (prepare)

- **Step A — Finalize 2025 exports/backups**
  - Export remaining months for 2025 (at minimum December), or run a final full-year export plan.
  - Verify S3 manifests exist and look correct.

- **Step B — Deploy DynamoDB changes (add 2026)**
  - Deploy the stack update that creates `submissions-2026` and exports its name/arn.
  - Verify:
    - Table exists
    - PITR is enabled
    - The two 2026 CloudFormation exports exist for your environment

This step should be non-impacting; the running app still uses 2025 until you change the API.

#### T-1 day (validate readiness)

- **Step C — Confirm “behavioral expectations”**
  - Confirm stakeholders accept:
    - history resets to the new year (or not)
    - deltas reset at the year boundary (or not)
  - If not accepted, schedule the required app change before cutover.

- **Step D — Prepare the API stack change**
  - Ensure the API stack is ready to import the `...2026...` exports.

#### T0 (Jan 1, shortly after midnight): switch

- **Step E — Deploy API repoint to 2026**
  - Deploy `APIStack` so Lambdas point to `submissions-2026`.

- **Step F — Smoke test**
  - Submit one record dated `01.01.2026` and verify:
    - Data lands in `submissions-2026`
    - `/recent` works
    - `/history` works
    - UI can submit and shows recent submissions

#### Post-cutover (Jan 1)

- **Step G — Monitoring**
  - Watch CloudWatch logs for:
    - AccessDenied to DynamoDB
    - “table not found”
    - spikes in 5xx responses

- **Step H — Update operator defaults**
  - Update docs/scripts (or enforce passing `--table`) so exports/imports/backfills don’t accidentally target 2025.

---

### Rollback plan (fast)

If something is wrong after cutover:

- **Rollback**: redeploy `APIStack` to point back to the 2025 exports (`...2025...`).
- `submissions-2025` is retained and remains intact.
- The DataLake bucket is versioned; exports are recoverable.

---

### Quick command examples (ops)

#### Export January 2026 from DynamoDB to S3

```bash
python scripts/export_dynamodb_to_s3.py \
  --bucket <YOUR_DATALAKE_BUCKET> \
  --table submissions-2026 \
  --region eu-central-1 \
  --year 2026 \
  --month 1
```

#### Backfill `datum_iso` (only needed for legacy rows that predate `datum_iso`)

```bash
python scripts/backfill_datum_iso.py \
  --table submissions-2026 \
  --region eu-central-1
```

---

### Checklist (printable)

- **Before Jan 1**
  - [ ] 2025 exports complete and verified in S3
  - [ ] `submissions-2026` exists (PITR enabled)
  - [ ] 2026 CloudFormation exports exist (name + arn)
  - [ ] Decision made: cross-year history/deltas required? (yes/no)

- **Cutover**
  - [ ] APIStack deployed to 2026
  - [ ] Smoke test submit OK
  - [ ] Smoke test recent/history OK

- **After**
  - [ ] Monitoring clean (no DynamoDB permission errors)
  - [ ] Script defaults/docs updated or operators instructed to pass `--table`


