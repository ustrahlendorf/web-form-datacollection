# Troubleshooting: Blank Page Issue

## Problem
When accessing https://d3qlp39n4pyhxb.cloudfront.net, you see a blank page with no login button or form.

## Root Cause Analysis

The issue is likely one of these:

1. **JavaScript not executing** - Scripts may not be loading or running
2. **JavaScript error** - An error in the code is preventing execution
3. **Configuration not loaded** - The config.js file isn't being loaded properly
4. **CORS issue** - Cross-origin requests are being blocked
5. **Browser cache** - Old cached version is being served

---

## Step 1: Check the Debug Page

I've created a debug page to help diagnose the issue.

**Access**: https://d3qlp39n4pyhxb.cloudfront.net/debug.html

This page will show you:
- ✓ Configuration status
- ✓ Script loading status
- ✓ Console errors
- ✓ Local storage contents
- ✓ DOM elements

**What to look for:**
- All scripts should show ✓ (loaded)
- Configuration should show ✓ (loaded)
- No console errors should be present

---

## Step 2: Check Browser Console

Open your browser's Developer Tools:

**Chrome/Edge**: Press `F12` or `Ctrl+Shift+I` (Windows) / `Cmd+Option+I` (Mac)
**Firefox**: Press `F12` or `Ctrl+Shift+I` (Windows) / `Cmd+Option+I` (Mac)
**Safari**: Enable Developer Menu, then press `Cmd+Option+I`

Go to the **Console** tab and look for:
- Red error messages
- Network errors
- CORS errors
- Undefined variables

**Common errors to look for:**
```
Uncaught ReferenceError: AuthManager is not defined
Uncaught SyntaxError: Unexpected token
Failed to fetch
CORS error
```

---

## Step 3: Check Network Tab

In Developer Tools, go to the **Network** tab and reload the page.

Look for:
- `index.html` - Should be 200 OK
- `config.js` - Should be 200 OK
- `auth.js` - Should be 200 OK
- `app.js` - Should be 200 OK
- `styles.css` - Should be 200 OK

**If any file shows 404 or 403:**
- The file wasn't uploaded to S3
- CloudFront cache needs invalidation
- S3 bucket permissions issue

---

## Step 4: Clear Cache and Reload

The issue might be CloudFront serving old cached files.

**Option 1: Hard Refresh**
- Chrome/Edge: `Ctrl+Shift+R` (Windows) / `Cmd+Shift+R` (Mac)
- Firefox: `Ctrl+F5` (Windows) / `Cmd+Shift+R` (Mac)
- Safari: `Cmd+Option+R` (Mac)

**Option 2: Clear Browser Cache**
- Open Developer Tools
- Right-click the reload button
- Select "Empty cache and hard reload"

**Option 3: Invalidate CloudFront Cache**
```bash
aws cloudfront create-invalidation \
    --distribution-id E33N0UUQ66WDN5 \
    --paths "/*" \
    --region eu-central-1
```

---

## Step 5: Verify S3 Files

Check that all files are in S3:

```bash
aws s3 ls s3://data-collection-frontend-dev/ --region eu-central-1
```

Expected output:
```
2025-12-16 22:45:02      14228 app.js
2025-12-16 22:45:02      11053 auth.js
2025-12-16 22:45:02       1136 config.js
2025-12-16 22:45:04       6209 index.html
2025-12-16 22:45:02       5949 styles.css
```

If files are missing, redeploy:
```bash
cd frontend/
bash deploy.sh dev
```

---

## Step 6: Check File Content

Verify the files have correct content:

```bash
# Check config.js has real values
curl https://d3qlp39n4pyhxb.cloudfront.net/config.js | grep API_ENDPOINT

# Check index.html loads
curl https://d3qlp39n4pyhxb.cloudfront.net | head -20
```

---

## Step 7: Check Cognito Configuration

Verify Cognito is properly configured:

```bash
# Check User Pool exists
aws cognito-idp describe-user-pool \
    --user-pool-id eu-central-1_B1NKA94F8 \
    --region eu-central-1

# Check Client ID is correct
aws cognito-idp list-user-pool-clients \
    --user-pool-id eu-central-1_B1NKA94F8 \
    --region eu-central-1
```

---

## Step 8: Check API Gateway

Verify API Gateway is accessible:

