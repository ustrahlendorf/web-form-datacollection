# Auto-Retrieval Deployment Guide

Step-by-step guide to deploy and configure the automatic Viessmann data retrieval feature.

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

## Step 1: Deploy Init Stack (if not already done)

The Init stack creates SSM parameters including the new AutoRetrieval parameters.

```bash
task deploy-init
```

## Step 2: Configure AutoRetrieval User ID

The auto-retrieval stores data under a single Cognito user. You must set the user's `sub` (subject) identifier.

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

## Step 3: (Optional) Adjust Schedule and Retry Settings

Default values are set by InitStack. To change them, update the SSM parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `/HeatingDataCollection/AutoRetrieval/ScheduleCron` | `0 6 * * ? *` | EventBridge cron (06:00 UTC daily) |
| `/HeatingDataCollection/AutoRetrieval/MaxRetries` | `5` | Max retry attempts on API failure |
| `/HeatingDataCollection/AutoRetrieval/RetryDelaySeconds` | `300` | Seconds between retries |

Example: change schedule to 07:30 UTC:

```bash
aws ssm put-parameter \
  --name "/HeatingDataCollection/AutoRetrieval/ScheduleCron" \
  --value "30 7 * * ? *" \
  --type String \
  --overwrite \
  --region eu-central-1
```

**Note:** Changing `ScheduleCron` in SSM requires redeploying the Scheduler stack for the EventBridge Rule to pick up the new value (the rule is created at deploy time from the SSM value).

## Step 4: Deploy Scheduler Stack

```bash
task deploy-scheduler
```

This creates:
- Lambda function for auto-retrieval
- EventBridge Rule (cron schedule)
- SNS topic for failure alerts

## Step 5: Subscribe to SNS for Failure Alerts

1. Go to AWS SNS → Topics
2. Find `heating-auto-retrieval-failure-dev`
3. Create subscription:
   - Protocol: Email
   - Endpoint: your-email@example.com
4. Confirm the subscription (check your inbox)

## Step 6: Verify

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
| Lambda fails with "UserId not configured" | Set `/HeatingDataCollection/AutoRetrieval/UserId` in SSM |
| Lambda fails with "VIESSMANN_CREDENTIALS_SECRET_ARN not set" | Ensure `taskfile.env` has `VIESSMANN_CREDENTIALS_SECRET_ARN` and Scheduler stack was deployed with it |
| No data stored | Check CloudWatch Logs; may be skipped as duplicate (same datum_iso) |
| SNS alert received | Check logs for error details; verify Viessmann API connectivity |
