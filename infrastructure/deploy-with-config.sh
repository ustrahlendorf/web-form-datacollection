#!/bin/bash

# Deploy CDK infrastructure with environment configuration
# This script deploys the CDK stacks and then configures the frontend with the deployed resources

set -e

# Configuration
ENVIRONMENT="${1:-dev}"
REGION="eu-central-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "CDK Deployment with Configuration"
echo "=========================================="
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo ""

# Validate environment
if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
    echo "Error: Environment must be 'dev' or 'prod'"
    exit 1
fi

# Deploy CDK stacks
echo "Deploying CDK stacks..."
cd "$SCRIPT_DIR"
cdk deploy --all --require-approval never

echo ""
echo "CDK deployment complete!"
echo ""

# Get CloudFront domain from stack outputs
echo "Retrieving CloudFront domain from stack outputs..."
FRONTEND_STACK="DataCollectionFrontend-$ENVIRONMENT"
CLOUDFRONT_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name "$FRONTEND_STACK" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomainName'].OutputValue" \
    --output text 2>/dev/null || echo "")

if [[ -z "$CLOUDFRONT_DOMAIN" ]]; then
    echo "Warning: Could not retrieve CloudFront domain"
    echo "Frontend configuration may need to be updated manually"
else
    echo "CloudFront Domain: $CLOUDFRONT_DOMAIN"
    
    # Update Cognito callback URLs with CloudFront domain
    echo ""
    echo "Updating Cognito callback URLs with CloudFront domain..."
    
    COGNITO_STACK="DataCollectionCognito-$ENVIRONMENT"
    USER_POOL_ID=$(aws cloudformation describe-stacks \
        --stack-name "$COGNITO_STACK" \
        --region "$REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
        --output text 2>/dev/null || echo "")
    
    if [[ -n "$USER_POOL_ID" ]]; then
        # Get the client ID
        CLIENT_ID=$(aws cloudformation describe-stacks \
            --stack-name "$COGNITO_STACK" \
            --region "$REGION" \
            --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" \
            --output text 2>/dev/null || echo "")
        
        if [[ -n "$CLIENT_ID" ]]; then
            # Update the client with new callback URLs
            aws cognito-idp update-user-pool-client \
                --user-pool-id "$USER_POOL_ID" \
                --client-id "$CLIENT_ID" \
                --callback-urls "http://localhost:3000" "http://localhost:8000" "https://$CLOUDFRONT_DOMAIN" \
                --logout-urls "http://localhost:3000" "http://localhost:8000" "https://$CLOUDFRONT_DOMAIN" \
                --region "$REGION" 2>/dev/null || echo "Note: Could not update Cognito client URLs"
        fi
    fi
fi

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Setup frontend environment: cd ../frontend && bash setup-env.sh $ENVIRONMENT"
echo "  2. Build frontend: bash build.sh"
echo "  3. Deploy frontend: bash deploy.sh $ENVIRONMENT"
echo ""
