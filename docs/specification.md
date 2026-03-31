# Web Form Application — Specification  
**Release 1 (AWS Serverless, Python, eu-central-1)**

## 1. Purpose and Scope
The application provides a secure, serverless web interface that allows authenticated users to:
1. Enter operational data via a web form  
2. Persist each submission in Amazon DynamoDB  
3. View a history of their submitted records  

Out of scope for Release 1:
- CSV export or download
- Data modification or deletion
- Administrative dashboards

## 2. Authentication
- Amazon Cognito User Pool with Hosted UI
- Self-signup enabled (any user may register)
- Authentication required for all application pages and API endpoints

## 3. Data Capture (Form Page)

### 3.1 Input Fields
| Label | Internal Name | Type | Required | Validation |
|---|---|---|---|---|
| Datum | datum | string | Yes | dd.mm.yyyy, valid date |
| Uhrzeit | uhrzeit | string | Yes | hh:mm (24h) |
| Betriebsstunden | betriebsstunden | integer | Yes | >= 0 |
| Starts | starts | integer | Yes | >= 0 |
| Verbrauch in qm | verbrauch_qm | number (stored as Decimal) | Yes | 0 < value < 20.0 |

Normalization:
- Decimal comma or dot accepted in UI, stored as dot.
- Whitespace trimmed.

### 3.2 System Fields
- submission_id (UUID v4)
- timestamp_utc (ISO-8601 UTC)
- user_id (Cognito sub)

### 3.3 Derived Fields (Delta vs Previous Submission)
After each submission, the backend computes deltas relative to the **previous submission of the same user** (ordered by `timestamp_utc` descending):

- `delta_betriebsstunden` = current `betriebsstunden` − previous `betriebsstunden` (int; can be negative)
- `delta_starts` = current `starts` − previous `starts` (int; can be negative)
- `delta_verbrauch_qm` = current `verbrauch_qm` − previous `verbrauch_qm` (Decimal; can be negative)

For a user’s **first** submission, all delta values are stored as **0**.

UI display:
- On the **form page**, the “Recent Submissions” list shows each value together with its delta (e.g. `123 (+5)`).

## 4. View History Page
- Shows submissions of the authenticated user only
- Sorted by timestamp_utc descending
- Read-only
- Paginated (default 20 items)
- Displays delta columns for operating hours, starts, and consumption
- Column headers indicate timezone where relevant (see frontend History view)

## 5. Additional authenticated UI (single-page app)

### 5.1 Analyze
- **Data source:** same records as history, fetched via `GET /history` (and related pagination); all aggregation runs in the browser.
- **Totals card:** year-to-date (or available range) sums for consumption (m³), operating hours, starts, day count; optional weekly mean supply and outside temperature for the peak-consumption week and the minimum-consumption week.
- **Peak week (consumption):** ISO week with highest summed `delta_verbrauch_qm` for the selected year; shows consumption, operating hours, starts, supply and outside temperature aggregates for that week. If multiple weeks tie for peak consumption, the lexicographically earlier ISO week label is shown with a tie notice.
- **Minimum week (consumption):** same structure for the week with lowest summed consumption; the **current** ISO week is excluded from the minimum statistic so partial weeks do not skew the result.
- **Live heating block:** when live data is available, shows gas consumption (today / yesterday), operating hours, starts, supply and outside temperatures (labels in English in this view).

### 5.2 Live heating
- Dedicated tab calling `GET /heating/live` when Viessmann integration is enabled (see `GET /heating/live` below).

### 5.3 Settings (auto-retrieval)
- Loads effective AppConfig via `GET /config/auto-retrieval` and optional `GET /config/auto-retrieval/deployment-status` for rollout progress.
- Edits validate in the browser (UUID for `userId`, window count, time ordering) before `PUT /config/auto-retrieval`.
- Surfaces read-only **scheduler metadata** returned on `GET` (frequent EventBridge rule expression / interval when describable; daily EventBridge Scheduler cron, timezone, schedule name, state when `GetSchedule` is configured).

## 6. API Specification

### POST /submit
Creates a submission.

Request:
```json
{
  "datum": "15.12.2025",
  "uhrzeit": "09:30",
  "betriebsstunden": 1234,
  "starts": 12,
  "verbrauch_qm": 19.5
}
```

Response 200:
```json
{
  "submission_id": "uuid",
  "timestamp_utc": "2025-12-15T08:30:00Z"
}
```

### GET /recent
Returns recent submissions for the current user (used on the form page).

Query params:
- limit (optional)
- next_token (optional)

### GET /history
Returns submissions for current user (paginated history view).

Query params:
- limit
- next_token

### GET /heating/live (optional)
Returns live heating data from the Viessmann IoT API. Requires Viessmann credentials in Secrets Manager. See `backend/vis-connect.md`.

