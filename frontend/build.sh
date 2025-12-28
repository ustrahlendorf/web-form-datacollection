#!/bin/bash

# Build script for frontend deployment to S3
# This script prepares the frontend files for deployment

set -e

echo "Building frontend application..."

# Create build directory
BUILD_DIR="build"
if [ -d "$BUILD_DIR" ]; then
    rm -rf "$BUILD_DIR"
fi
mkdir -p "$BUILD_DIR"

# Load environment variables from .env file if it exists
if [ -f ".env" ]; then
    echo "Loading environment variables from .env file..."
    set -a
    source .env
    set +a
fi

# Copy HTML, CSS, and JS files
echo "Copying frontend files..."
cp index.html "$BUILD_DIR/"
cp styles.css "$BUILD_DIR/"
cp app.js "$BUILD_DIR/"
cp auth.js "$BUILD_DIR/"

# Create config.js with environment variables
echo "Creating configuration file..."
cat > "$BUILD_DIR/config.js" << EOF
/**
 * Application Configuration
 * This file is auto-generated during the build process with environment-specific values
 * from CDK stack outputs and environment variables.
 */

// Configuration object that will be used by auth.js and app.js
window.APP_CONFIG = {
    // API Gateway endpoint URL
    API_ENDPOINT: '${API_ENDPOINT:-http://localhost:3000}',
    
    // Cognito configuration
    COGNITO_DOMAIN: '${COGNITO_DOMAIN:-https://your-domain.auth.eu-central-1.amazoncognito.com}',
    COGNITO_CLIENT_ID: '${COGNITO_CLIENT_ID:-your-client-id}',
    COGNITO_REDIRECT_URI: '${COGNITO_REDIRECT_URI:-http://localhost:3000}',
    COGNITO_USER_POOL_ID: '${COGNITO_USER_POOL_ID:-your-user-pool-id}',
    
    // CloudFront domain for CORS
    CLOUDFRONT_DOMAIN: '${CLOUDFRONT_DOMAIN:-your-cloudfront-domain}',
    
    // Environment name
    ENVIRONMENT: '${ENVIRONMENT:-dev}',
};

// Log configuration on page load (for debugging)
console.log('Application Configuration Loaded:', {
    environment: window.APP_CONFIG.ENVIRONMENT,
    apiEndpoint: window.APP_CONFIG.API_ENDPOINT,
    cognitoDomain: window.APP_CONFIG.COGNITO_DOMAIN,
    cloudFrontDomain: window.APP_CONFIG.CLOUDFRONT_DOMAIN,
});
EOF

# Cache-busting: create content-hashed asset filenames and rewrite build/index.html to reference them.
# This prevents browsers from using stale cached JS/CSS between deployments.
hash_file() {
    # Use sha256 and keep it short for readable filenames.
    shasum -a 256 "$1" | awk '{print substr($1,1,12)}'
}

echo "Applying cache-busting (content-hash filenames)..."
APP_HASH="$(hash_file "$BUILD_DIR/app.js")"
AUTH_HASH="$(hash_file "$BUILD_DIR/auth.js")"
CONFIG_HASH="$(hash_file "$BUILD_DIR/config.js")"
CSS_HASH="$(hash_file "$BUILD_DIR/styles.css")"

mv "$BUILD_DIR/app.js" "$BUILD_DIR/app.${APP_HASH}.js"
mv "$BUILD_DIR/auth.js" "$BUILD_DIR/auth.${AUTH_HASH}.js"
mv "$BUILD_DIR/config.js" "$BUILD_DIR/config.${CONFIG_HASH}.js"
mv "$BUILD_DIR/styles.css" "$BUILD_DIR/styles.${CSS_HASH}.css"

# macOS/BSD sed requires an explicit backup suffix argument; use '' for in-place without backups.
sed -i '' -e "s|href=\"styles.css\"|href=\"styles.${CSS_HASH}.css\"|g" "$BUILD_DIR/index.html"
sed -i '' -e "s|src=\"config.js\"|src=\"config.${CONFIG_HASH}.js\"|g" "$BUILD_DIR/index.html"
sed -i '' -e "s|src=\"auth.js\"|src=\"auth.${AUTH_HASH}.js\"|g" "$BUILD_DIR/index.html"
sed -i '' -e "s|src=\"app.js\"|src=\"app.${APP_HASH}.js\"|g" "$BUILD_DIR/index.html"

echo "Cache-busting version:"
echo "  app.${APP_HASH}.js"
echo "  auth.${AUTH_HASH}.js"
echo "  config.${CONFIG_HASH}.js"
echo "  styles.${CSS_HASH}.css"

echo "Frontend build complete!"
echo "Build directory: $BUILD_DIR"
echo ""
echo "Configuration:"
echo "  API_ENDPOINT: ${API_ENDPOINT:-http://localhost:3000}"
echo "  COGNITO_DOMAIN: ${COGNITO_DOMAIN:-https://your-domain.auth.eu-central-1.amazoncognito.com}"
echo "  COGNITO_CLIENT_ID: ${COGNITO_CLIENT_ID:-your-client-id}"
echo "  COGNITO_USER_POOL_ID: ${COGNITO_USER_POOL_ID:-your-user-pool-id}"
echo "  CLOUDFRONT_DOMAIN: ${CLOUDFRONT_DOMAIN:-your-cloudfront-domain}"
echo "  ENVIRONMENT: ${ENVIRONMENT:-dev}"
echo ""
echo "To deploy to S3, run:"
echo "  ./deploy.sh dev"
echo ""