```bash
# Test API endpoint
curl https://mowswsomwf.execute-api.eu-central-1.amazonaws.com/recent \
    -H "Authorization: Bearer test-token"
```

Should return an error about invalid token, not a 404.

---

## Common Issues & Solutions

### Issue: "Uncaught ReferenceError: AuthManager is not defined"

**Cause**: auth.js didn't load before app.js tried to use it

**Solution**:
1. Check Network tab - auth.js should load before app.js
2. Verify auth.js is in S3
3. Invalidate CloudFront cache
4. Hard refresh browser

### Issue: "Failed to fetch" or CORS error

**Cause**: API Gateway endpoint is not accessible or CORS is misconfigured

**Solution**:
1. Verify API endpoint in config.js is correct
2. Check API Gateway CORS settings
3. Verify CloudFront domain is in CORS allowed origins
4. Test API directly: `curl https://mowswsomwf.execute-api.eu-central-1.amazonaws.com/recent`

### Issue: "Unexpected token" in console

**Cause**: JavaScript syntax error in one of the files

**Solution**:
1. Check which file has the error (Network tab)
2. Rebuild frontend: `bash build.sh`
3. Redeploy: `bash deploy.sh dev`

### Issue: Blank page but no errors in console

**Cause**: JavaScript is running but not displaying anything

**Solution**:
1. Check if login section is hidden: Open DevTools → Elements → Find `#login-section`
2. Check if it has `style="display: none;"`
3. Check if AuthManager is initializing properly
4. Look for network errors in Network tab

---

## Manual Testing Steps

If the debug page shows everything is loaded:

1. **Open DevTools Console** and run:
```javascript
// Check if config is loaded
console.log(window.APP_CONFIG);

// Check if AuthManager exists
console.log(typeof AuthManager);

// Check if app functions exist
console.log(typeof navigateToPage);

// Check authentication status
console.log(localStorage.getItem('access_token'));
```

2. **Manually trigger login**:
```javascript
// Create auth manager
const authManager = new AuthManager(window.APP_CONFIG);

// Check if authenticated
console.log(authManager.isAuthenticated());

// Initiate login
authManager.initiateLogin();
```

---

## If Still Not Working

### Option 1: Rebuild and Redeploy

```bash
cd web-form-verbrauch/frontend/

# Clean build
rm -rf build/

# Rebuild
bash build.sh

# Redeploy
bash deploy.sh dev
```

### Option 2: Check CloudFront Distribution

```bash
# Get distribution details
aws cloudfront get-distribution \
    --id E33N0UUQ66WDN5 \
    --region eu-central-1

# Check if distribution is enabled
# Check if S3 origin is correct
# Check if behaviors are configured
```

### Option 3: Check S3 Bucket Policy

```bash
# Get bucket policy
aws s3api get-bucket-policy \
    --bucket data-collection-frontend-dev \
    --region eu-central-1

# Should allow CloudFront to access
```

### Option 4: Redeploy Everything

```bash
# Go to infrastructure
cd infrastructure/

# Redeploy CDK stacks
cdk deploy --all

# Then redeploy frontend
cd ../frontend/
bash setup-env.sh dev
bash build.sh
bash deploy.sh dev
```

---

## Debug Page URL

**Access the debug page**: https://d3qlp39n4pyhxb.cloudfront.net/debug.html

This will show you:
- Configuration loaded status
- Script loading status
- Any console errors
- Local storage contents
- DOM elements present

---

## Getting Help

If you're still stuck, provide:

1. **Screenshot of debug page** - Shows what's loaded
2. **Browser console errors** - Copy/paste any red errors
3. **Network tab screenshot** - Shows which files loaded
4. **Output of these commands**:
```bash
# Check S3 files
aws s3 ls s3://data-collection-frontend-dev/

# Check CloudFront
aws cloudfront get-distribution --id E33N0UUQ66WDN5 --region eu-central-1

# Check API
curl https://mowswsomwf.execute-api.eu-central-1.amazonaws.com/recent
```

---

## Next Steps

Once you identify the issue:

1. **If files are missing**: Run `bash deploy.sh dev`
2. **If cache is stale**: Invalidate CloudFront
3. **If JavaScript error**: Check console and fix the error
4. **If CORS error**: Verify API Gateway CORS settings
5. **If Cognito error**: Verify Cognito configuration

