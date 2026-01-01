# Diagnostic Guide - Error Capture Page

## Problem
The application briefly shows a form then goes blank. We need to capture the JavaScript errors causing this.

## Solution
I've created a comprehensive error capture page that will show us exactly what's going wrong.

---

## How to Use the Diagnostic Page

### Step 1: Open the Diagnostic Page

**URL**: https://d3qlp39n4pyhxb.cloudfront.net/error-capture.html

Open this in your browser (use incognito/private window to avoid cache issues).

### Step 2: What You'll See

The page has several sections:

1. **Configuration Status** - Shows if config.js loaded
2. **Script Loading Status** - Shows if all scripts loaded
3. **Captured Errors** - Shows any JavaScript errors
4. **Console Output** - Shows all console.log/warn/error messages
5. **DOM Elements Check** - Shows if HTML elements exist
6. **Actions** - Buttons to test different parts

### Step 3: Read the Errors

The **Captured Errors** section will show:
- Error type (uncaught, unhandledRejection, etc.)
- Error message
- Stack trace (if available)
- File and line number (if available)
- Timestamp

### Step 4: Share the Information

Once you see errors, please share:

1. **Screenshot of the Captured Errors section** - Shows what went wrong
2. **Screenshot of the Console Output section** - Shows what was logged
3. **Screenshot of the DOM Elements Check** - Shows what elements exist
4. **Screenshot of the Script Loading Status** - Shows what loaded

---

## What Each Section Tells Us

### Configuration Status
- ✅ **Green checkmark** = config.js loaded successfully
- ❌ **Red X** = config.js did NOT load

If red, the issue is that configuration isn't being loaded.

### Script Loading Status
- ✅ **Green checkmark** = Script loaded
- ❌ **Red X** = Script NOT loaded

If any are red, that script didn't load properly.

### Captured Errors
- **Empty** = No errors (good!)
- **Red items** = JavaScript errors occurred

Each error shows:
- Type of error
- What went wrong
- Where it happened
- When it happened

### Console Output
Shows all messages that were logged to the console:
- Blue = console.log() messages
- Yellow = console.warn() messages
- Red = console.error() messages

### DOM Elements Check
Shows if the HTML elements exist on the page:
- ✅ **Green** = Element exists and is visible
- ❌ **Red** = Element missing or hidden

---

## Action Buttons

### Load Main App
Tries to navigate to the form page. If this fails, you'll see an error.

### Check AuthManager
Tests if the AuthManager class can be initialized. If this fails, auth.js didn't load.

### Check Config
Displays the actual configuration values (API endpoint, Cognito settings, etc.)

### Clear Logs
Clears all captured errors and logs to start fresh.

---

## Common Issues and What They Mean

### Issue: "Configuration NOT loaded"
**Cause**: config.js didn't load or didn't set window.APP_CONFIG

**Next Step**: Check if config.js is in S3 and if it's being served correctly

### Issue: "auth.js: NOT loaded"
**Cause**: auth.js didn't load from S3

**Next Step**: Check if auth.js is in S3 and if it's being served correctly

### Issue: "app.js: NOT loaded"
**Cause**: app.js didn't load from S3

**Next Step**: Check if app.js is in S3 and if it's being served correctly

### Issue: Errors in "Captured Errors" section
**Cause**: JavaScript runtime error

**Next Step**: Read the error message and stack trace to understand what went wrong

### Issue: "Cannot read properties of null"
**Cause**: Code tried to use a DOM element that doesn't exist

**Next Step**: Check the DOM Elements Check section to see which element is missing

### Issue: "AuthManager is not defined"
**Cause**: auth.js didn't load before app.js tried to use it

**Next Step**: Check script loading order and if auth.js is in S3

---

## Step-by-Step Troubleshooting

### 1. Open the diagnostic page
```
https://d3qlp39n4pyhxb.cloudfront.net/error-capture.html
```

### 2. Check Configuration Status
- If red: config.js didn't load
- If green: config.js loaded, check the config values

### 3. Check Script Loading Status
- If any red: that script didn't load
- If all green: all scripts loaded

### 4. Check Captured Errors
- If empty: no errors (but page is still blank?)
- If has errors: read the error message

### 5. Check Console Output
- Look for any error messages
- Look for any warning messages

### 6. Check DOM Elements
- If any red: that element doesn't exist
- If all green: all elements exist

### 7. Try Action Buttons
- Click "Check Config" to see actual values
- Click "Check AuthManager" to test auth
- Click "Load Main App" to test navigation

---

## What to Share With Me

When you open the diagnostic page, please take screenshots of:

1. **The entire page** - So I can see all sections
2. **Captured Errors section** - If there are any errors
3. **Console Output section** - If there are any messages
4. **Script Loading Status** - To see what loaded
5. **Configuration Status** - To see if config loaded

Or, if you can copy/paste:

1. **Any error messages** from the Captured Errors section
2. **Any console output** from the Console Output section
3. **Which scripts show as NOT loaded** in Script Loading Status
4. **Which DOM elements show as NOT FOUND** in DOM Elements Check

---

## Real-Time Monitoring

The diagnostic page automatically updates every 500ms, so:

1. Open the page
2. Wait a few seconds
3. Watch for errors appearing in real-time
4. The page will capture errors as they happen

---

## Next Steps

1. **Open**: https://d3qlp39n4pyhxb.cloudfront.net/error-capture.html
2. **Wait**: Let it load and monitor for errors
3. **Screenshot**: Take screenshots of what you see
4. **Share**: Send me the screenshots or error details

This will help us identify exactly what's causing the blank page issue.

---

## If Still Blank

If the diagnostic page itself is blank:

1. **Hard refresh**: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)
2. **Open DevTools**: F12
3. **Go to Console tab**
4. **Copy any red error messages**
5. **Share those errors with me**

---

## Browser Console (Alternative)

If the diagnostic page doesn't work, you can also:

1. Open: https://d3qlp39n4pyhxb.cloudfront.net
2. Press F12 to open DevTools
3. Go to Console tab
4. Look for red error messages
5. Copy/paste those errors

---

**Next Action**: Open https://d3qlp39n4pyhxb.cloudfront.net/error-capture.html and share what you see!
