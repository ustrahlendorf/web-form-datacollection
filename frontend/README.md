# Frontend Application

This is the frontend for the Data Collection Web Application, a serverless web application built on AWS.

## Overview

The frontend is a static web application (HTML, CSS, JavaScript) that:
- Authenticates users via AWS Cognito
- Submits operational data through a web form
- Displays submission history with pagination
- Shows recent submissions on the form page

## Architecture

- **Hosting**: AWS S3 + CloudFront CDN
- **Authentication**: AWS Cognito User Pool with OAuth2
- **API Communication**: AWS API Gateway with JWT authorization
- **Deployment**: AWS CDK infrastructure as code

## Project Structure

```
frontend/
├── index.html              # Main HTML file
├── styles.css              # Application styles
├── app.js                  # Main application logic
├── auth.js                 # Authentication module
├── config.js               # Configuration (generated during build)
├── build.sh                # Build script
├── deploy.sh               # Deployment script
├── setup-env.sh            # Environment setup script
├── .env.example            # Environment variables template
├── README.md               # This file
├── package.json            # NPM dependencies
├── jest.config.js          # Jest test configuration
├── form.test.js            # Form component tests
├── form-integration.test.html  # Integration tests
└── form-prepopulation.pbt.js   # Property-based tests
```

## Quick Start

### 1. Setup Environment Variables

```bash
cd frontend/
bash setup-env.sh dev
```

This script will:
- Retrieve CloudFront domain, API endpoint, and Cognito configuration from CDK outputs
- Generate a `.env` file with the correct values

### 2. Build the Frontend

```bash
bash build.sh
```

This creates a `build/` directory with all frontend files ready for deployment.

### 3. Deploy to S3 and CloudFront

```bash
bash deploy.sh dev
```

This will:
- Upload files to S3
- Invalidate CloudFront cache
- Display the URL where your application is accessible

### 4. Access the Application

Open the CloudFront URL in your browser and log in with your Cognito credentials.

## Development

### Local Testing

To test the frontend locally:

```bash
# Start a local web server
npm run serve

# Open http://localhost:8000 in your browser
```

### Running Tests

```bash
# Run unit tests
npm test

# Run property-based tests
npm run test -- form-prepopulation.pbt.js
```

### Configuration

The frontend uses environment variables for configuration:

- `REACT_APP_API_ENDPOINT`: API Gateway endpoint URL
- `REACT_APP_COGNITO_DOMAIN`: Cognito domain
- `REACT_APP_COGNITO_CLIENT_ID`: Cognito client ID
- `REACT_APP_COGNITO_REDIRECT_URI`: CloudFront domain (for OAuth callback)

These are injected during the build process from the `.env` file.

## Features

### Authentication
- OAuth2 flow with Cognito Hosted UI
- JWT token management
- Automatic token refresh
- Logout functionality

### Form Page
- Pre-populated date (current date in dd.mm.yyyy format)
- Pre-populated time (current time in hh:mm format)
- Form validation (client-side)
- Recent submissions display (last 3 from past 3 days)
- Success/error messages

### History Page
- Paginated submission history (20 items per page)
- Sorted by timestamp (newest first)
- Read-only display
- Navigation controls

## Deployment

For detailed deployment instructions, see `../docs/getting-started.md`.

### Quick Deployment

```bash
# Setup environment
bash setup-env.sh dev

# Build and deploy
bash build.sh
bash deploy.sh dev
```

### Production Deployment

```bash
bash setup-env.sh prod
bash build.sh
bash deploy.sh prod
```

## Troubleshooting

### Application shows "Failed to load recent submissions"

1. Check browser console for errors
2. Verify API endpoint is correct in `.env`
3. Ensure Cognito configuration is correct
4. Check that API Gateway is deployed and accessible

### "Invalid client id" error during login

1. Verify Cognito client ID in `.env` matches CDK output
2. Check that Cognito User Pool is deployed
3. Verify redirect URI matches CloudFront domain

### Files not updating after deployment

1. Clear browser cache
2. Check CloudFront invalidation completed
3. Verify S3 bucket has the latest files: `aws s3 ls s3://bucket-name/`

## Security

- **HTTPS Only**: All connections are encrypted
- **JWT Authorization**: API requests require valid JWT tokens
- **CORS Protection**: API requests are restricted to frontend domain
- **S3 Access**: S3 bucket is not publicly accessible
- **Environment Variables**: Sensitive values are injected at build time

## Performance

- **CloudFront CDN**: Global content delivery
- **Cache Strategy**: Static assets cached for 1 hour, HTML not cached
- **Compression**: CloudFront automatically compresses responses
- **Lazy Loading**: Recent submissions loaded on demand

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Dependencies

### Runtime
- None (vanilla JavaScript)

### Development
- jest: Testing framework
- fast-check: Property-based testing
- jest-environment-jsdom: DOM testing environment

## Scripts

- `npm test`: Run unit tests
- `npm run build`: Build frontend (alias for `bash build.sh`)
- `npm run serve`: Start local web server
- `npm run deploy`: Deploy to S3 (requires environment setup)

## Contributing

When making changes to the frontend:

1. Test locally: `npm run serve`
2. Run tests: `npm test`
3. Build: `bash build.sh`
4. Deploy: `bash deploy.sh dev`

## License

MIT

## Support

For issues or questions:
1. Check `../docs/operations/troubleshooting.md` first
2. Review browser console for error messages
3. Check CloudWatch logs for API errors
4. Verify AWS credentials and permissions
