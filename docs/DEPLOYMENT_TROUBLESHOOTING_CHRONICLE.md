# Deployment Troubleshooting Chronicle

**Project:** Data Collection Web Application  
**Environment:** dev  
**Date:** December 2024  
**Status:** ✅ Resolved

## Executive Summary

This document chronicles the systematic debugging and resolution of six critical issues encountered during the initial deployment of the data collection web application. The application uses CloudFront, S3, Cognito, API Gateway (HTTP API), Lambda, and DynamoDB.

**Timeline:** Initial deployment → Login page blank → Cognito redirect errors → OAuth disabled → CORS blocking → Authentication failures → DynamoDB type errors → **Full functionality achieved**

---

## Issue Timeline

### Issue 1: Blank Page After Initial Load

**Timestamp:** Initial deployment testing  
**Severity:** Critical (P0) - Application completely inaccessible

#### Symptoms
- CloudFront URL loads briefly (~1 second)
- Web form flashes on screen
- Page immediately covered by blank white page
- Login button not accessible
- No visible error messages in browser

#### Root Cause Analysis

**Investigation Steps:**
1. Opened browser DevTools → Console tab
2. Checked for JavaScript errors (none found)
3. Examined HTML structure in Elements tab
4. Reviewed `app.js` authentication flow
5. Analyzed DOM manipulation logic

**Root Cause:**
HTML structure issue - the login section (`#login-section`) was nested *inside* the main app container (`#app`), but the JavaScript authentication logic hides the entire `#app` div when the user is not authenticated:

```javascript
function showLoginPage() {
    document.getElementById('app').style.display = 'none';  // Hides parent
    document.getElementById('login-section').style.display = 'flex';  // Child cannot be shown
}
```

When `#app` is hidden, all its children (including `#login-section`) are also hidden, creating the blank page.

#### Debugging Process

**Files Examined:**
- `frontend/index.html` - HTML structure
- `frontend/app.js` - DOM manipulation logic
- `frontend/build/index.html` - Deployed artifact

**Key Discovery:**
```html
<div id="app">
    <!-- Navigation and main content -->
    
    <!-- Login Section (PROBLEM: nested inside #app) -->
    <section id="login-section" class="login-container">
        ...
    </section>
</div>
```

#### Solution Implemented

**Fix:** Moved `#login-section` to be a sibling of `#app` instead of a child.

**Changed:**
```html
<!-- BEFORE -->
<body>
    <div id="app">
        ...
        <section id="login-section">...</section>
    </div>
</body>

<!-- AFTER -->
<body>
    <div id="app">
        ...
    </div>
    
    <!-- Login Section (now sibling of #app) -->
    <section id="login-section" style="display: none;">
        ...
    </section>
</body>
```

**Files Modified:**
- `frontend/index.html`
- Rebuilt `frontend/build/index.html` via `build.sh`
- Redeployed via `deploy.sh dev`

**Result:** ✅ Login button now visible and accessible

---

### Issue 2: Cognito Redirect Mismatch

**Timestamp:** After fixing blank page issue  
**Severity:** Critical (P0) - Authentication completely blocked

#### Symptoms
- Login button now visible and clickable
- Clicking "Login with Cognito" redirects to Cognito error page
- Error URL: `https://data-collection-dev.auth.eu-central-1.amazoncognito.com/error?error=redirect_mismatch&client_id=4g4fv2f3edufh3lf0kti0dhgsk`
- Error message: "An error was encountered with the requested page."

#### Root Cause Analysis

**Investigation Steps:**
1. Examined error URL parameter: `error=redirect_mismatch`
2. Captured full OAuth authorize URL from browser network tab:
   ```
   https://data-collection-dev.auth.eu-central-1.amazoncognito.com/oauth2/authorize?
   client_id=4g4fv2f3edufh3lf0kti0dhgsk&
   response_type=code&
   scope=openid+profile+email&
   redirect_uri=https%3A%2F%2Fd3qlp39n4pyhxb.cloudfront.net
   ```
3. Decoded `redirect_uri`: `https://d3qlp39n4pyhxb.cloudfront.net` (no trailing slash)
4. Checked Cognito User Pool App Client settings

**Root Cause:**
The Cognito App Client's "Allowed callback URLs" list did not include the exact CloudFront URL being sent in the OAuth request. Cognito performs **exact string matching** (scheme + host + path + trailing slash must all match).

