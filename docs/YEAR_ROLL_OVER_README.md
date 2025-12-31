# Year Roll-Over Runbook (active ↔ passive)

This repo models submissions as **two DynamoDB tables**:
- **active**: current year (used by frontend/API)
- **passive**: previous year (kept for roll-over / migration tooling)

The roll-over is an **infrastructure + configuration switch**: update which physical table is considered “active” and redeploy.

---

### Key facts (how the system is wired)

- **External configuration (required at deploy time)**
  - `ACTIVE_SUBMISSIONS_TABLE_NAME`
  - `PASSIVE_SUBMISSIONS_TABLE_NAME`

- **DynamoDB (CDK)**
  - The table schema is unchanged:
    - Partition key: `user_id`
    - Sort key: `timestamp_utc` (ISO-8601 UTC string)
  - Tables use **PITR** and **RemovalPolicy.RETAIN**.
  - `DynamoDBStack` creates/keeps both physical tables named by the two env vars and exports role-based outputs:
    - `DataCollectionSubmissionsActiveTableName-<env>`
    - `DataCollectionSubmissionsActiveTableArn-<env>`
    - `DataCollectionSubmissionsPassiveTableName-<env>`
    - `DataCollectionSubmissionsPassiveTableArn-<env>`
  - Swapping the env var values swaps the **exports** (active ↔ passive) while keeping the **same two tables** (no renames during the swap).

- **API / Lambda**
  - Lambda handlers do **not** hardcode a year; they read the active table from env var `SUBMISSIONS_TABLE`.
  - `APIStack` imports the **active** exports, sets `SUBMISSIONS_TABLE`, and grants DynamoDB permissions to the **active table ARN only**.
  - (Optional) `PASSIVE_SUBMISSIONS_TABLE` is also provided to Lambdas for future tooling/migrations.

---

### Application behavior (choose intentionally)

Switching to a new active table changes user-visible behavior:

- **History / Analyze**
  - The UI uses `/history` to compute YTD stats.
  - After cutover, `/history` shows **only the active table**.

- **Deltas**
  - The submit handler computes deltas from the previous submission by querying the same table.
  - After cutover, the first record in the new active table will have deltas of **0** (no previous item in that table).

If you need **cross-year history** or **cross-year deltas**, implement it explicitly (query both tables, or fall back when active has no prior record). That is a product decision and requires app + IAM changes.

---

### Cutover sequence (safe order)

The safe order matters because `APIStack` imports table values from exports.

#### T-2 days (prepare)

- **Step A — Finalize exports/backups**
  - Export remaining months for the current active year (at minimum December).
  - Verify S3 manifests exist and look correct.

- **Step B — Ensure both tables exist and are exported**
  - Deploy `DynamoDBStack` with env vars set to the two physical table names you want to keep, for example:

```bash
export ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2025
export PASSIVE_SUBMISSIONS_TABLE_NAME=submissions-2026
```

  - Verify:
    - both tables exist
    - PITR is enabled
    - the active/passive CloudFormation exports exist for your environment

#### T0 (Jan 1, shortly after midnight): switch

- **Step C — Swap active/passive via env vars**

```bash
export ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2026
export PASSIVE_SUBMISSIONS_TABLE_NAME=submissions-2025
```

- **Step D — Deploy in order**
  - Deploy `DynamoDBStack` first (updates exports)
  - Deploy `APIStack` next (repoints Lambdas and IAM to the new active table)

- **Step E — Smoke test**
  - Submit one record and verify:
    - data lands in the new active table
    - `/recent` works
    - `/history` works
    - UI can submit and shows recent submissions

---

### Rollback plan (fast)

If something is wrong after cutover:
- Swap the env vars back (active ↔ passive) and redeploy `DynamoDBStack`, then `APIStack`.
- Both tables are retained; data remains intact.

---

### Ops scripts (table selection)

Ops scripts **do not default to a hardcoded year**. They require a table via:
- `--table ...`, or
- `ACTIVE_SUBMISSIONS_TABLE_NAME` / `SUBMISSIONS_TABLE` env var.

Example:

```bash
export ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2026
python scripts/export_dynamodb_to_s3.py --bucket <YOUR_DATALAKE_BUCKET> --region eu-central-1 --year 2026 --month 1
```


