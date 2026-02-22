# Year Roll-Over Runbook (active ↔ passive, via SSM pointers)

This repo models submissions as **two DynamoDB tables**:
- **active**: current year (used by frontend/API)
- **passive**: previous year (kept for roll-over / migration tooling)

The roll-over is an **infrastructure switch**: update which physical table is considered “active” by updating **SSM Parameter Store pointers**, then redeploy the API so Lambdas + IAM point at the new active table.

---

### One-time prerequisite: deploy InitStack (SSM contract)

InitStack creates the stable SSM “contract” parameters under the namespace prefix (single environment, no env segment):
- `SSM_NAMESPACE_PREFIX=/HeatingDataCollection` (see `taskfile.env`)

Deploy it once before your first roll-over:

```bash
# from web-form-verbrauch/ (repo root)
task deploy-init

# optional: verify InitStack parameters exist
task ssm:init:show
```

### Key facts (how the system is wired)

- **SSM “contract” (required at deploy time)**
  - The API stack reads these parameters at deploy time (not at runtime):
    - `/HeatingDataCollection/Submissions/Active/TableName`
    - `/HeatingDataCollection/Submissions/Active/TableArn`
    - `/HeatingDataCollection/Submissions/Passive/TableName`
    - `/HeatingDataCollection/Submissions/Passive/TableArn`

- **DynamoDB (CDK)**
  - The table schema is unchanged:
    - Partition key: `user_id`
    - Sort key: `timestamp_utc` (ISO-8601 UTC string)
  - Tables use **PITR** and **RemovalPolicy.RETAIN**.
  - `DynamoDBStack` owns the pointer values by publishing the **active/passive table name + ARN** into SSM under the paths above.

- **API / Lambda**
  - Lambda handlers do **not** hardcode a year; they read the active table from env var `SUBMISSIONS_TABLE`.
  - `APIStack` reads **Active/TableName** from SSM, sets `SUBMISSIONS_TABLE`, and grants DynamoDB permissions to **Active/TableArn only**.
  - Because the API reads SSM at **deploy time**, you must redeploy the API after changing the SSM pointers.

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

The safe order matters because the API stack must be redeployed to pick up the new SSM pointer values.

### Operational guidance (helps avoid edge cases)

- Pick a controlled cutover window where you can watch logs for ~15–30 minutes.
- Avoid heavy usage during the flip (reduces the chance of “writes split across years”).
- Optional: ask users for a short “quiet period” (a couple minutes) right around the flip.

#### T-2 days (prepare)

- **Step A — Finalize S3 exports/backups**
  - Export remaining months for the current active year (at minimum December).
  - Verify S3 manifests exist and look correct.

- **Step B — Ensure both tables exist**
  - Ensure the next-year table exists (can be done weeks before cutover).
  - If your `DynamoDBStack` uses environment variables to define the two physical table names, set them to the two physical table names you want to keep, for example:

```bash
export ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2025
export PASSIVE_SUBMISSIONS_TABLE_NAME=submissions-2026
```

  - Verify:
    - both tables exist
    - PITR is enabled
    - the SSM pointer parameters exist (see verification commands below)

#### T0 (Jan 1, shortly after midnight): switch

- **Step C — Swap active/passive**

  Update `taskfile.env` (or export in your shell) with the new table names:

```bash
ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2026
PASSIVE_SUBMISSIONS_TABLE_NAME=submissions-2025
```

  If using the Taskfile, it loads `taskfile.env` automatically. Otherwise, `export` these before running CDK.

- **Step D — Deploy in order** (from `web-form-verbrauch/`)

  - Deploy `DynamoDBStack` first (updates the SSM pointers): `task deploy-dynamodb`
  - Deploy `APIStack` next (repoints Lambdas and IAM to the new active table): `task deploy-api`

- **Step E — Smoke test**
  - Submit one record and verify:
    - data lands in the new active table
    - `/recent` works
    - `/history` works
    - UI can submit and shows recent submissions
  - Monitor CloudWatch logs for the submit/recent/history Lambdas for 5–10 minutes:
    - `AccessDenied` (usually IAM points at the wrong table ARN)
    - `ResourceNotFoundException` (usually table name mismatch / wrong pointer)

---

### Verification (SSM pointers + DynamoDB)

Run these checks before and after cutover.

#### 1) Read pointer parameters

```bash
aws ssm get-parameter --name "/HeatingDataCollection/Submissions/Active/TableName" --query "Parameter.Value" --output text
aws ssm get-parameter --name "/HeatingDataCollection/Submissions/Active/TableArn"  --query "Parameter.Value" --output text
aws ssm get-parameter --name "/HeatingDataCollection/Submissions/Passive/TableName" --query "Parameter.Value" --output text
aws ssm get-parameter --name "/HeatingDataCollection/Submissions/Passive/TableArn"  --query "Parameter.Value" --output text
```

Expected:
- Active points to the current-year table (e.g. `submissions-2026` right after Jan 1 cutover).
- Passive points to the previous-year table (e.g. `submissions-2025` right after Jan 1 cutover).

#### 2) Confirm the active table exists and is the one receiving writes

```bash
ACTIVE_TABLE="$(aws ssm get-parameter --name "/HeatingDataCollection/Submissions/Active/TableName" --query "Parameter.Value" --output text)"
aws dynamodb describe-table --table-name "$ACTIVE_TABLE" --query "Table.TableStatus" --output text
```

After deploying `APIStack`, submit one record and confirm it lands in `$ACTIVE_TABLE`.

---

### Rollback plan (fast)

If something is wrong after cutover:
- Swap the env vars back (active ↔ passive) and redeploy `DynamoDBStack`, then `APIStack`.
- Both tables are retained; data remains intact.

---

### Legacy deployments (do not use unless you’re on an old stack wiring model)

If your deployment still uses CloudFormation `Export`/`ImportValue` wiring (pre-SSM refactor), see:
- `docs/legacy/year-roll-over-cloudformation-export-in-use-fix.md`

### Ops scripts (table selection)

Ops scripts **do not default to a hardcoded year**. They require a table via:
- `--table ...`, or
- `ACTIVE_SUBMISSIONS_TABLE_NAME` / `SUBMISSIONS_TABLE` env var.

Example:

```bash
# Using env var (preferred)
export ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2026
python scripts/export_dynamodb_to_s3.py --bucket <YOUR_DATALAKE_BUCKET> --region eu-central-1 --year 2026 --month 1

# Or using --table explicitly
python scripts/export_dynamodb_to_s3.py --table submissions-2026 --bucket <YOUR_DATALAKE_BUCKET> --region eu-central-1 --year 2026 --month 1
```