**Why It Happened:**
- CDK stack only adds CloudFront callback URL if `CLOUDFRONT_DOMAIN` env var exists at deploy time
- Frontend deployment happened after Cognito stack, so URL wasn't registered
- Manual `update-user-pool-client` command only updated callback/logout URLs without OAuth settings

#### Debugging Process

**AWS CLI Commands Used:**
```bash
# Check current callback URLs
aws cognito-idp describe-user-pool-client \
  --user-pool-id eu-central-1_B1NKA94F8 \
  --client-id 4g4fv2f3edufh3lf0kti0dhgsk \
  --region eu-central-1 \
  --query 'UserPoolClient.{CallbackURLs:CallbackURLs,LogoutURLs:LogoutURLs}'
```

**Discovery:**
Callback URLs list was missing the CloudFront URL entirely or had mismatched format (e.g., with/without trailing slash).

#### Solution Implemented

**Immediate Fix (AWS CLI):**
```bash
aws cognito-idp update-user-pool-client \
  --user-pool-id eu-central-1_B1NKA94F8 \
  --client-id 4g4fv2f3edufh3lf0kti0dhgsk \
  --callback-urls \
    "https://d3qlp39n4pyhxb.cloudfront.net" \
    "https://d3qlp39n4pyhxb.cloudfront.net/" \
    "http://localhost:8000" \
  --logout-urls \
    "https://d3qlp39n4pyhxb.cloudfront.net" \
    "https://d3qlp39n4pyhxb.cloudfront.net/" \
    "http://localhost:8000" \
  --region eu-central-1
```

**Permanent Fix (Code):**
Modified `infrastructure/deploy-with-config.sh` to include both URL variants (with/without trailing slash) in the `update-user-pool-client` call to prevent regression on future deployments.

**Files Modified:**
- `infrastructure/deploy-with-config.sh`

**Result:** ✅ `redirect_mismatch` error resolved

---

### Issue 3: OAuth Invalid Request

**Timestamp:** After fixing redirect mismatch  
**Severity:** Critical (P0) - Authentication still blocked

#### Symptoms
- No more `redirect_mismatch` error
- Clicking "Login with Cognito" redirects back immediately with error
- Browser console shows:
  ```
  auth.js:123 Authentication error: invalid_request
  ```
- Cognito returns `?error=invalid_request` in callback URL

#### Root Cause Analysis

**Investigation Steps:**
1. Searched AWS documentation for "Cognito invalid_request error"
2. Checked Cognito App Client OAuth configuration
3. Ran diagnostic AWS CLI command:
   ```bash
   aws cognito-idp describe-user-pool-client \
     --user-pool-id eu-central-1_B1NKA94F8 \
     --client-id 4g4fv2f3edufh3lf0kti0dhgsk \
     --region eu-central-1 \
     --query 'UserPoolClient.{AllowedOAuthFlowsUserPoolClient:AllowedOAuthFlowsUserPoolClient,AllowedOAuthFlows:AllowedOAuthFlows,AllowedOAuthScopes:AllowedOAuthScopes}'
   ```

**Output Revealed:**
```json
{
    "AllowedOAuthFlowsUserPoolClient": false,
    "AllowedOAuthFlows": null,
    "AllowedOAuthScopes": null
}
```

**Root Cause:**
OAuth was completely **disabled** on the App Client. When `deploy-with-config.sh` ran `update-user-pool-client` with only `--callback-urls` and `--logout-urls`, it inadvertently cleared the OAuth configuration fields.

#### Debugging Process

**Common Causes of `invalid_request` (investigated):**
1. ❌ Missing/invalid `redirect_uri` - Already fixed
2. ❌ Missing PKCE when required - Not applicable (PKCE not configured)
3. ✅ **OAuth flows not enabled** - CONFIRMED

**AWS CLI Verification:**
The command showed `AllowedOAuthFlowsUserPoolClient: false`, proving OAuth was disabled.

#### Solution Implemented

**Immediate Fix (AWS CLI):**
```bash
aws cognito-idp update-user-pool-client \
  --user-pool-id eu-central-1_B1NKA94F8 \
  --client-id 4g4fv2f3edufh3lf0kti0dhgsk \
  --allowed-o-auth-flows-user-pool-client \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes openid email profile \
  --callback-urls "https://d3qlp39n4pyhxb.cloudfront.net" "https://d3qlp39n4pyhxb.cloudfront.net/" "http://localhost:8000" \
  --logout-urls "https://d3qlp39n4pyhxb.cloudfront.net" "https://d3qlp39n4pyhxb.cloudfront.net/" "http://localhost:8000" \
  --region eu-central-1
```

