#!/bin/bash

# Frontend deployment script
# This script builds the frontend and deploys it to S3 with CloudFront invalidation

set -e

# Configuration
ENVIRONMENT="${1:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "Frontend Deployment Script"
echo "=========================================="
echo "Environment: $ENVIRONMENT"
echo ""

# Validate environment
if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
    echo "Error: Environment must be 'dev' or 'prod'"
    exit 1
fi

# Step 1: Build frontend
echo "Step 1: Building frontend application..."
cd "$SCRIPT_DIR"
bash build.sh

# Step 2: Get S3 bucket name and CloudFront distribution ID from CDK outputs
echo ""
echo "Step 2: Retrieving AWS resources from CDK outputs..."

# Get the stack name
STACK_NAME="DataCollectionWebAppFrontend-$ENVIRONMENT"

# Try to get outputs from CDK
S3_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region eu-central-1 \
    --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
    --output text 2>/dev/null || echo "")

DISTRIBUTION_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region eu-central-1 \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
    --output text 2>/dev/null || echo "")

CLOUDFRONT_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region eu-central-1 \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomainName'].OutputValue" \
    --output text 2>/dev/null || echo "")

if [[ -z "$S3_BUCKET" || -z "$DISTRIBUTION_ID" ]]; then
    echo "Error: Could not retrieve S3 bucket or CloudFront distribution ID from CDK outputs"
    echo "Make sure the infrastructure has been deployed with: cdk deploy --all"
    exit 1
fi

echo "S3 Bucket: $S3_BUCKET"
echo "CloudFront Distribution ID: $DISTRIBUTION_ID"
echo "CloudFront Domain: $CLOUDFRONT_DOMAIN"
echo ""

# Step 3: Upload files to S3
echo "Step 3: Uploading frontend files to S3..."
aws s3 sync "$SCRIPT_DIR/build/" "s3://$S3_BUCKET/" \
    --region eu-central-1 \
    --delete \
    --cache-control "public, max-age=3600" \
    --exclude "index.html" \
    --exclude ".DS_Store"

# Upload index.html with no-cache policy
aws s3 cp "$SCRIPT_DIR/build/index.html" "s3://$S3_BUCKET/index.html" \
    --region eu-central-1 \
    --cache-control "public, max-age=0, must-revalidate" \
    --content-type "text/html"

echo "Files uploaded successfully!"
echo ""

# Step 4: Invalidate CloudFront cache
echo "Step 4: Invalidating CloudFront cache..."
INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id "$DISTRIBUTION_ID" \
    --paths "/*" \
    --region eu-central-1 \
    --query 'Invalidation.Id' \
    --output text)

echo "Invalidation created with ID: $INVALIDATION_ID"
echo ""

# Step 5: Wait for invalidation to complete
echo "Step 5: Waiting for CloudFront invalidation to complete..."
aws cloudfront wait invalidation-completed \
    --distribution-id "$DISTRIBUTION_ID" \
    --id "$INVALIDATION_ID" \
    --region eu-central-1

echo "CloudFront cache invalidated successfully!"
echo ""

# Step 6: Verify deployment
echo "Step 6: Verifying deployment..."
echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Frontend is now accessible at:"
echo "  https://$CLOUDFRONT_DOMAIN"
echo ""
echo "To verify the deployment, you can:"
echo "  1. Open https://$CLOUDFRONT_DOMAIN in your browser"
echo "  2. Check S3 bucket contents: aws s3 ls s3://$S3_BUCKET/"
echo "  3. Check CloudFront distribution: https://console.aws.amazon.com/cloudfront/"
echo ""
