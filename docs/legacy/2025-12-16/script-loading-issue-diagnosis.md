# Script Loading Issue - Diagnosis & Solution

## Problem Summary

The debug page shows:
- ✗ Configuration NOT loaded
- ✗ All scripts NOT loaded (red)

But the files ARE in S3 and ARE accessible via CloudFront (HTTP 200).

---

## Root Cause

The scripts are being downloaded by the browser but **not being executed**. This is likely due to:

1. **Browser security policy** - Scripts might be blocked
2. **Syntax error in scripts** - Error prevents execution
3. **Missing dependencies** - Scripts depend on each other
4. **Timing issue** - Scripts loading in wrong order

---

## Diagnostic Steps

### Step 1: Test Simple Script Loading

Open this URL in your browser:
```
https://d3qlp39n4pyhxb.cloudfront.net/simple-test.html
```

This page will show if config.js can load and execute.

**Expected result:**
```
Page loaded
✓ config.js loaded successfully
API_ENDPOINT: https://mowswsomwf.execute-api.eu-central-1.amazonaws.com
```

**If you see this, config.js is working!**

### Step 2: Check Browser Console

Open Developer Tools (`F12`) and go to **Console** tab.

Look for:
- Red error messages
- Warnings about blocked scripts
- CORS errors
- Syntax errors

**Copy any error messages** - they will help diagnose the issue.

### Step 3: Check Network Tab

Open Developer Tools (`F12`) and go to **Network** tab.

Reload the page and look for:
- `config.js` - Should show 200 OK
- `auth.js` - Should show 200 OK
- `app.js` - Should show 200 OK

**If any show 404 or 403:**
- File is missing from S3
- Need to redeploy

**If all show 200 but scripts don't execute:**
- There's a syntax error or security issue

### Step 4: Check Content-Type Headers

In Network tab, click on each script file and check the **Headers** tab.

Look for:
```
content-type: text/javascript
```

or

```
content-type: application/javascript
```

If it shows `text/plain` or something else, that's the problem.

---

## Possible Solutions

### Solution 1: Hard Refresh & Clear Cache

**Chrome/Edge:**
```
Ctrl+Shift+R (Windows)
Cmd+Shift+R (Mac)
```

**Firefox:**
```
Ctrl+F5 (Windows)
Cmd+Shift+R (Mac)
```

**Safari:**
```
Cmd+Option+R (Mac)
```

### Solution 2: Invalidate CloudFront Cache

```bash
aws cloudfront create-invalidation \
    --distribution-id E33N0UUQ66WDN5 \
    --paths "/*" \
    --region eu-central-1
```

Wait for invalidation to complete (usually 1-2 minutes).

### Solution 3: Check S3 Content-Type

The files might have wrong content-type. Fix it:

```bash
# Set correct content-type for JavaScript files
aws s3 cp s3://data-collection-frontend-dev/config.js s3://data-collection-frontend-dev/config.js \
    --metadata-directive COPY \
    --content-type "application/javascript" \
    --region eu-central-1

aws s3 cp s3://data-collection-frontend-dev/auth.js s3://data-collection-frontend-dev/auth.js \
    --metadata-directive COPY \
    --content-type "application/javascript" \
    --region eu-central-1

aws s3 cp s3://data-collection-frontend-dev/app.js s3://data-collection-frontend-dev/app.js \
    --metadata-directive COPY \
    --content-type "application/javascript" \
    --region eu-central-1
```

Then invalidate CloudFront:

```bash
aws cloudfront create-invalidation \
    --distribution-id E33N0UUQ66WDN5 \
    --paths "/*" \
    --region eu-central-1
```

### Solution 4: Redeploy Everything

If the above doesn't work, redeploy:

```bash
cd web-form-verbrauch/frontend/

# Clean build
rm -rf build/

# Rebuild
bash build.sh

# Redeploy
bash deploy.sh dev
```

### Solution 5: Check for Syntax Errors

Validate JavaScript syntax:

```bash
# Check config.js
curl -s https://d3qlp39n4pyhxb.cloudfront.net/config.js | node -c

# Check auth.js
curl -s https://d3qlp39n4pyhxb.cloudfront.net/auth.js | node -c

# Check app.js
curl -s https://d3qlp39n4pyhxb.cloudfront.net/app.js | node -c
```

If any show syntax errors, the file needs to be fixed.

---

## Test URLs

Use these URLs to test different aspects:

1. **Simple config test:**
   ```
   https://d3qlp39n4pyhxb.cloudfront.net/simple-test.html
   ```

2. **Full script loading test:**
   ```
   https://d3qlp39n4pyhxb.cloudfront.net/test.html
   ```

3. **Debug page:**
   ```
   https://d3qlp39n4pyhxb.cloudfront.net/debug.html
   ```

4. **Main application:**
   ```
   https://d3qlp39n4pyhxb.cloudfront.net
   ```

---

## What to Do Next

1. **Open simple-test.html** - See if config.js loads
2. **Check browser console** - Look for errors
3. **Check Network tab** - Verify files load with 200 OK
4. **Try hard refresh** - Clear browser cache
5. **Invalidate CloudFront** - Clear CDN cache
6. **Redeploy if needed** - Run deploy.sh again

---

## If Still Not Working

Please provide:

1. **Screenshot of simple-test.html** - Shows if config.js loads
2. **Browser console errors** - Copy/paste any red errors
3. **Network tab screenshot** - Shows which files loaded
4. **Output of these commands:**

```bash
# Check S3 files
aws s3 ls s3://data-collection-frontend-dev/ --region eu-central-1

# Check file content-type
aws s3api head-object \
    --bucket data-collection-frontend-dev \
    --key config.js \
    --region eu-central-1 | grep ContentType

# Check CloudFront
aws cloudfront get-distribution \
    --id E33N0UUQ66WDN5 \
    --region eu-central-1 | grep -A 5 "Origins"
```

---

## Quick Fix Checklist

- [ ] Opened simple-test.html and saw config.js load
- [ ] Checked browser console - no red errors
- [ ] Checked Network tab - all files show 200 OK
- [ ] Hard refreshed browser (Ctrl+Shift+R)
- [ ] Invalidated CloudFront cache
- [ ] Waited 2 minutes for invalidation to complete
- [ ] Reloaded main application
- [ ] Saw login page appear

If all checked and still not working, redeploy:

```bash
cd web-form-verbrauch/frontend/
bash deploy.sh dev
```