**Permanent Fix (Code):**

1. **Updated `infrastructure/deploy-with-config.sh`:**
   Added OAuth flags to the `update-user-pool-client` call so updating callback URLs never disables OAuth again.

2. **Updated `infrastructure/stacks/cognito_stack.py`:**
   Added `profile` scope to the CDK Cognito client configuration to match frontend requirements.

**Files Modified:**
- `infrastructure/deploy-with-config.sh`
- `infrastructure/stacks/cognito_stack.py`

**CDK Dependency Fix:**
During redeployment, encountered Python import errors. Fixed:
- Added `aws-cdk.aws-apigatewayv2-authorizers-alpha==2.100.0a0` to `requirements.txt`
- Fixed import paths in `infrastructure/stacks/api_stack.py` to use alpha packages
- Added `CDK_DEFAULT_ACCOUNT` export to deployment script

**Result:** ✅ OAuth now enabled, Cognito login redirects correctly

---

### Issue 4: CORS Policy Blocking API Requests

**Timestamp:** After successful Cognito authentication  
**Severity:** High (P1) - Application functional but API calls fail

#### Symptoms
- Login successful
- User authenticated via Cognito
- Clicking "Form" tab triggers CORS error
- Browser console shows:
  ```
  Access to fetch at 'https://mowswsomwf.execute-api.eu-central-1.amazonaws.com/recent' 
  from origin 'https://d3qlp39n4pyhxb.cloudfront.net' has been blocked by CORS policy: 
  Response to preflight request doesn't pass access control check: 
  No 'Access-Control-Allow-Origin' header is present on the requested resource.
  ```
- Same error for `/submit` endpoint
- Network tab shows `OPTIONS` preflight requests failing

#### Root Cause Analysis

**Investigation Steps:**
1. Confirmed CORS error is from API Gateway (not Lambda)
2. Examined API Gateway CORS configuration in CDK code
3. Checked `infrastructure/stacks/api_stack.py`:
   ```python
   cors_origins = ["http://localhost:8000"]
   cloudfront_domain = os.environ.get("CLOUDFRONT_DOMAIN")
   if cloudfront_domain:
       cors_origins.append(f"https://{cloudfront_domain}")
   ```
4. Verified `CLOUDFRONT_DOMAIN` env var was not set during CDK deployment

**Root Cause:**
API Gateway CORS configuration only included `localhost:8000`. The CloudFront domain was never added because:
- `CLOUDFRONT_DOMAIN` environment variable wasn't set at CDK synth/deploy time
- API stack was deployed before Frontend stack, so CloudFront URL didn't exist yet
- No mechanism to wire the CloudFront domain from Frontend stack to API stack

#### Debugging Process

**CORS Preflight Requirements:**
Browser sends `OPTIONS` request before actual `GET`/`POST`. API Gateway must respond with:
- `Access-Control-Allow-Origin: https://d3qlp39n4pyhxb.cloudfront.net` (exact match)
- `Access-Control-Allow-Methods: GET, POST, OPTIONS`
- `Access-Control-Allow-Headers: Authorization, Content-Type`

**Verification:**
Checked browser Network tab → `OPTIONS` request → Response Headers → Missing `Access-Control-Allow-Origin`

#### Solution Implemented

**Fix Strategy:**
Wire CloudFront domain directly from `FrontendStack` to `APIStack` as a construct parameter (no environment variable needed).

**Changes Made:**

1. **Updated `infrastructure/stacks/api_stack.py`:**
   ```python
   def __init__(self, scope, id, env_name, user_pool, user_pool_client, 
                cloudfront_domain: str, **kwargs):  # Added parameter
       
       # Build CORS origins
       cors_origins = ["http://localhost:8000"]
       if cloudfront_domain:
           cors_origins.append(f"https://{cloudfront_domain}")
       
       # Configure HTTP API with CORS
       http_api = apigatewayv2_alpha.HttpApi(
           self, "DataCollectionAPI",
           cors_preflight=apigatewayv2_alpha.CorsPreflightOptions(
               allow_origins=cors_origins,
               allow_methods=[apigatewayv2_alpha.CorsHttpMethod.GET,
                            apigatewayv2_alpha.CorsHttpMethod.POST,
                            apigatewayv2_alpha.CorsHttpMethod.OPTIONS],
               allow_headers=["Content-Type", "Authorization"],
               allow_credentials=True,
               max_age=Duration.hours(1),
           ),
       )
   ```

