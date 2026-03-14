# Auto-Retrieval Deployment Guide

Step-by-step guide to deploy and configure the automatic Viessmann data retrieval feature.

For AppConfig Agent adoption analysis and migration scope, see `docs/runbooks/appconfig-agent-fit.md`.

## Overview

The auto-retrieval feature:
- Runs once per 24 hours at a configurable time (default: 06:00 UTC)
- Fetches heating data from the Viessmann IoT API
- Stores the data in DynamoDB (same schema as manual submissions)
- Retries on connection failure (configurable attempts and delay)
- Skips storing if a submission for the same date already exists
- Publishes an SNS alert on repeated failures

## Prerequisites

- All base stacks deployed (Init, DynamoDB, API, Frontend)
- `VIESSMANN_CREDENTIALS_SECRET_ARN` set in `taskfile.env` (required for Viessmann API)
- Cognito user registered (you need the user's `sub` claim for configuration)

## AppConfig Change Test + Deploy Checklist

Use this sequence for releases that include AppConfig infrastructure and the new config API functions.

### 1) Run local tests before deploy

From repository root:

```bash
pytest -q \
  tests/test_appconfig_stack.py \
  tests/test_auto_retrieval_config_handler.py \
  tests/test_auto_retrieval_handler.py \
  tests/test_init_stack.py
```

### 2) Deploy stacks in dependency order

Deploy in this order so AppConfig resources and API write-path exist before scheduler runtime reads:

```bash
task deploy-init
task deploy-api-with-deps
task deploy-scheduler
task deploy-scheduler-frequent
```

### 3) Publish/verify AppConfig runtime baseline

After API deploy, publish baseline config via `PUT /config/auto-retrieval`:

```json
{
  "schemaVersion": 1,
  "frequentActiveWindows": [{"start": "00:00", "stop": "24:00"}],
  "maxRetries": 5,
  "retryDelaySeconds": 300,
  "userId": "YOUR_COGNITO_USER_SUB"
}
```

Then confirm with `GET /config/auto-retrieval` that values are active.

### 4) Validate new functions and runtime behavior

- Invoke/configure the API path (`GET` and `PUT /config/auto-retrieval`) and confirm:
  - validation rejects invalid windows/ranges
  - deployment is started for valid payloads
- Invoke both scheduler Lambdas (daily + frequent) once and verify CloudWatch logs show AppConfig read success.
- Confirm DynamoDB writes occur under the configured `userId`.

### 5) Migration-safety checks

- Keep `AUTO_RETRIEVAL_ENABLE_SSM_FALLBACK=true` during first rollout.
- If AppConfig read fails, verify Lambda falls back safely (and logs fallback usage).
- After at least one successful full schedule cycle, plan cutover to `AUTO_RETRIEVAL_ENABLE_SSM_FALLBACK=false`.

## Phase 1.5: Enable AppConfig Agent Extension

Phase 1 added AppConfig Agent-first runtime reads in `auto_retrieval_handler` with automatic fallback to AppConfigData SDK.
To activate real local-agent reads in AWS Lambda, attach the AppConfig Agent extension layer during deploy.

### 1) Export extension layer ARN before deploy

Set the layer ARN for your region/account (example format shown):

```bash
export APPCONFIG_AGENT_EXTENSION_LAYER_ARN="arn:aws:lambda:eu-central-1:123456789012:layer:AWS-AppConfig-Extension:1"
```

Then redeploy both scheduler stacks:

```bash
task deploy-scheduler
task deploy-scheduler-frequent
```

Note:
- If `APPCONFIG_AGENT_EXTENSION_LAYER_ARN` is not set, deployment still succeeds.
- In that case runtime continues with Agent-first code path enabled but typically falls back to AppConfigData SDK because no extension is attached.

### 2) Verify extension is attached

Check each function has a layer configured:

```bash
aws lambda get-function-configuration \
  --function-name DataCollectionScheduler-dev-AutoRetrievalHandler... \
  --region eu-central-1 \
  --query "Layers[].Arn"
```

Repeat for the frequent scheduler Lambda.

### 3) Post-deploy runtime verification checklist

Run this checklist for **both** daily and frequent scheduler Lambdas:

1. Invoke function once (manual invoke is fine).
2. In CloudWatch logs, confirm there is no `AppConfig Agent read failed` message on healthy runs.
3. Confirm config-dependent behavior remains correct (`userId`, retries, active windows).
4. Temporarily force an agent endpoint failure (for example, set `AUTO_RETRIEVAL_APPCONFIG_AGENT_ENDPOINT` to an invalid local URL in a test deploy), invoke again, and verify:
   - logs show `AppConfig Agent read failed`
   - runtime continues by falling back to AppConfigData SDK
   - function still completes (or fails only for unrelated reasons)
5. Restore the correct endpoint (`http://127.0.0.1:2772`) after the fallback test.

## Step 1: Deploy Init Stack (if not already done)

The Init stack creates SSM parameters including the new AutoRetrieval parameters.

```bash
task deploy-init
```

## Step 2: Publish AppConfig Baseline (Required)

Runtime auto-retrieval values are now sourced from AppConfig. Before scheduler rollout,
publish a baseline document equivalent to prior SSM runtime values.

Use API `PUT /config/auto-retrieval` with this baseline payload:

```json
{
  "schemaVersion": 1,
  "frequentActiveWindows": [{"start": "00:00", "stop": "24:00"}],
  "maxRetries": 5,
  "retryDelaySeconds": 300,
  "userId": "YOUR_COGNITO_USER_SUB"
}
```

If AppConfig is temporarily unavailable, Lambda can still read migration fallback values
from SSM while `AUTO_RETRIEVAL_ENABLE_SSM_FALLBACK=true` (default during migration).

### Settings tab operation (UI path)

You can also manage this payload from the web app:

1. Open the app and navigate to `#settings`
2. Click **Reload** to fetch current `GET /config/auto-retrieval` values
3. Edit active windows, retry values, and `userId`
4. Click **Save Settings** to call `PUT /config/auto-retrieval`
5. Confirm the success message includes:
   - config `versionNumber`
   - `deploymentNumber`
   - deployment `state` (typically `DEPLOYING` immediately after save)

Important: Save success confirms deployment was **started**. It does not guarantee rollout completion.

## Step 3: Configure AutoRetrieval User ID (SSM fallback only)

The auto-retrieval stores data under a single Cognito user. The primary source is AppConfig `userId`.
Set the SSM value only as fallback during migration.

**Option A: AWS Console**

1. Go to AWS Systems Manager → Parameter Store
2. Find `/HeatingDataCollection/AutoRetrieval/UserId`
3. Edit and set the value to your Cognito user's `sub` (e.g. `a1b2c3d4-e5f6-7890-abcd-ef1234567890`)

**Option B: AWS CLI**

```bash
aws ssm put-parameter \
  --name "/HeatingDataCollection/AutoRetrieval/UserId" \
  --value "YOUR_COGNITO_USER_SUB" \
  --type String \
  --overwrite \
  --region eu-central-1
```

To find your Cognito user `sub`:
- AWS Console → Cognito → User Pools → your pool → Users → select user → copy "User sub"
- Or decode the `id_token` JWT and read the `sub` claim

## Step 4: (Optional) Adjust Schedule and Runtime Settings

Deploy-time schedule values remain in SSM. Runtime values are managed in AppConfig.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `/HeatingDataCollection/AutoRetrieval/ScheduleCron` | `0 6 * * ? *` | EventBridge cron (06:00 UTC daily), deploy-time |
| `/HeatingDataCollection/AutoRetrieval/FrequentScheduleCron` | `0/15 * * * ? *` | EventBridge cron for frequent scheduler (every 15 min), deploy-time |
| AppConfig `frequentActiveWindows` | `[{"start":"00:00","stop":"24:00"}]` | Runtime active windows (UTC HH:MM, max 5 windows) |
| AppConfig `maxRetries` | `5` | Runtime max retry attempts on API failure |
| AppConfig `retryDelaySeconds` | `300` | Runtime seconds between retries |
| AppConfig `userId` | `SET_ME` | Runtime Cognito user `sub` |

Example: change schedule to 07:30 UTC:

```bash
aws ssm put-parameter \
  --name "/HeatingDataCollection/AutoRetrieval/ScheduleCron" \
  --value "30 7 * * ? *" \
  --type String \
  --overwrite \
  --region eu-central-1
```

**Note:** Changing `ScheduleCron` or `FrequentScheduleCron` in SSM requires redeploying the respective stack for the EventBridge Rule to pick up the new value (rules are created at deploy time from SSM values). AppConfig runtime changes do **not** require redeploy.

**Example: Restrict frequent scheduler to 08:00–12:00 and 14:00–18:00 UTC**

```bash
aws ssm put-parameter \
  --name "/HeatingDataCollection/AutoRetrieval/FrequentActiveWindows" \
  --value '[{"start":"08:00","stop":"12:00"},{"start":"14:00","stop":"18:00"}]' \
  --type String \
  --overwrite \
  --region eu-central-1
```

## Step 5: Deploy Scheduler Stack

```bash
task deploy-scheduler
```

This creates:
- Lambda function for auto-retrieval
- EventBridge Rule (cron schedule)
- SNS topic for failure alerts

## Step 6: Subscribe to SNS for Failure Alerts

1. Go to AWS SNS → Topics
2. Find `heating-auto-retrieval-failure-dev` (daily scheduler) or `heating-auto-retrieval-frequent-failure-dev` (frequent scheduler)
3. Create subscription:
   - Protocol: Email
   - Endpoint: your-email@example.com
4. Confirm the subscription (check your inbox)

## Frequent Scheduler (Multiple Runs Per Day)

The **frequent** scheduler runs multiple times per day within configurable active windows, using a dedicated DynamoDB table and SNS topic:

```bash
task deploy-init                 # Deploy first to create FrequentScheduleCron parameter
task deploy-scheduler-frequent   # Creates frequent table + Lambda + EventBridge Rule
task invoke-auto-retrieval-frequent  # Optional: manual invoke for immediate verification
# Verify: aws dynamodb scan --table-name submissions-auto-retrieval-frequent-dev
task destroy-scheduler-frequent  # Removes frequent table, Lambda, and EventBridge Rule
```

### Phase 5: Deploy and Validate (Command Order)

Run these commands in order. Do **not** skip the InitStack deploy if `FrequentScheduleCron` or `FrequentActiveWindows` SSM parameters do not yet exist.

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `task deploy-init` | Deploy InitStack (if new param names require migration — creates `FrequentScheduleCron`, `FrequentActiveWindows`) |
| 2 | `task deploy-scheduler-frequent` | Deploy frequent scheduler stack (Lambda, EventBridge, SNS, DynamoDB) |
| 3a | `aws cloudformation describe-stacks --stack-name DataCollectionSchedulerFrequent-dev --region eu-central-1` | Verify stack deployed |
| 3b | `aws lambda get-function --function-name $(aws cloudformation describe-stacks --stack-name DataCollectionSchedulerFrequent-dev --query "Stacks[0].Outputs[?OutputKey=='FrequentLambdaFunctionName'].OutputValue" --output text --region eu-central-1) --region eu-central-1` | Verify Lambda |
| 3c | `aws events describe-rule --name heating-auto-retrieval-frequent-dev --region eu-central-1` | Verify EventBridge rule |
| 3d | `aws sns list-topics --region eu-central-1 --query "Topics[?contains(TopicArn, 'heating-auto-retrieval-frequent-failure')]"` | Verify SNS topic exists |
| 3e | `aws dynamodb describe-table --table-name submissions-auto-retrieval-frequent-dev --region eu-central-1` | Verify DynamoDB table |
| 4 | `task invoke-auto-retrieval-frequent` | Manual invoke for end-to-end verification |
| 5 | `aws dynamodb scan --table-name submissions-auto-retrieval-frequent-dev --region eu-central-1` | (Optional) Verify data written after invoke |

## Step 7: Verify

**Manual trigger (optional):**

```bash
aws lambda invoke \
  --function-name DataCollectionScheduler-dev-AutoRetrievalHandler... \
  --region eu-central-1 \
  output.json && cat output.json
```

Check CloudWatch Logs for the Lambda to confirm success or failure.

**After the scheduled run:**

- Check the History tab in the web app for the new auto-retrieved submission
- Or query DynamoDB for recent items with your `user_id`

## Rollback

To disable auto-retrieval without deleting the stack:

1. Disable the EventBridge Rule:
   ```bash
   aws events disable-rule --name heating-auto-retrieval-dev --region eu-central-1
   ```

To fully remove:

```bash
cdk destroy DataCollectionScheduler-dev
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Lambda fails with "AutoRetrieval userId not configured" | Set AppConfig `userId` first. If migration fallback is enabled, also verify `/HeatingDataCollection/AutoRetrieval/UserId` |
| Lambda fails with "VIESSMANN_CREDENTIALS_SECRET_ARN not set" | Ensure `taskfile.env` has `VIESSMANN_CREDENTIALS_SECRET_ARN` and Scheduler stack was deployed with it |
| No data stored | Check CloudWatch Logs; may be skipped as duplicate (same datum_iso) |
| SNS alert received | Check logs for error details; verify Viessmann API connectivity |
| Settings save succeeds but new behavior not visible yet | Deployment may still be in progress; wait for rollout window and verify Lambda logs on next scheduler run |

## Migration Cutover (Disable SSM Runtime Fallback)

After AppConfig-backed runtime behavior is verified in dev:

1. Keep AppConfig document up to date via `PUT /config/auto-retrieval`
2. Redeploy scheduler stacks with `AUTO_RETRIEVAL_ENABLE_SSM_FALLBACK=false`
3. Verify logs show AppConfig reads and no fallback usage
4. Validate daily + frequent scheduler behavior for at least one full schedule cycle
5. In a later cleanup release, remove mutable runtime SSM parameters from `InitStack` ownership
