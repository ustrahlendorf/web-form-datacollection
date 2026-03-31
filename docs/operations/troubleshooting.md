# troubleshooting

This is the **evergreen** troubleshooting entry point (not a historical incident log).

## start here (fast checks)

- **frontend config**: open DevTools → Console and confirm `window.APP_CONFIG` exists
- **network**: DevTools → Network and confirm `index.html`, `config.js`, `auth.js`, `app.js`, `styles.css` return 200
- **auth**: confirm Cognito redirect URL exactly matches the CloudFront URL (with/without trailing slash as configured)
- **api**: confirm requests to `/recent` and `/history` return 401 when unauthenticated and 200 when authenticated

## common symptoms → likely causes

### blank page / nothing renders

Likely:
- scripts not loading/executing
- runtime JS error
- config missing / not loaded

First actions:
- hard refresh (bypass cache)
- re-run `bash deploy.sh dev` to ensure CloudFront invalidation ran
- check DevTools console for the first red error

### login fails (redirect mismatch / invalid_request)

Likely:
- Cognito callback URLs missing exact CloudFront URL variant
- OAuth flags were cleared by an update-user-pool-client call that didn’t specify OAuth settings

### api calls fail with CORS errors

Likely:
- API Gateway CORS allowlist missing the CloudFront origin
- stack deploy order didn’t wire the CloudFront domain into the API CORS config

### Settings shows “Not available” for scheduler lines

Likely:
- API Lambda missing IAM for `events:DescribeRule` and/or `scheduler:GetSchedule`, or daily schedule name env not set on the config function
- Scheduler stack not deployed (`VIESSMANN_CREDENTIALS_SECRET_ARN` gating); config and AppConfig can still work while metadata stays unavailable

First actions:
- confirm `task deploy-api-with-deps` / scheduler stacks per `runbooks/auto-retrieval-deployment.md`
- check CloudWatch logs for the auto-retrieval config Lambda when loading Settings

### submit fails (500) after sending numbers

Likely:
- DynamoDB float vs Decimal mismatch if backend parsing/serialization is inconsistent

## historical deep dives (legacy)

If you need the original incident write-ups, see:
- `legacy/2025-12-16/` (deployment + blank-page investigations)