2. **Updated `infrastructure/app.py`:**
   - Reordered stack creation: Frontend before API
   - Passed `frontend_stack.distribution.distribution_domain_name` to API stack
   - Added explicit dependency: `api_stack.add_dependency(frontend_stack)`

3. **Updated `infrastructure/deploy-with-config.sh`:**
   - Changed stack deployment order: Frontend → API → Lambda

**Files Modified:**
- `infrastructure/stacks/api_stack.py`
- `infrastructure/app.py`
- `infrastructure/deploy-with-config.sh`

**Result:** ✅ CORS errors resolved, API requests now succeed from CloudFront origin

---

### Issue 5: 401 Unauthorized on API Requests

**Timestamp:** After fixing CORS  
**Severity:** High (P1) - API accessible but authentication failing

#### Symptoms
- CORS errors gone
- API requests reach API Gateway
- All authenticated endpoints return `401 Unauthorized`
- Browser console shows:
  ```
  auth.js:338 GET https://mowswsomwf.execute-api.eu-central-1.amazonaws.com/recent 401 (Unauthorized)
  ```
- Error appears even with valid JWT token in `Authorization` header

#### Root Cause Analysis

**Investigation Steps:**
1. Verified JWT token exists and is being sent in Authorization header
2. Confirmed API Gateway JWT authorizer is configured
3. Examined Lambda handler code for JWT claims extraction
4. Compared Lambda event structure with handler expectations

**Key Code in Handlers:**
```python
def extract_user_id(event: Dict[str, Any]) -> str:
    claims = event["requestContext"]["authorizer"]["claims"]
    user_id = claims.get("sub")
    # ...
```

**Root Cause:**
Lambda handlers were trying to read JWT claims from `requestContext.authorizer.claims.sub`, but **HTTP API JWT authorizers** provide claims at a different path:

```
REST API (old):    requestContext.authorizer.claims.sub
HTTP API (new):    requestContext.authorizer.jwt.claims.sub
```

The handlers returned 401 because they couldn't find the `sub` claim (user ID) in the expected location.

#### Debugging Process

**Event Structure Investigation:**
1. Reviewed AWS documentation for HTTP API JWT authorizer event format
2. Examined test files to see what event shape tests used
3. Found tests used legacy `authorizer.claims` shape
4. Confirmed production uses HTTP API → different event structure

**Test Event Example (from tests):**
```python
event = {
    "requestContext": {
        "authorizer": {
            "claims": {"sub": "user-123"}  # Legacy/test format
        }
    }
}
```

**Production Event (HTTP API):**
```python
event = {
    "requestContext": {
        "authorizer": {
            "jwt": {
                "claims": {"sub": "user-123"}  # Actual production format
            }
        }
    }
}
```

#### Solution Implemented

**Fix:** Updated `extract_user_id()` function in all handlers to support both event structures (production HTTP API and test legacy format).

**New Code:**
```python
def extract_user_id(event: Dict[str, Any]) -> str:
    """Extract user_id from JWT claims (supports both HTTP API and legacy formats)."""
    try:
        authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
        
        claims = None
        # Try HTTP API JWT authorizer shape first
        jwt_block = authorizer.get("jwt")
        if isinstance(jwt_block, dict):
            claims = jwt_block.get("claims")
        
        # Fall back to legacy/test shape
        if not isinstance(claims, dict):
            claims = authorizer.get("claims")
        
        if not isinstance(claims, dict):
            claims = {}
        
        user_id = claims.get("sub")
        if not user_id:
            raise KeyError("sub claim missing")
        
        return user_id
    except Exception as e:
        raise KeyError(f"Could not extract user_id from JWT claims: {e}")
```

**Files Modified:**
- `src/handlers/recent_handler.py`
- `src/handlers/submit_handler.py`
- `src/handlers/history_handler.py`

**Result:** ✅ Authentication now works, handlers can extract user ID from JWT

---

### Issue 6: DynamoDB Write Failure (500 Internal Server Error)

**Timestamp:** After fixing authentication  
**Severity:** Critical (P0) - Form submission completely broken

#### Symptoms
- Form loads successfully
- User can fill in all fields
- Clicking "Submit" returns `500 Internal Server Error`
- Browser console shows:
  ```
  POST https://mowswsomwf.execute-api.eu-central-1.amazonaws.com/submit 500 (Internal Server Error)
  ```
- Network tab Response: `{"error":"Failed to store submission"}`

