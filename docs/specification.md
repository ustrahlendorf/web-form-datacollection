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

## 5. API Specification

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

## 6. Validation Rules
- Strict date and time parsing
- Integers >= 0
- Float range validation

## 7. Data Storage (DynamoDB)
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

## 8. Architecture
- S3 + CloudFront for frontend
- API Gateway (HTTP API)
- Lambda (Python)
- DynamoDB
- Cognito User Pool
- Region: eu-central-1

## 9. Security
- HTTPS everywhere
- Least-privilege IAM
- JWT authorizer
- CORS restricted to frontend domain

## 10. Observability
- CloudWatch Logs
- Error and latency monitoring

## 11. Infrastructure as Code
- AWS CDK (Python)
- Separate stacks per environment

## 12. Acceptance Criteria
- Users can self-register and authenticate
- Valid data is stored
- Users can view only their own history
- Infrastructure deployed via CDK
