# Frontend Deployment Guide

This guide explains how to build and deploy the frontend application to AWS S3 and CloudFront.

## Prerequisites

1. AWS CLI configured with appropriate credentials
2. AWS CDK infrastructure deployed (see infrastructure README)
3. Node.js and npm installed (for running tests, optional)
4. Bash shell (for running deployment scripts)

## Deployment Steps

### Step 1: Configure Environment Variables

Create a `.env` file in the `frontend/` directory with your AWS resources:

```bash
cp .env.example .env
```

Edit `.env` and fill in the values from your CDK deployment outputs:

```bash
# Get outputs from CDK deployment
aws cloudformation describe-stacks \
    --stack-name DataCollectionWebAppFrontend-dev \
    --region eu-central-1 \
    --query "Stacks[0].Outputs" \
    --output table
```

Update `.env` with:
- `REACT_APP_API_ENDPOINT`: Your API Gateway endpoint URL
- `REACT_APP_COGNITO_DOMAIN`: Your Cognito domain
- `REACT_APP_COGNITO_CLIENT_ID`: Your Cognito client ID
- `REACT_APP_COGNITO_REDIRECT_URI`: Your CloudFront domain

Example:
```
REACT_APP_API_ENDPOINT=https://abc123.execute-api.eu-central-1.amazonaws.com
REACT_APP_COGNITO_DOMAIN=https://data-collection.auth.eu-central-1.amazoncognito.com
REACT_APP_COGNITO_CLIENT_ID=1a2b3c4d5e6f7g8h9i0j
REACT_APP_COGNITO_REDIRECT_URI=https://d123456.cloudfront.net
```

### Step 2: Build the Frontend

```bash
cd frontend/
bash build.sh
```

This will:
- Create a `build/` directory
- Copy all frontend files (HTML, CSS, JavaScript)
- Generate a `config.js` file with your environment variables
- Display the configuration being used

### Step 3: Deploy to S3 and CloudFront

```bash
bash deploy.sh dev
```

Or for production:
```bash
bash deploy.sh prod
```

The deployment script will:
1. Build the frontend (if not already built)
2. Retrieve S3 bucket and CloudFront distribution details from CDK outputs
3. Upload files to S3 with appropriate cache headers
4. Invalidate the CloudFront cache
5. Display the CloudFront URL where your application is now accessible

### Step 4: Verify Deployment

After deployment completes, verify that your application is accessible:

```bash
# Get the CloudFront domain from the deployment output
# Then open it in your browser
https://your-cloudfront-domain.cloudfront.net
```

You should see:
- The login page if not authenticated
- The form page after logging in with Cognito

## Troubleshooting

### Issue: "Could not retrieve S3 bucket or CloudFront distribution ID"

**Solution**: Ensure the CDK infrastructure has been deployed:
```bash
cd infrastructure/
cdk deploy --all
```

### Issue: "Access Denied" when uploading to S3

**Solution**: Verify your AWS credentials have the necessary permissions:
- `s3:PutObject`
- `s3:DeleteObject`
- `cloudfront:CreateInvalidation`

### Issue: Application shows "Failed to load recent submissions"

**Solution**: Verify your environment variables are correct:
1. Check the browser console for errors
2. Verify the API endpoint is accessible
3. Ensure Cognito configuration matches your User Pool settings

### Issue: "Invalid client id" error during login

**Solution**: Verify the Cognito client ID in your `.env` file matches the one created by CDK.

## Manual Deployment (Alternative)

If the deployment script doesn't work, you can deploy manually:

```bash
# Build
cd frontend/
bash build.sh

# Get S3 bucket name
S3_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name DataCollectionWebAppFrontend-dev \
    --region eu-central-1 \
    --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
    --output text)

# Upload to S3
aws s3 sync build/ s3://$S3_BUCKET/ --delete --region eu-central-1

# Get CloudFront distribution ID
DISTRIBUTION_ID=$(aws cloudformation describe-stacks \
    --stack-name DataCollectionWebAppFrontend-dev \
    --region eu-central-1 \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
    --output text)

# Invalidate cache
aws cloudfront create-invalidation \
    --distribution-id $DISTRIBUTION_ID \
    --paths "/*" \
    --region eu-central-1
```

## Cache Strategy

The deployment uses the following cache strategy:

- **Static assets** (CSS, JS): 1 hour cache (`max-age=3600`)
- **index.html**: No cache (`max-age=0, must-revalidate`)

This ensures:
- Users always get the latest HTML
- Static assets are cached for performance
- CloudFront invalidation clears all caches

## Security Considerations

1. **HTTPS Only**: CloudFront enforces HTTPS for all connections
2. **S3 Access**: S3 bucket is not publicly accessible; only CloudFront can access it
3. **CORS**: API requests are protected by JWT authorization
4. **Environment Variables**: Sensitive values (client IDs, domains) are injected at build time

## Rollback

To rollback to a previous version:

1. Check S3 bucket versioning:
   ```bash
   aws s3api list-object-versions --bucket $S3_BUCKET --region eu-central-1
   ```

2. Restore a previous version:
   ```bash
   aws s3api get-object --bucket $S3_BUCKET --key index.html --version-id VERSION_ID index.html
   aws s3 cp index.html s3://$S3_BUCKET/index.html
   ```

3. Invalidate CloudFront cache:
   ```bash
   aws cloudfront create-invalidation --distribution-id $DISTRIBUTION_ID --paths "/*"
   ```

## Monitoring

Monitor your deployment using:

1. **CloudFront Logs**: Check S3 bucket `data-collection-cf-logs-{env}`
2. **CloudWatch**: Monitor Lambda function logs
3. **AWS Console**: Check CloudFront distribution metrics

## Next Steps

After successful deployment:

1. Test the application with real users
2. Monitor CloudWatch logs for errors
3. Set up automated deployments (CI/CD pipeline)
4. Configure custom domain (optional)
5. Set up WAF rules for additional security (optional)