#### Root Cause Analysis

**Investigation Steps:**
1. Checked DevTools Network tab → Response body: generic error
2. Examined CloudWatch Logs for `data-collection-submit-dev`:
   ```bash
   aws logs tail "/aws/lambda/data-collection-submit-dev" \
     --since 30m --region eu-central-1
   ```
3. Found critical error message:
   ```
   DynamoDB write error: Float types are not supported. Use Decimal types instead.
   ```

**Root Cause:**
**boto3 DynamoDB does NOT support Python `float` values.** It requires `decimal.Decimal` for all numeric types.

**Why It Happened:**
1. Frontend sends form data as JSON: `{"verbrauch_qm": 10.5, ...}`
2. Lambda handler parses JSON: `json.loads(event["body"])`
3. Python's `json.loads()` converts JSON numbers to `float` by default
4. Handler stores float value directly in DynamoDB
5. `boto3` rejects the write with "Float types are not supported"

#### Debugging Process

**Data Flow Analysis:**
```
Browser (JSON: 10.5) 
  → API Gateway 
  → Lambda (Python float: 10.5) 
  → boto3 DynamoDB (REJECTS float)
```

**Testing:**
```python
# This FAILS in boto3 DynamoDB
table.put_item(Item={"verbrauch_qm": 10.5})  # float - ERROR

# This WORKS in boto3 DynamoDB  
from decimal import Decimal
table.put_item(Item={"verbrauch_qm": Decimal("10.5")})  # Decimal - OK
```

**Complication:**
DynamoDB stores `Decimal`, but `json.dumps()` cannot serialize `Decimal` back to JSON:
```python
json.dumps({"verbrauch_qm": Decimal("10.5")})  # TypeError!
```

This means `/recent` and `/history` would fail once a Decimal was stored.

#### Solution Implemented

**Three-Part Fix:**

**1. Parse JSON floats as Decimal on input (submit_handler.py):**
```python
from decimal import Decimal

# Parse JSON numbers as Decimal for DynamoDB compatibility
if isinstance(event.get("body"), str):
    body = json.loads(event["body"], parse_float=Decimal)
else:
    body = event.get("body", {})

# verbrauch_qm is now Decimal, not float
submission = create_submission(
    user_id=user_id,
    verbrauch_qm=body["verbrauch_qm"],  # Decimal
    # ...
)
```

**2. Add JSON serialization helper for Decimal (all handlers):**
```python
from decimal import Decimal

def _json_default(obj):
    """JSON serializer for DynamoDB Decimal types."""
    if isinstance(obj, Decimal):
        return float(obj)  # Convert Decimal → float for JSON
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

# Use in json.dumps()
return {
    "statusCode": 200,
    "body": json.dumps({"submissions": submissions}, default=_json_default),
}
```

**3. Update model type hints (models.py):**
```python
from decimal import Decimal

@dataclass
class Submission:
    verbrauch_qm: Decimal  # Changed from float
```

**4. Update tests to use Decimal:**
```python
from decimal import Decimal

# Update assertions
assert stored_item["verbrauch_qm"] == Decimal(str(verbrauch_qm))
assert submission.verbrauch_qm == Decimal(str(verbrauch_qm))
```

**Files Modified:**
- `src/handlers/submit_handler.py`
- `src/handlers/recent_handler.py`
- `src/handlers/history_handler.py`
- `src/models.py`
- `tests/test_submit_handler.py`
- `tests/test_models.py`

**Result:** ✅ Form submission works, Decimal values stored and retrieved correctly

---

## Deployment Checklist (Final Working Process)

### Prerequisites
```bash
cd /Users/uwes/EigeneDateien/Projekte/AWS-kiro/web-form-verbrauch
source ../.venv/bin/activate
pip install -r requirements.txt
```

### 1. Deploy Infrastructure (CDK)
```bash
cd infrastructure
bash ./deploy-with-config.sh dev
```

**Order:** Frontend → API → Lambda (now correct with dependencies)

### 2. Deploy Frontend
```bash
cd ../frontend
bash setup-env.sh dev
bash build.sh
bash deploy.sh dev
```

### 3. Verify Cognito Configuration
```bash
aws cognito-idp describe-user-pool-client \
  --user-pool-id eu-central-1_B1NKA94F8 \
  --client-id 4g4fv2f3edufh3lf0kti0dhgsk \
  --region eu-central-1
```

