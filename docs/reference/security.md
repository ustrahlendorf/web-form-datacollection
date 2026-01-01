# security

This document is the **evergreen** security overview (not a point-in-time audit report).

## security controls (high-level)

- **transport security**: HTTPS enforced (CloudFront, API Gateway, S3 SSL enforcement)
- **authentication/authorization**: Cognito + JWT authorizer on all API routes
- **cors**: restricted allowlist (localhost for dev + CloudFront origin)
- **data isolation**: DynamoDB access is scoped by `user_id` (partition key and query patterns)
- **encryption at rest**: DynamoDB AWS-managed encryption; S3 encryption; versioning where applicable
- **least privilege**: Lambda IAM role scoped to required DynamoDB actions and table ARN

## where this is enforced / tested

- CDK stacks under `infrastructure/stacks/`
- tests under `tests/` (security validation + integration coverage)

## legacy

Point-in-time validation reports belong in `docs/legacy/` to avoid drift in live docs.


