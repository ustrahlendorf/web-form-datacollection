# Complete Deployment Workflow

This document provides a complete step-by-step workflow for deploying the Data Collection Web Application to AWS.

## Prerequisites

1. AWS Account with appropriate permissions
2. AWS CLI configured with credentials
3. AWS CDK installed (`npm install -g aws-cdk`)
4. Node.js and npm installed
5. Bash/Zsh shell
6. Git (for version control)

## Phase 1: Infrastructure Deployment

### Step 1.1: Deploy CDK Infrastructure

```bash
cd infrastructure/

# Install dependencies
pip install -r requirements.txt

# Synthesize CDK stacks
cdk synth

# Deploy dev stacks (dev-only)
cdk deploy \
  DataCollectionCognito-dev \
  DataCollectionDynamoDB-dev \
  DataCollectionFrontend-dev \
  DataCollectionAPI-dev \
  --require-approval never
```

This creates:
- Cognito User Pool for authentication
- DynamoDB table for data storage
- API Gateway with Lambda functions
- S3 bucket for frontend hosting
- CloudFront distribution for CDN

### Step 1.2: Verify Infrastructure Deployment

```bash
# Check CloudFormation stacks
aws cloudformation list-stacks --region eu-central-1

# Get stack outputs
aws cloudformation describe-stacks \
    --stack-name DataCollectionAPI-dev \
    --region eu-central-1 \
    --query "Stacks[0].Outputs" \
    --output table
```

## Phase 2: Backend Deployment

### Step 2.1: Deploy Lambda Functions

Lambda functions are automatically deployed by CDK. Verify they're working:

If you change backend behavior (e.g., new stored attributes), redeploy the API stack:

```bash
cd infrastructure/
cdk deploy DataCollectionAPI-dev --require-approval never
```

```bash
# Test submit endpoint
curl -X POST https://your-api-id.execute-api.eu-central-1.amazonaws.com/submit \
    -H "Authorization: Bearer YOUR_JWT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "datum": "15.12.2025",
        "uhrzeit": "09:30",
        "betriebsstunden": 1234,
        "starts": 12,
        "verbrauch_qm": 19.5
    }'
```

### Step 2.2: Verify DynamoDB

```bash
# List tables
aws dynamodb list-tables --region eu-central-1

# Describe submissions table
aws dynamodb describe-table \
    --table-name submissions-dev \
    --region eu-central-1
```

## Phase 3: Frontend Deployment

### Step 3.1: Setup Environment Variables

```bash
cd frontend/

# Auto-generate .env from CDK outputs
bash setup-env.sh dev

# Verify .env file
cat .env
```

Expected output:
```
REACT_APP_API_ENDPOINT=https://abc123.execute-api.eu-central-1.amazonaws.com
REACT_APP_COGNITO_DOMAIN=https://data-collection.auth.eu-central-1.amazoncognito.com
REACT_APP_COGNITO_CLIENT_ID=1a2b3c4d5e6f7g8h9i0j
REACT_APP_COGNITO_REDIRECT_URI=https://d123456.cloudfront.net
```

### Step 3.2: Build Frontend

```bash
# Build the frontend
bash build.sh

# Verify build output
ls -la build/
```

Expected files:
- index.html
- styles.css
- app.js
- auth.js
- config.js

### Step 3.3: Deploy to S3 and CloudFront

```bash
# Deploy to S3 and invalidate CloudFront
bash deploy.sh dev

# Output will show:
# - S3 bucket name
# - CloudFront distribution ID
# - CloudFront domain name
# - Invalidation ID
```

### Step 3.4: Verify Frontend Deployment

```bash
# Get CloudFront domain from deployment output
# Open in browser: https://your-cloudfront-domain.cloudfront.net

# Or check S3 bucket contents
aws s3 ls s3://data-collection-frontend-dev/

# Check CloudFront distribution
aws cloudfront get-distribution \
    --id YOUR_DISTRIBUTION_ID \
    --region eu-central-1
```

## Phase 4: End-to-End Testing

### Step 4.1: Test Authentication

1. Open the CloudFront URL in your browser
2. Click "Login with Cognito"
3. Sign up or log in with Cognito credentials
4. Verify you're redirected back to the application

### Step 4.2: Test Form Submission

1. Navigate to the Form page
2. Verify date and time are pre-populated
3. Fill in the form fields
4. Click Submit
5. Verify success message appears
6. Check that recent submissions are updated (including delta values after the second submission)

### Step 4.3: Test History Page

1. Navigate to History page
2. Verify submissions are displayed
3. Test pagination (if more than 20 submissions)
4. Verify sorting (newest first)
5. Verify delta columns are shown and values match (current - previous)

### Step 4.4: Test Data Isolation

1. Create a second Cognito user
2. Log in as the second user
3. Verify you can only see your own submissions
4. Verify you cannot see submissions from the first user

### Step 4.5: Test Analyze Page (YTD Statistics)

The **Analyze** page is a **frontend-only** feature that uses the existing `/history` API to compute totals (latest − earliest) and inclusive calendar days.

1. Navigate to **Analyze**.
2. Verify the header **“Statistics Year to Date”** is shown.
3. Verify the Totals card renders values for:
   - Operating hours
   - Starts
   - Consumption
   - Days