### GET /config/auto-retrieval
Returns the current effective AppConfig document for auto-retrieval runtime behavior, plus read-only scheduler metadata for the Settings UI.

Response 200:
```json
{
  "config": {
    "schemaVersion": 1,
    "frequentActiveWindows": [{"start": "08:00", "stop": "18:00"}],
    "maxRetries": 3,
    "retryDelaySeconds": 300,
    "userId": "123e4567-e89b-12d3-a456-426614174000"
  },
  "versionLabel": "7",
  "scheduler": {
    "frequentRuleName": "heating-auto-retrieval-frequent-dev",
    "frequentScheduleExpression": "cron(0/15 * * * ? *)",
    "frequentScheduleCron": "0/15 * * * ? *",
    "frequentIntervalMinutes": 15,
    "source": "eventbridge",
    "available": true,
    "dailyScheduleName": "heating-auto-retrieval-dev",
    "dailyScheduleGroupName": "default",
    "dailyScheduleExpression": "cron(0 7 * * ? *)",
    "dailyScheduleCron": "0 7 * * ? *",
    "dailyScheduleTimezone": "Europe/Berlin",
    "dailyState": "ENABLED",
    "dailyAvailable": true,
    "dailySource": "scheduler"
  }
}
```

Scheduler fields are best-effort: if AWS APIs are unavailable or env wiring is missing, boolean `available` / `dailyAvailable` may be false and string fields may be null. Frequent metadata comes from EventBridge `DescribeRule`; daily metadata from EventBridge Scheduler `GetSchedule` when `AUTO_RETRIEVAL_DAILY_SCHEDULE_NAME` is set on the config Lambda.

### GET /config/auto-retrieval/deployment-status
Returns the latest AppConfig deployment for the auto-retrieval environment, or a specific deployment when queried.

Query params:
- `deploymentNumber` (optional): when set, fetches that deployment; otherwise returns the most recent deployment from `ListDeployments` (max one item).

Response 200:
```json
{
  "deployment": {
    "deploymentNumber": 7,
    "state": "DEPLOYING",
    "configurationVersion": "11",
    "configurationName": null,
    "startedAt": "2025-12-15T10:00:00+00:00",
    "completedAt": null,
    "percentageComplete": 35.0
  }
}
```

`deployment` may be `null` if no deployment exists. Field names mirror AppConfig API attributes normalized for JSON.

### PUT /config/auto-retrieval
Validates and publishes a new hosted AppConfig version, then starts an AppConfig deployment for that version.

Request:
```json
{
  "schemaVersion": 1,
  "frequentActiveWindows": [{"start": "08:00", "stop": "18:00"}],
  "maxRetries": 3,
  "retryDelaySeconds": 300,
  "userId": "123e4567-e89b-12d3-a456-426614174000"
}
```

Response 200:
```json
{
  "versionNumber": 11,
  "deploymentNumber": 3,
  "state": "DEPLOYING"
}
```

Operational semantics:
- The deployment is triggered as part of the same `PUT` call after successful validation.
- A successful `PUT` means deployment started, not necessarily completed.
- The Settings tab surfaces deployment metadata (`versionNumber`, `deploymentNumber`, `state`) to confirm trigger details.

## 7. Validation Rules
- Strict date and time parsing
- Integers >= 0
- Float range validation
- Auto-retrieval config:
  - `schemaVersion` must be `1`
  - `maxRetries` must be integer `0..20`
  - `retryDelaySeconds` must be integer `1..3600`
  - `frequentActiveWindows` must contain `1..5` windows with `HH:MM` and `start < stop`
  - `userId` must be a non-empty string (frontend enforces UUID format)

## 8. Data Storage (DynamoDB)
Table: submissions-<env>

Primary key:
- Partition: user_id
- Sort: timestamp_utc

Attributes:
- submission_id
- datum
- datum_iso (YYYY-MM-DD, derived from datum; used for filtering/analytics)
- uhrzeit
- betriebsstunden
- starts
- verbrauch_qm
- delta_betriebsstunden
- delta_starts
- delta_verbrauch_qm

## 9. Architecture
- S3 + CloudFront for frontend
- API Gateway (HTTP API)
- Lambda (Python)
- DynamoDB
- Cognito User Pool
- Region: eu-central-1

## 10. Security
- HTTPS everywhere
- Least-privilege IAM
- JWT authorizer
- CORS restricted to frontend domain

For detailed security controls and where they are enforced, see `reference/security.md`.

## 11. Observability
- CloudWatch Logs
- Error and latency monitoring

## 12. Infrastructure as Code
- AWS CDK (Python)
- Separate stacks per environment

## 13. Acceptance Criteria
- Users can self-register and authenticate
- Valid data is stored
- Users can view only their own history
- Authenticated users can open Analyze (statistics derived from their history) and Settings (auto-retrieval config when deployed)
- Infrastructure deployed via CDK