**Verify:**
- `AllowedOAuthFlowsUserPoolClient: true`
- `AllowedOAuthFlows: ["code"]`
- `AllowedOAuthScopes: ["openid", "email", "profile"]`
- `CallbackURLs` includes CloudFront domain

### 4. Test Application
1. Open CloudFront URL
2. Login via Cognito
3. Submit form with decimal values
4. Check Recent/History tabs
5. Monitor CloudWatch Logs

---

## Key Lessons Learned

### 1. HTML Structure Matters for Dynamic UIs
- Parent `display: none` hides all children
- Authentication UI must be sibling of main app container
- Test visibility toggling during development

### 2. Cognito Callback URLs Require Exact Matching
- Include both with/without trailing slash variants
- Update URLs before enabling OAuth flows
- Use AWS CLI for immediate fixes, update CDK for permanence

### 3. OAuth Must Be Explicitly Enabled
- `update-user-pool-client` can clear OAuth settings if not specified
- Always include OAuth flags when updating Cognito clients
- Verify with `describe-user-pool-client` after changes

### 4. CORS Must Match Actual Origin
- CloudFront domain must be in API Gateway CORS allow list
- Wire domains between stacks using construct parameters
- Deploy frontend before API to ensure domain exists

### 5. HTTP API JWT Authorizers Use Different Event Structure
- REST API: `requestContext.authorizer.claims`
- HTTP API: `requestContext.authorizer.jwt.claims`
- Write handlers to support both for test compatibility

### 6. DynamoDB Requires Decimal, Not Float
- Always use `json.loads(..., parse_float=Decimal)` for numeric input
- Add custom JSON encoder for Decimal output
- Update all read/write handlers consistently
- Fix tests to assert Decimal types

---

## Monitoring and Verification Commands

### Check CloudWatch Logs
```bash
# Submit handler
aws logs tail "/aws/lambda/data-collection-submit-dev" --since 30m --follow --region eu-central-1

# Recent handler  
aws logs tail "/aws/lambda/data-collection-recent-dev" --since 30m --follow --region eu-central-1

# History handler
aws logs tail "/aws/lambda/data-collection-history-dev" --since 30m --follow --region eu-central-1
```

### Verify DynamoDB Data
```bash
aws dynamodb scan \
  --table-name data-collection-submissions-dev \
  --region eu-central-1 \
  --max-items 5
```

### Check API Gateway Configuration
```bash
aws apigatewayv2 get-apis --region eu-central-1
aws apigatewayv2 get-api --api-id <api-id> --region eu-central-1
```

### Verify Cognito Settings
```bash
aws cognito-idp describe-user-pool-client \
  --user-pool-id eu-central-1_B1NKA94F8 \
  --client-id 4g4fv2f3edufh3lf0kti0dhgsk \
  --region eu-central-1
```

---

## Architecture Diagram (Final Working State)

```
┌─────────────┐
│   Browser   │
└──────┬──────┘
       │
       ├─────────────────┐
       │                 │
       ▼                 ▼
┌────────────┐    ┌──────────────┐
│ CloudFront │    │   Cognito    │
│  (Static)  │    │ (Hosted UI)  │
└─────┬──────┘    └──────┬───────┘
      │                  │
      │                  │ JWT Token
      ▼                  │
   ┌─────┐               │
   │ S3  │               │
   └─────┘               │
                         │
      ┌──────────────────┘
      │
      ▼
┌──────────────────┐
│  API Gateway     │
│  (HTTP API)      │
│  - CORS enabled  │
│  - JWT Authorizer│
└────────┬─────────┘
         │
         ├──────┬──────┬──────┐
         ▼      ▼      ▼      ▼
      ┌─────┬─────┬─────┬─────┐
      │Submit Recent History ...│
      │Lambda Lambda Lambda   │
      └──┬───┴──┬───┴──┬──────┘
         │      │      │
         └──────┴──────┘
                │
                ▼
         ┌──────────────┐
         │  DynamoDB    │
         │  (Decimal)   │
         └──────────────┘
```

---

## Final Status

✅ **All Issues Resolved**

- [x] Login page displays correctly
- [x] Cognito authentication works
- [x] OAuth flows enabled
- [x] CORS configured for CloudFront origin
- [x] JWT claims extracted correctly
- [x] DynamoDB writes succeed with Decimal values
- [x] Form submission functional
- [x] Recent submissions display
- [x] History pagination works

**Application Status:** Fully operational in dev environment

---

## Document Version

**Version:** 1.0  
**Last Updated:** December 2024  
**Maintained By:** Development Team