4. Verify behavior with different data volumes:
   - With **0–1 submissions**: Analyze shows an empty state (no totals).
   - With **2+ submissions**: totals are computed from earliest vs latest.

## Phase 6: Monitoring and Maintenance

### Step 6.1: Monitor CloudWatch Logs

```bash
# View Lambda function logs
aws logs tail /aws/lambda/DataCollectionSubmitHandler-dev --follow

# View API Gateway logs
aws logs tail /aws/apigateway/DataCollectionAPI-dev --follow
```

### Step 6.2: Monitor CloudFront

```bash
# Get CloudFront statistics
aws cloudfront get-distribution-statistics \
    --id YOUR_DISTRIBUTION_ID \
    --region eu-central-1
```

### Step 6.3: Monitor DynamoDB

```bash
# Get DynamoDB metrics
aws cloudwatch get-metric-statistics \
    --namespace AWS/DynamoDB \
    --metric-name ConsumedWriteCapacityUnits \
    --dimensions Name=TableName,Value=submissions-dev \
    --start-time 2025-12-15T00:00:00Z \
    --end-time 2025-12-16T00:00:00Z \
    --period 3600 \
    --statistics Sum
```

## Phase 7: Troubleshooting

### Issue: "Could not retrieve S3 bucket or CloudFront distribution ID"

**Solution**: Verify CDK infrastructure is deployed
```bash
aws cloudformation list-stacks --region eu-central-1 | grep DataCollection
```

### Issue: "Invalid client id" error during login

**Solution**: Verify Cognito client ID in .env
```bash
aws cognito-idp list-user-pool-clients \
    --user-pool-id YOUR_USER_POOL_ID \
    --region eu-central-1
```

### Issue: "Failed to load recent submissions"

**Solution**: Check API endpoint and verify Lambda functions
```bash
# Test API endpoint
curl https://your-api-id.execute-api.eu-central-1.amazonaws.com/recent \
    -H "Authorization: Bearer YOUR_JWT_TOKEN"

# Check Lambda logs
aws logs tail /aws/lambda/DataCollectionRecentHandler-dev --follow
```

### Issue: CloudFront shows old content

**Solution**: Verify invalidation completed
```bash
aws cloudfront list-invalidations \
    --distribution-id YOUR_DISTRIBUTION_ID \
    --region eu-central-1
```

## Rollback Procedures

### Rollback Frontend

```bash
# Restore previous version from S3
aws s3api list-object-versions \
    --bucket data-collection-frontend-dev \
    --region eu-central-1

# Restore specific version
aws s3api get-object \
    --bucket data-collection-frontend-dev \
    --key index.html \
    --version-id VERSION_ID \
    index.html

# Upload restored version
aws s3 cp index.html s3://data-collection-frontend-dev/

# Invalidate CloudFront
aws cloudfront create-invalidation \
    --distribution-id YOUR_DISTRIBUTION_ID \
    --paths "/*" \
    --region eu-central-1
```

### Rollback Infrastructure

```bash
# Delete CDK stacks
cdk destroy \
  DataCollectionFrontend-dev \
  DataCollectionAPI-dev \
  DataCollectionCognito-dev \
  DataCollectionDynamoDB-dev
```

## Deployment Checklist

- [ ] AWS credentials configured
- [ ] AWS CDK installed
- [ ] Infrastructure deployed (dev-only)
- [ ] Cognito User Pool created
- [ ] DynamoDB table created
- [ ] API Gateway deployed
- [ ] Lambda functions deployed
- [ ] S3 bucket created
- [ ] CloudFront distribution created
- [ ] Environment variables setup (`bash setup-env.sh dev`)
- [ ] Frontend built (`bash build.sh`)
- [ ] Frontend deployed (`bash deploy.sh dev`)
- [ ] Authentication tested
- [ ] Form submission tested
- [ ] History page tested
- [ ] Analyze page tested (YTD statistics)
- [ ] Data isolation verified
- [ ] CloudWatch logs monitored
- [ ] Production deployment completed (if applicable)

## Quick Reference Commands

```bash
# Setup and deploy (dev)
cd infrastructure && bash deploy-with-config.sh dev
cd ../frontend
bash setup-env.sh dev
bash build.sh
bash deploy.sh dev

# View logs
aws logs tail /aws/lambda/DataCollectionSubmitHandler-dev --follow

# Check deployment status
aws cloudformation describe-stacks --region eu-central-1

# Get CloudFront URL
aws cloudformation describe-stacks \
    --stack-name DataCollectionFrontend-dev \
    --region eu-central-1 \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomainName'].OutputValue" \
    --output text
```

## Support

For detailed information:
- Infrastructure: See `infrastructure/README.md`
- Frontend: See `frontend/README.md`
- Deployment: See `frontend/DEPLOYMENT.md`
- Backend: See `src/handlers/` documentation

## Next Steps

After successful deployment:
1. Set up CI/CD pipeline for automated deployments
2. Configure custom domain (optional)
3. Set up WAF rules for additional security
4. Configure backup and disaster recovery
5. Set up monitoring and alerting
6. Plan for scaling and performance optimization
