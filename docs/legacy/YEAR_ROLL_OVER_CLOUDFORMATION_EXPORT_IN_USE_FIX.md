# (Legacy) Year roll-over deployment failure (CloudFormation export in use)

**Status**: Deprecated.

This document applies only to older deployments where `APIStack` used CloudFormation `Export`/`ImportValue` wiring for DynamoDB table names/ARNs.

The current design uses **SSM Parameter Store pointers** under `/HeatingDataCollection/Submissions/...` to decouple the stacks. For the up-to-date roll-over procedure, see:
- `docs/YEAR_ROLL_OVER_README.md`

### Summary (what went wrong)

During the year roll-over you swapped:

- `ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2026`
- `PASSIVE_SUBMISSIONS_TABLE_NAME=submissions-2025`

Then you deployed `DataCollectionDynamoDB-dev`.

CloudFormation failed with an event similar to:

- “Cannot update export `DataCollectionSubmissionsPassiveTableName-dev` as it is in use by `DataCollectionAPI-dev`.”

This happens because **CloudFormation Exports cannot be updated/removed while another stack is importing them**.

---

### Root cause (why the DynamoDB stack update was blocked)

In this repo:

- `DynamoDBStack` publishes these exports (per environment):
  - `DataCollectionSubmissionsActiveTableName-<env>`
  - `DataCollectionSubmissionsActiveTableArn-<env>`
  - `DataCollectionSubmissionsPassiveTableName-<env>`
  - `DataCollectionSubmissionsPassiveTableArn-<env>`

- `APIStack` imports:
  - the **active** table ARN (for IAM permissions)
  - the **active** table name (for Lambda env `SUBMISSIONS_TABLE`)
  - and (currently) the **passive** table name:
    - `Fn.import_value("DataCollectionSubmissionsPassiveTableName-<env>")`

So when you swap active/passive, `DynamoDBStack` must update the **passive export value** too — but CloudFormation refuses because `DataCollectionAPI-dev` is importing it.

---

### Recommended fix (Option A): remove the passive import from `APIStack`

Goal: make `APIStack` depend only on the **active** exports (as the runbook intent describes), and make passive wiring truly optional.

#### Exact change (high level)

In `APIStack`:

- Keep importing:
  - `DataCollectionSubmissionsActiveTableArn-<env>`
  - `DataCollectionSubmissionsActiveTableName-<env>`

- Remove importing:
  - `DataCollectionSubmissionsPassiveTableName-<env>`

- Stop passing `passive_submissions_table_name` into Lambda creation methods, so the Lambda env var `PASSIVE_SUBMISSIONS_TABLE` is **not set**.

This is safe because the Lambda helper methods already treat passive as optional: they only include `PASSIVE_SUBMISSIONS_TABLE` in the Lambda environment when a value is provided.

---

### Why this removes the deployment error

After Option A:

- `DataCollectionAPI-dev` no longer imports `DataCollectionSubmissionsPassiveTableName-dev`.
- Therefore `DataCollectionDynamoDB-dev` can update the passive export during rollover because it is **no longer “in use”** by any stack.
- The roll-over becomes the intended two-step:
  - deploy `DataCollectionDynamoDB-dev` (exports swap)
  - deploy `DataCollectionAPI-dev` (Lambdas + IAM point to the new active table)

Important operational note: `cdk deploy DataCollectionAPI-dev` will, by default, also attempt to deploy
dependency stacks (including DynamoDB). During recovery, you must deploy the API stack **exclusively**
so the “stop importing passive export” change lands before DynamoDB is updated.

---

### What changes in runtime behavior

- Normal app operation remains the same because the API/Lambdas use `SUBMISSIONS_TABLE` (active).
- Any “future tooling” that expected `PASSIVE_SUBMISSIONS_TABLE` to be provided to Lambdas will no longer receive it (unless it is reintroduced later in a different way).

---

### Future roll-overs (end of 2026 → 2027)

With Option A, you repeat the same procedure annually:

- Ensure the new year table exists (e.g. `submissions-2027`) via `DynamoDBStack` env vars.
- Set:
  - `ACTIVE_SUBMISSIONS_TABLE_NAME=submissions-2027`
  - `PASSIVE_SUBMISSIONS_TABLE_NAME=submissions-2026`
- Deploy in order:
  - `deploy-dynamodb`
  - `deploy-api`

**Important limitation**: the current design models only **two** DynamoDB tables (active + previous). Older years should be preserved via S3 exports/backups (or the architecture must be extended to support querying multiple historical tables).

---

### Note about the runbook

The runbook (`YEAR_ROLL_OVER_README.md`) describes passive as “optional” for API/Lambdas, but the current `APIStack` imports passive. Option A aligns the implementation with the runbook intent.


