#!/bin/bash

# Deploy CDK infrastructure with environment configuration
# This script deploys the CDK stacks and then configures the frontend with the deployed resources

set -e

# Configuration
ENVIRONMENT="${1:-dev}"
REGION="eu-central-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Ensure CDK has an explicit account/region to deploy into.
# CDK can infer these sometimes, but it's safer to set them explicitly for scripts.
export CDK_DEFAULT_REGION="$REGION"
if [[ -z "${CDK_DEFAULT_ACCOUNT:-}" ]]; then
    CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text --region "$REGION" 2>/dev/null || echo "")
    if [[ -n "$CDK_DEFAULT_ACCOUNT" ]]; then
        export CDK_DEFAULT_ACCOUNT
    else
        echo "Error: Unable to resolve AWS account (CDK_DEFAULT_ACCOUNT). Check your AWS credentials/config."
        exit 1
    fi
fi

echo "=========================================="
echo "CDK Deployment with Configuration"
echo "=========================================="
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo ""

# Validate environment
if [[ "$ENVIRONMENT" != "dev" ]]; then
    echo "Error: This project is dev-only. Environment must be 'dev'"
    exit 1
fi

# Deploy CDK stacks
echo "Deploying CDK stacks..."
# Run CDK from the project root so cdk.json (and its "app" command) is found.
cd "$PROJECT_ROOT"
cdk deploy \
    "DataCollectionCognito-$ENVIRONMENT" \
    "DataCollectionDynamoDB-$ENVIRONMENT" \
    "DataCollectionFrontend-$ENVIRONMENT" \
    "DataCollectionAPI-$ENVIRONMENT" \
    --require-approval never

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
                --allowed-o-auth-flows-user-pool-client \
                --allowed-o-auth-flows code \
                --allowed-o-auth-scopes openid email profile \
                --supported-identity-providers COGNITO \
                --callback-urls "http://localhost:3000" "http://localhost:8000" "https://$CLOUDFRONT_DOMAIN" "https://$CLOUDFRONT_DOMAIN/" \
                --logout-urls "http://localhost:3000" "http://localhost:8000" "https://$CLOUDFRONT_DOMAIN" "https://$CLOUDFRONT_DOMAIN/" \
                --region "$REGION" || echo "Note: Could not update Cognito client OAuth/callback/logout URLs"
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
