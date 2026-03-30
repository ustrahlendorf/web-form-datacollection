// Configuration
// Use window.APP_CONFIG if available (set by config.js during build)
// Otherwise fall back to environment variables or defaults
const CONFIG = window.APP_CONFIG || {
    // These will be set from environment variables or CDK outputs
    API_ENDPOINT: process.env.REACT_APP_API_ENDPOINT || 'http://localhost:3000',
    COGNITO_DOMAIN: process.env.REACT_APP_COGNITO_DOMAIN || 'https://your-domain.auth.eu-central-1.amazoncognito.com',
    COGNITO_CLIENT_ID: process.env.REACT_APP_COGNITO_CLIENT_ID || 'your-client-id',
    COGNITO_REDIRECT_URI: process.env.REACT_APP_COGNITO_REDIRECT_URI || window.location.origin,
};

// State Management
const state = {
    isAuthenticated: false,
    currentPage: 'form',
    historyNextToken: null,
    settingsStatusPollTimer: null,
};

// Initialize AuthManager
let authManager;
let authenticatedFetch;
const SETTINGS_MAX_WINDOWS = 5;
const SETTINGS_TIME_PATTERN = /^([0-1][0-9]|2[0-3]):([0-5][0-9])$/;
// Accept canonical UUID shape regardless of specific version/variant bits.
const SETTINGS_UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const SETTINGS_DEFAULT_CONFIG = {
    schemaVersion: 1,
    frequentActiveWindows: [{ start: '08:00', stop: '18:00' }],
    maxRetries: 3,
    retryDelaySeconds: 300,
    userId: '',
};
const SETTINGS_DEPLOYMENT_POLL_INTERVAL_MS = 4000;
const SETTINGS_DEPLOYMENT_POLL_MAX_ATTEMPTS = 20;
const SETTINGS_DEPLOYMENT_TERMINAL_STATES = new Set([
    'COMPLETE',
    'COMPLETED',
    'ROLLED_BACK',
    'REVERTED',
]);
const SETTINGS_SCHEDULER_PLACEHOLDER = 'Not available';

// Initialize Application
document.addEventListener('DOMContentLoaded', async () => {
    // Create auth manager
    authManager = new AuthManager(CONFIG);
    authenticatedFetch = createAuthenticatedFetch(authManager);

    // Listen for auth state changes
    authManager.onAuthStateChanged((isAuthenticated) => {
        state.isAuthenticated = isAuthenticated;
        if (isAuthenticated) {
            showMainApp();
            loadRecentSubmissions();
        } else {
            showLoginPage();
        }
    });

    // Handle OAuth callback
    const handled = await authManager.handleAuthCallback();
    
    if (!handled) {
        // Check if already authenticated
        if (authManager.isAuthenticated()) {
            state.isAuthenticated = true;
            showMainApp();
            loadRecentSubmissions();
        } else {
            showLoginPage();
        }
    }

    setupEventListeners();

    // Navigate to page from initial hash (e.g. bookmark #live)
    const hash = (window.location.hash || '').replace(/^#/, '');
    if (hash && ['form', 'analyze', 'history', 'live', 'settings'].includes(hash)) {
        navigateToPage(hash);
    }
});

function setupEventListeners() {
    // Navigation
    document.querySelectorAll('.nav-link[data-page]').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const page = e.target.dataset.page;
            navigateToPage(page);
        });
    });

    // Logout
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    // Login
    const loginBtn = document.getElementById('login-btn');
    if (loginBtn) {
        loginBtn.addEventListener('click', initiateLogin);
    }

    // Form Submission
    const submissionForm = document.getElementById('submission-form');
    if (submissionForm) {
        submissionForm.addEventListener('submit', handleFormSubmit);
    }

    // Live page refresh
    const liveRefreshBtn = document.getElementById('live-refresh-btn');
    if (liveRefreshBtn) {
        liveRefreshBtn.addEventListener('click', () => loadLive());
    }

    // Live inject button (Submit Data page)
    const liveInjectBtn = document.getElementById('live-inject-btn');
    if (liveInjectBtn) {
        liveInjectBtn.addEventListener('click', () => injectLiveDataIntoForm());
    }

    // Settings page form
    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
        settingsForm.addEventListener('submit', handleSettingsSubmit);
    }

    const settingsAddWindowBtn = document.getElementById('settings-add-window-btn');
    if (settingsAddWindowBtn) {
        settingsAddWindowBtn.addEventListener('click', addSettingsWindowRow);
    }

    const settingsReloadBtn = document.getElementById('settings-reload-btn');
    if (settingsReloadBtn) {
        settingsReloadBtn.addEventListener('click', () => loadSettings());
    }
    const settingsStatusRefreshBtn = document.getElementById('settings-status-refresh-btn');
    if (settingsStatusRefreshBtn) {
        settingsStatusRefreshBtn.addEventListener('click', () => refreshSettingsDeploymentStatus());
    }

    const settingsWindows = document.getElementById('settings-active-windows');
    if (settingsWindows) {
        settingsWindows.addEventListener('click', (event) => {
            const removeBtn = event.target.closest('.settings-remove-window-btn');
            if (!removeBtn) {
                return;
            }
            const row = removeBtn.closest('.settings-window-row');
            if (!row) {
                return;
            }
            const rows = settingsWindows.querySelectorAll('.settings-window-row');
            if (rows.length <= 1) {
                const windowsError = document.getElementById('settings-active-windows-error');
                if (windowsError) {
                    windowsError.textContent = 'At least one active window is required.';
                }
                return;
            }
            row.remove();
            const windowsError = document.getElementById('settings-active-windows-error');
            if (windowsError) {
                windowsError.textContent = '';
            }
            updateSettingsWindowControls();
        });
        settingsWindows.addEventListener('input', () => {
            const windowsError = document.getElementById('settings-active-windows-error');
            if (windowsError) {
                windowsError.textContent = '';
            }
        });
    }

    initializeSettingsFormDefaults();
}

// Authentication Functions
function initiateLogin() {
    authManager.initiateLogin();
}

function logout() {
    authManager.logout();
}

// Page Navigation
function navigateToPage(page) {
    if (page !== 'settings') {
        clearSettingsDeploymentPolling();
    }
    state.currentPage = page;
    
    // Update active nav link
    document.querySelectorAll('.nav-link[data-page]').forEach(link => {
        link.classList.remove('active');
        if (link.dataset.page === page) {
            link.classList.add('active');
        }
    });

    // Show/hide pages
    document.querySelectorAll('.page').forEach(p => {
        p.classList.remove('active');
    });
    document.getElementById(`${page}-page`).classList.add('active');

    // Load page-specific data
    if (page === 'history') {
        loadHistory();
    } else if (page === 'analyze') {
        loadAnalyze();
    } else if (page === 'form') {
        initializeFormPage();
    } else if (page === 'live') {
        loadLive();
    } else if (page === 'settings') {
        loadSettings();
    }
}

function showMainApp() {
    document.getElementById('app').style.display = 'block';
    document.getElementById('login-section').style.display = 'none';
}

function showLoginPage() {
    document.getElementById('app').style.display = 'none';
    document.getElementById('login-section').style.display = 'flex';
}

// Form Page Functions
async function prefillFromLatestSubmission() {
    // Best-effort: if anything fails, keep defaults (0) and do not block the UI.
    try {
        // If auth isn't ready yet, we can't fetch the user's history.
        if (typeof authenticatedFetch !== 'function') {
            return;
        }

        const response = await authenticatedFetch(`${CONFIG.API_ENDPOINT}/history?limit=1`);
        if (!response || !response.ok) {
            return;
        }

        const data = await response.json();
        const submissions = (data && Array.isArray(data.submissions)) ? data.submissions : [];
        const latest = submissions.length > 0 && typeof submissions[0] === 'object' ? submissions[0] : null;
        if (!latest) {
            return;
        }

        const operatingHoursEl = document.getElementById('betriebsstunden');
        const startsEl = document.getElementById('starts');
        const consumptionEl = document.getElementById('verbrauch_qm');

        // Only overwrite if the user hasn't changed the defaults yet (prevents clobbering fast typing).
        if (operatingHoursEl && operatingHoursEl.value === '0' && latest.betriebsstunden !== undefined && latest.betriebsstunden !== null) {
            operatingHoursEl.value = String(parseInt(latest.betriebsstunden, 10));
        }
        if (startsEl && startsEl.value === '0' && latest.starts !== undefined && latest.starts !== null) {
            startsEl.value = String(parseInt(latest.starts, 10));
        }
        if (consumptionEl && consumptionEl.value === '0' && latest.verbrauch_qm !== undefined && latest.verbrauch_qm !== null) {
            // Display as stored (dot decimal) per requirement.
            consumptionEl.value = String(latest.verbrauch_qm);
        }
        const vorlaufEl = document.getElementById('vorlauf_temp');
        const aussentempEl = document.getElementById('aussentemp');
        if (vorlaufEl && vorlaufEl.value === '' && latest.vorlauf_temp !== undefined && latest.vorlauf_temp !== null) {
            vorlaufEl.value = Number(latest.vorlauf_temp).toFixed(1);
        }
        if (aussentempEl && aussentempEl.value === '' && latest.aussentemp !== undefined && latest.aussentemp !== null) {
            aussentempEl.value = Number(latest.aussentemp).toFixed(1);
        }
    } catch (error) {
        console.warn('Failed to prefill from latest submission:', error);
    }
}

async function initializeFormPage() {
    // Pre-populate form with current date and time
    const now = new Date();
    
    // Format date as dd.mm.yyyy
    const day = String(now.getDate()).padStart(2, '0');
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const year = now.getFullYear();
    document.getElementById('datum').value = `${day}.${month}.${year}`;
    
    // Format time as hh:mm
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('uhrzeit').value = `${hours}:${minutes}`;
    
    // Initialize numeric fields (immediate defaults to avoid blank UI)
    document.getElementById('betriebsstunden').value = '0';
    document.getElementById('starts').value = '0';
    document.getElementById('verbrauch_qm').value = '0';
    document.getElementById('vorlauf_temp').value = '';
    document.getElementById('aussentemp').value = '';
    
    // Clear any previous messages
    clearFormMessage();
    
    // Load recent submissions
    loadRecentSubmissions();

    // Prefill values from user's latest DynamoDB entry (best-effort).
    await prefillFromLatestSubmission();
}

function handleFormSubmit(e) {
    e.preventDefault();
    
    // Clear previous errors
    clearFormErrors();
    
    // Get form data
    const vorlaufVal = document.getElementById('vorlauf_temp').value.trim();
    const aussentempVal = document.getElementById('aussentemp').value.trim();
    const formData = {
        datum: document.getElementById('datum').value.trim(),
        uhrzeit: document.getElementById('uhrzeit').value.trim(),
        betriebsstunden: parseInt(document.getElementById('betriebsstunden').value),
        starts: parseInt(document.getElementById('starts').value),
        verbrauch_qm: parseFloat(document.getElementById('verbrauch_qm').value.replace(',', '.')),
        vorlauf_temp: vorlaufVal ? parseFloat(vorlaufVal.replace(',', '.')) : null,
        aussentemp: aussentempVal ? parseFloat(aussentempVal.replace(',', '.')) : null,
    };
    
    // Client-side validation
    const validationErrors = validateFormData(formData);
    if (validationErrors.length > 0) {
        displayFormErrors(validationErrors);
        return;
    }
    
    // Submit to API
    submitForm(formData);
}

function validateFormData(data) {
    const errors = [];
    
    // Validate date
    if (!isValidDate(data.datum)) {
        errors.push({ field: 'datum', message: 'Invalid date format. Expected dd.mm.yyyy' });
    }
    
    // Validate time
    if (!isValidTime(data.uhrzeit)) {
        errors.push({ field: 'uhrzeit', message: 'Invalid time format. Expected hh:mm' });
    }
    
    // Validate betriebsstunden
    if (isNaN(data.betriebsstunden) || data.betriebsstunden < 0) {
        errors.push({ field: 'betriebsstunden', message: 'Must be a non-negative integer' });
    }
    
    // Validate starts
    if (isNaN(data.starts) || data.starts < 0) {
        errors.push({ field: 'starts', message: 'Must be a non-negative integer' });
    }
    
    // Validate verbrauch_qm
    if (isNaN(data.verbrauch_qm) || data.verbrauch_qm <= 0 || data.verbrauch_qm >= 20.0) {
        errors.push({ field: 'verbrauch_qm', message: 'Must be between 0 and 20.0' });
    }

    // Validate vorlauf_temp (optional, -99.9 to 99.9 when provided)
    if (data.vorlauf_temp != null && (isNaN(data.vorlauf_temp) || data.vorlauf_temp < -99.9 || data.vorlauf_temp > 99.9)) {
        errors.push({ field: 'vorlauf_temp', message: 'Must be between -99.9 and 99.9 °C' });
    }

    // Validate aussentemp (optional, -99.9 to 99.9 when provided)
    if (data.aussentemp != null && (isNaN(data.aussentemp) || data.aussentemp < -99.9 || data.aussentemp > 99.9)) {
        errors.push({ field: 'aussentemp', message: 'Must be between -99.9 and 99.9 °C' });
    }
    
    return errors;
}

function isValidDate(dateStr) {
    const regex = /^(\d{2})\.(\d{2})\.(\d{4})$/;
    const match = dateStr.match(regex);
    
    if (!match) return false;
    
    const day = parseInt(match[1]);
    const month = parseInt(match[2]);
    const year = parseInt(match[3]);
    
    const date = new Date(year, month - 1, day);
    return date.getFullYear() === year && 
           date.getMonth() === month - 1 && 
           date.getDate() === day;
}

function isValidTime(timeStr) {
    const regex = /^(\d{2}):(\d{2})$/;
    const match = timeStr.match(regex);
    
    if (!match) return false;
    
    const hours = parseInt(match[1]);
    const minutes = parseInt(match[2]);
    
    return hours >= 0 && hours <= 23 && minutes >= 0 && minutes <= 59;
}

function displayFormErrors(errors) {
    errors.forEach(error => {
        const errorElement = document.getElementById(`${error.field}-error`);
        if (errorElement) {
            errorElement.textContent = error.message;
            document.getElementById(error.field).classList.add('error');
        }
    });
}

function clearFormErrors() {
    document.querySelectorAll('.error-message').forEach(el => {
        el.textContent = '';
    });
    document.querySelectorAll('input').forEach(el => {
        el.classList.remove('error');
    });
}

function clearFormMessage() {
    const messageEl = document.getElementById('form-message');
    messageEl.textContent = '';
    messageEl.classList.remove('success', 'error');
}

async function submitForm(data) {
    try {
        const response = await authenticatedFetch(`${CONFIG.API_ENDPOINT}/submit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data),
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showFormMessage('Submission successful!', 'success');
            // Reset form
            initializeFormPage();
            // Reload recent submissions
            loadRecentSubmissions();
        } else {
            if (result.details) {
                displayFormErrors(result.details);
            } else {
                showFormMessage(result.error || 'Submission failed', 'error');
            }
        }
    } catch (error) {
        console.error('Error submitting form:', error);
        showFormMessage('An error occurred. Please try again.', 'error');
    }
}

function showFormMessage(message, type) {
    const messageEl = document.getElementById('form-message');
    messageEl.textContent = message;
    messageEl.classList.remove('success', 'error');
    messageEl.classList.add(type);
}

// Settings Page Functions
function initializeSettingsFormDefaults() {
    const userId = (authManager && typeof authManager.getUserId === 'function' && authManager.getUserId())
        ? authManager.getUserId()
        : '';
    const config = {
        ...SETTINGS_DEFAULT_CONFIG,
        userId,
    };
    applyConfigToSettingsForm(config);
    clearSettingsErrors();
    clearSettingsMessage();
    renderSettingsDeploymentStatus(null, 'Status has not been loaded yet.');
    renderSettingsSchedulerMetadata(null);
}

function normalizeSettingsConfig(rawConfig, fallbackUserId = '') {
    const source = (rawConfig && typeof rawConfig === 'object') ? rawConfig : {};
    const schemaVersion = Number.isInteger(source.schemaVersion) ? source.schemaVersion : 1;
    const maxRetries = Number.isInteger(source.maxRetries) ? source.maxRetries : SETTINGS_DEFAULT_CONFIG.maxRetries;
    const retryDelaySeconds = Number.isInteger(source.retryDelaySeconds)
        ? source.retryDelaySeconds
        : SETTINGS_DEFAULT_CONFIG.retryDelaySeconds;
    const userId = (typeof source.userId === 'string' && source.userId.trim() !== '')
        ? source.userId.trim()
        : (fallbackUserId || '');
    const frequentActiveWindows = Array.isArray(source.frequentActiveWindows) && source.frequentActiveWindows.length > 0
        ? source.frequentActiveWindows
            .slice(0, SETTINGS_MAX_WINDOWS)
            .map((window) => ({
                start: (window && typeof window.start === 'string') ? window.start.trim() : '',
                stop: (window && typeof window.stop === 'string') ? window.stop.trim() : '',
            }))
        : SETTINGS_DEFAULT_CONFIG.frequentActiveWindows.map((window) => ({ ...window }));

    return {
        schemaVersion,
        frequentActiveWindows,
        maxRetries,
        retryDelaySeconds,
        userId,
    };
}

function parseTimeMinutes(value) {
    const match = SETTINGS_TIME_PATTERN.exec(String(value || '').trim());
    if (!match) {
        return null;
    }
    const hours = parseInt(match[1], 10);
    const minutes = parseInt(match[2], 10);
    return (hours * 60) + minutes;
}

function validateSettingsPayload(payload) {
    const errors = [];
    if (!payload || typeof payload !== 'object') {
        return [{ field: 'settings-message', message: 'Settings payload is invalid.' }];
    }

    if (payload.schemaVersion !== 1) {
        errors.push({ field: 'settings-schema-version-error', message: 'Schema version must be 1.' });
    }

    if (!Number.isInteger(payload.maxRetries) || payload.maxRetries < 0 || payload.maxRetries > 20) {
        errors.push({ field: 'settings-max-retries-error', message: 'Max retries must be an integer between 0 and 20.' });
    }

    if (!Number.isInteger(payload.retryDelaySeconds) || payload.retryDelaySeconds < 1 || payload.retryDelaySeconds > 3600) {
        errors.push({ field: 'settings-retry-delay-seconds-error', message: 'Retry delay must be an integer between 1 and 3600.' });
    }

    if (typeof payload.userId !== 'string' || payload.userId.trim() === '') {
        errors.push({ field: 'settings-user-id-error', message: 'User ID is required.' });
    } else if (!SETTINGS_UUID_PATTERN.test(payload.userId.trim())) {
        errors.push({ field: 'settings-user-id-error', message: 'User ID must be a valid UUID.' });
    }

    if (!Array.isArray(payload.frequentActiveWindows)) {
        errors.push({ field: 'settings-active-windows-error', message: 'Frequent active windows must be an array.' });
        return errors;
    }
    if (payload.frequentActiveWindows.length < 1) {
        errors.push({ field: 'settings-active-windows-error', message: 'At least one active window is required.' });
    }
    if (payload.frequentActiveWindows.length > SETTINGS_MAX_WINDOWS) {
        errors.push({ field: 'settings-active-windows-error', message: 'No more than 5 active windows are allowed.' });
    }

    payload.frequentActiveWindows.forEach((window, index) => {
        const start = (window && typeof window.start === 'string') ? window.start.trim() : '';
        const stop = (window && typeof window.stop === 'string') ? window.stop.trim() : '';
        const rowStartSelector = `#settings-active-windows .settings-window-row:nth-child(${index + 1}) .settings-window-start`;
        const rowStopSelector = `#settings-active-windows .settings-window-row:nth-child(${index + 1}) .settings-window-stop`;
        if (!SETTINGS_TIME_PATTERN.test(start) || !SETTINGS_TIME_PATTERN.test(stop)) {
            errors.push({
                field: 'settings-active-windows-error',
                message: `Window ${index + 1}: start/stop must use HH:MM format.`,
                selectors: [rowStartSelector, rowStopSelector],
            });
            return;
        }
        const startMinutes = parseTimeMinutes(start);
        const stopMinutes = parseTimeMinutes(stop);
        if (startMinutes === null || stopMinutes === null || startMinutes >= stopMinutes) {
            errors.push({
                field: 'settings-active-windows-error',
                message: `Window ${index + 1}: start must be earlier than stop.`,
                selectors: [rowStartSelector, rowStopSelector],
            });
        }
    });

    return errors;
}

function clearSettingsErrors() {
    document.querySelectorAll('#settings-page .error-message').forEach((el) => {
        el.textContent = '';
    });
    document.querySelectorAll('#settings-page input').forEach((el) => {
        el.classList.remove('error');
    });
}

function displaySettingsErrors(errors) {
    clearSettingsErrors();
    errors.forEach((error) => {
        const errorEl = document.getElementById(error.field);
        if (errorEl) {
            errorEl.textContent = error.message;
        }
        if (Array.isArray(error.selectors)) {
            error.selectors.forEach((selector) => {
                document.querySelectorAll(selector).forEach((el) => {
                    el.classList.add('error');
                });
            });
        }
    });
}

function clearSettingsMessage() {
    const messageEl = document.getElementById('settings-message');
    if (!messageEl) {
        return;
    }
    messageEl.textContent = '';
    messageEl.classList.remove('success', 'error');
}

function showSettingsMessage(message, type) {
    const messageEl = document.getElementById('settings-message');
    if (!messageEl) {
        return;
    }
    messageEl.textContent = message;
    messageEl.classList.remove('success', 'error');
    messageEl.classList.add(type);
}

function clearSettingsDeploymentPolling() {
    if (state.settingsStatusPollTimer) {
        clearTimeout(state.settingsStatusPollTimer);
        state.settingsStatusPollTimer = null;
    }
}

function getSettingsDeploymentStateClass(stateValue) {
    const normalized = String(stateValue || '').toUpperCase();
    if (SETTINGS_DEPLOYMENT_TERMINAL_STATES.has(normalized)) {
        return 'settings-deployment-state-success';
    }
    if (normalized.includes('ROLLBACK') || normalized.includes('FAILED') || normalized.includes('REVERT')) {
        return 'settings-deployment-state-failed';
    }
    if (normalized === '') {
        return '';
    }
    return 'settings-deployment-state-pending';
}

function formatSettingsDateTime(value) {
    if (!value || typeof value !== 'string') {
        return '-';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return value;
    }
    return formatTimestamp(parsed.toISOString());
}

function renderSettingsDeploymentStatus(deployment, note = '') {
    const stateEl = document.getElementById('settings-deployment-state');
    const numberEl = document.getElementById('settings-deployment-number');
    const versionEl = document.getElementById('settings-deployment-config-version');
    const startedEl = document.getElementById('settings-deployment-started-at');
    const completedEl = document.getElementById('settings-deployment-completed-at');
    const progressEl = document.getElementById('settings-deployment-progress');
    const noteEl = document.getElementById('settings-deployment-note');

    const stateText = deployment && deployment.state ? String(deployment.state) : 'Unknown';
    if (stateEl) {
        stateEl.textContent = stateText;
        stateEl.classList.remove(
            'settings-deployment-state-success',
            'settings-deployment-state-pending',
            'settings-deployment-state-failed'
        );
        const stateClass = getSettingsDeploymentStateClass(stateText);
        if (stateClass) {
            stateEl.classList.add(stateClass);
        }
    }
    if (numberEl) {
        numberEl.textContent = deployment && deployment.deploymentNumber != null
            ? String(deployment.deploymentNumber)
            : '-';
    }
    if (versionEl) {
        versionEl.textContent = deployment && deployment.configurationVersion
            ? String(deployment.configurationVersion)
            : '-';
    }
    if (startedEl) {
        startedEl.textContent = formatSettingsDateTime(deployment && deployment.startedAt);
    }
    if (completedEl) {
        completedEl.textContent = formatSettingsDateTime(deployment && deployment.completedAt);
    }
    if (progressEl) {
        progressEl.textContent = deployment && Number.isFinite(Number(deployment.percentageComplete))
            ? `${Math.round(Number(deployment.percentageComplete))}%`
            : '-';
    }
    if (noteEl) {
        noteEl.textContent = note || '';
    }
}

function normalizeSettingsSchedulerMetadata(rawScheduler) {
    if (!rawScheduler || typeof rawScheduler !== 'object') {
        return {
            available: false,
            source: 'eventbridge',
            frequentScheduleCron: null,
            frequentScheduleExpression: null,
            frequentIntervalMinutes: null,
            frequentRuleName: null,
        };
    }

    return {
        available: rawScheduler.available === true,
        source: (typeof rawScheduler.source === 'string' && rawScheduler.source.trim() !== '')
            ? rawScheduler.source.trim()
            : 'eventbridge',
        frequentScheduleCron: (typeof rawScheduler.frequentScheduleCron === 'string' && rawScheduler.frequentScheduleCron.trim() !== '')
            ? rawScheduler.frequentScheduleCron.trim()
            : null,
        frequentScheduleExpression: (typeof rawScheduler.frequentScheduleExpression === 'string' && rawScheduler.frequentScheduleExpression.trim() !== '')
            ? rawScheduler.frequentScheduleExpression.trim()
            : null,
        frequentIntervalMinutes: Number.isFinite(Number(rawScheduler.frequentIntervalMinutes))
            ? Math.max(0, Math.round(Number(rawScheduler.frequentIntervalMinutes)))
            : null,
        frequentRuleName: (typeof rawScheduler.frequentRuleName === 'string' && rawScheduler.frequentRuleName.trim() !== '')
            ? rawScheduler.frequentRuleName.trim()
            : null,
    };
}

function renderSettingsSchedulerMetadata(rawScheduler) {
    const cronEl = document.getElementById('settings-scheduler-frequent-cron');
    const intervalEl = document.getElementById('settings-scheduler-frequent-interval');
    const noteEl = document.getElementById('settings-scheduler-note');
    const scheduler = normalizeSettingsSchedulerMetadata(rawScheduler);

    const cronText = scheduler.frequentScheduleCron || scheduler.frequentScheduleExpression || SETTINGS_SCHEDULER_PLACEHOLDER;
    const intervalText = scheduler.frequentIntervalMinutes !== null
        ? `${scheduler.frequentIntervalMinutes} minute${scheduler.frequentIntervalMinutes === 1 ? '' : 's'}`
        : SETTINGS_SCHEDULER_PLACEHOLDER;
    const availabilityText = scheduler.available ? 'available' : 'unavailable';
    const sourceText = scheduler.source || 'eventbridge';
    const ruleText = scheduler.frequentRuleName ? `, rule ${scheduler.frequentRuleName}` : '';

    if (cronEl) {
        cronEl.textContent = cronText;
    }
    if (intervalEl) {
        intervalEl.textContent = intervalText;
    }
    if (noteEl) {
        noteEl.textContent = `Source: ${sourceText} (${availabilityText}${ruleText})`;
    }
}

function isSettingsDeploymentTerminal(stateValue) {
    return SETTINGS_DEPLOYMENT_TERMINAL_STATES.has(String(stateValue || '').toUpperCase());
}

async function fetchSettingsDeploymentStatus(deploymentNumber = null) {
    let url = `${CONFIG.API_ENDPOINT}/config/auto-retrieval/deployment-status`;
    if (deploymentNumber != null && deploymentNumber !== '') {
        url += `?deploymentNumber=${encodeURIComponent(String(deploymentNumber))}`;
    }
    const response = await authenticatedFetch(url);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(result.error || 'Failed to load deployment status');
    }
    return result.deployment || null;
}

async function refreshSettingsDeploymentStatus(deploymentNumber = null, options = {}) {
    const { silent = false } = options;
    try {
        const deployment = await fetchSettingsDeploymentStatus(deploymentNumber);
        if (!deployment) {
            renderSettingsDeploymentStatus(null, 'No deployment found yet.');
            return null;
        }
        const stateValue = String(deployment.state || 'UNKNOWN');
        renderSettingsDeploymentStatus(deployment, `Last update: state is ${stateValue}.`);
        return deployment;
    } catch (error) {
        console.error('Error loading deployment status:', error);
        renderSettingsDeploymentStatus(null, 'Failed to load deployment status.');
        if (!silent) {
            showSettingsMessage(error.message || 'Failed to load deployment status.', 'error');
        }
        return null;
    }
}

function startSettingsDeploymentPolling(deploymentNumber) {
    clearSettingsDeploymentPolling();
    let attempts = 0;

    const pollOnce = async () => {
        attempts += 1;
        const deployment = await refreshSettingsDeploymentStatus(deploymentNumber, { silent: true });
        if (!deployment) {
            if (attempts >= SETTINGS_DEPLOYMENT_POLL_MAX_ATTEMPTS) {
                renderSettingsDeploymentStatus(null, 'Stopped polling because no deployment status was returned.');
                clearSettingsDeploymentPolling();
                return;
            }
            state.settingsStatusPollTimer = setTimeout(pollOnce, SETTINGS_DEPLOYMENT_POLL_INTERVAL_MS);
            return;
        }

        if (isSettingsDeploymentTerminal(deployment.state)) {
            renderSettingsDeploymentStatus(
                deployment,
                `Deployment reached terminal state ${deployment.state}.`
            );
            clearSettingsDeploymentPolling();
            return;
        }

        if (attempts >= SETTINGS_DEPLOYMENT_POLL_MAX_ATTEMPTS) {
            renderSettingsDeploymentStatus(
                deployment,
                `Polling stopped after ${SETTINGS_DEPLOYMENT_POLL_MAX_ATTEMPTS} checks. Use Refresh for latest status.`
            );
            clearSettingsDeploymentPolling();
            return;
        }
        state.settingsStatusPollTimer = setTimeout(pollOnce, SETTINGS_DEPLOYMENT_POLL_INTERVAL_MS);
    };

    void pollOnce();
}

function updateSettingsWindowControls() {
    const windowsContainer = document.getElementById('settings-active-windows');
    const addBtn = document.getElementById('settings-add-window-btn');
    if (!windowsContainer) {
        return;
    }
    const rows = windowsContainer.querySelectorAll('.settings-window-row');
    const disableAdd = rows.length >= SETTINGS_MAX_WINDOWS;
    if (addBtn) {
        addBtn.disabled = disableAdd;
    }
    rows.forEach((row) => {
        const removeBtn = row.querySelector('.settings-remove-window-btn');
        if (removeBtn) {
            removeBtn.disabled = rows.length <= 1;
        }
    });
}

function createSettingsWindowRow(windowData = { start: '', stop: '' }) {
    const row = document.createElement('div');
    row.className = 'settings-window-row';
    row.innerHTML = `
        <input
            type="text"
            class="settings-window-start"
            placeholder="HH:MM"
            value="${String(windowData.start || '').trim()}"
            required
        >
        <span class="settings-window-separator">to</span>
        <input
            type="text"
            class="settings-window-stop"
            placeholder="HH:MM"
            value="${String(windowData.stop || '').trim()}"
            required
        >
        <button type="button" class="btn btn-secondary settings-remove-window-btn">Remove</button>
    `;
    return row;
}

function renderSettingsWindows(windows) {
    const windowsContainer = document.getElementById('settings-active-windows');
    if (!windowsContainer) {
        return;
    }
    windowsContainer.innerHTML = '';
    windows.forEach((windowData) => {
        windowsContainer.appendChild(createSettingsWindowRow(windowData));
    });
    updateSettingsWindowControls();
}

function addSettingsWindowRow() {
    const windowsContainer = document.getElementById('settings-active-windows');
    if (!windowsContainer) {
        return;
    }
    const rows = windowsContainer.querySelectorAll('.settings-window-row');
    if (rows.length >= SETTINGS_MAX_WINDOWS) {
        const windowsError = document.getElementById('settings-active-windows-error');
        if (windowsError) {
            windowsError.textContent = 'No more than 5 active windows are allowed.';
        }
        return;
    }
    windowsContainer.appendChild(createSettingsWindowRow({ start: '', stop: '' }));
    const windowsError = document.getElementById('settings-active-windows-error');
    if (windowsError) {
        windowsError.textContent = '';
    }
    updateSettingsWindowControls();
}

function applyConfigToSettingsForm(config) {
    const normalized = normalizeSettingsConfig(
        config,
        (authManager && typeof authManager.getUserId === 'function') ? authManager.getUserId() : ''
    );

    const schemaVersionEl = document.getElementById('settings-schema-version');
    const maxRetriesEl = document.getElementById('settings-max-retries');
    const retryDelayEl = document.getElementById('settings-retry-delay-seconds');
    const userIdEl = document.getElementById('settings-user-id');

    if (schemaVersionEl) schemaVersionEl.value = String(normalized.schemaVersion);
    if (maxRetriesEl) maxRetriesEl.value = String(normalized.maxRetries);
    if (retryDelayEl) retryDelayEl.value = String(normalized.retryDelaySeconds);
    if (userIdEl) userIdEl.value = normalized.userId;
    renderSettingsWindows(normalized.frequentActiveWindows);
}

function buildSettingsPayloadFromForm() {
    const schemaVersion = parseInt(document.getElementById('settings-schema-version').value, 10);
    const maxRetries = parseInt(document.getElementById('settings-max-retries').value, 10);
    const retryDelaySeconds = parseInt(document.getElementById('settings-retry-delay-seconds').value, 10);
    const userId = (document.getElementById('settings-user-id').value || '').trim();
    const windows = Array.from(document.querySelectorAll('#settings-active-windows .settings-window-row')).map((row) => ({
        start: ((row.querySelector('.settings-window-start') || {}).value || '').trim(),
        stop: ((row.querySelector('.settings-window-stop') || {}).value || '').trim(),
    }));

    return {
        schemaVersion,
        frequentActiveWindows: windows,
        maxRetries,
        retryDelaySeconds,
        userId,
    };
}

async function loadSettings() {
    clearSettingsDeploymentPolling();
    clearSettingsErrors();
    clearSettingsMessage();
    showSettingsMessage('Loading settings...', 'success');

    try {
        const response = await authenticatedFetch(`${CONFIG.API_ENDPOINT}/config/auto-retrieval`);
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.error || 'Failed to load settings');
        }

        applyConfigToSettingsForm(result.config || null);
        renderSettingsSchedulerMetadata(result.scheduler || null);
        const labelText = (result.versionLabel && String(result.versionLabel).trim() !== '')
            ? ` (version ${result.versionLabel})`
            : '';
        await refreshSettingsDeploymentStatus(null, { silent: true });
        showSettingsMessage(`Settings loaded successfully${labelText}.`, 'success');
    } catch (error) {
        console.error('Error loading settings:', error);
        renderSettingsSchedulerMetadata(null);
        showSettingsMessage(error.message || 'Failed to load settings.', 'error');
    }
}

async function handleSettingsSubmit(event) {
    event.preventDefault();
    clearSettingsDeploymentPolling();
    clearSettingsErrors();
    clearSettingsMessage();

    const payload = buildSettingsPayloadFromForm();
    const validationErrors = validateSettingsPayload(payload);
    if (validationErrors.length > 0) {
        displaySettingsErrors(validationErrors);
        showSettingsMessage('Please correct validation errors before saving.', 'error');
        return;
    }

    try {
        const response = await authenticatedFetch(`${CONFIG.API_ENDPOINT}/config/auto-retrieval`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        });
        const result = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(result.error || 'Failed to save settings');
        }

        const details = [
            `Config version ${result.versionNumber}`,
            `deployment ${result.deploymentNumber}`,
            `state ${result.state || 'UNKNOWN'}`,
        ].join(', ');
        showSettingsMessage(`Settings saved. Deployment started: ${details}.`, 'success');
        startSettingsDeploymentPolling(result.deploymentNumber);
    } catch (error) {
        console.error('Error saving settings:', error);
        showSettingsMessage(error.message || 'Failed to save settings.', 'error');
    }
}

// Recent Submissions Functions
async function loadRecentSubmissions() {
    try {
        const response = await authenticatedFetch(`${CONFIG.API_ENDPOINT}/recent`);
        
        if (!response.ok) {
            throw new Error('Failed to load recent submissions');
        }
        
        const data = await response.json();
        displayRecentSubmissions(data.submissions || []);
    } catch (error) {
        console.error('Error loading recent submissions:', error);
        document.getElementById('recent-submissions').innerHTML = 
            '<p class="empty-state">Failed to load recent submissions</p>';
    }
}

function displayRecentSubmissions(submissions) {
    const container = document.getElementById('recent-submissions');
    
    if (submissions.length === 0) {
        container.innerHTML = '<p class="empty-state">No recent submissions</p>';
        return;
    }
    
    container.innerHTML = submissions.map(submission => `
        <div class="recent-item">
            <div class="recent-item-header">
                <span>${submission.datum} ${submission.uhrzeit} (UTC)</span>
                <span class="recent-item-date">${formatTimestamp(submission.timestamp_utc)} (local)</span>
            </div>
            <div class="recent-item-data">
                <div class="recent-item-field">
                    <span class="recent-item-label">Operating Hours:</span>
                    <span class="recent-item-value">${submission.betriebsstunden} <span class="delta">${formatDelta(getDeltaValue(submission, 'delta_betriebsstunden', 'betriebsstunden_delta'), { kind: 'int' })}</span></span>
                </div>
                <div class="recent-item-field">
                    <span class="recent-item-label">Starts:</span>
                    <span class="recent-item-value">${submission.starts} <span class="delta">${formatDelta(getDeltaValue(submission, 'delta_starts', 'starts_delta'), { kind: 'int' })}</span></span>
                </div>
                <div class="recent-item-field">
                    <span class="recent-item-label">Consumption:</span>
                    <span class="recent-item-value">${submission.verbrauch_qm} m³ <span class="delta">${formatDelta(getDeltaValue(submission, 'delta_verbrauch_qm', 'verbrauch_qm_delta'), { kind: 'decimal', decimals: 2 })}</span></span>
                </div>
                <div class="recent-item-field">
                    <span class="recent-item-label">Supply Temp:</span>
                    <span class="recent-item-value">${submission.vorlauf_temp != null ? Number(submission.vorlauf_temp).toFixed(1) + ' °C' : '—'}</span>
                </div>
                <div class="recent-item-field">
                    <span class="recent-item-label">Outside-Temp. Sensor:</span>
                    <span class="recent-item-value">${submission.aussentemp != null ? Number(submission.aussentemp).toFixed(1) + ' °C' : '—'}</span>
                </div>
            </div>
        </div>
    `).join('');
}

// History Page Functions
async function loadHistory(nextToken = null) {
    try {
        let url = `${CONFIG.API_ENDPOINT}/history?limit=20`;
        if (nextToken) {
            url += `&next_token=${encodeURIComponent(nextToken)}`;
        }
        
        const response = await authenticatedFetch(url);
        
        if (!response.ok) {
            throw new Error('Failed to load history');
        }
        
        const data = await response.json();
        displayHistory(data.submissions || []);
        
        // Update pagination
        state.historyNextToken = data.next_token || null;
        updatePaginationControls(!!data.next_token);
    } catch (error) {
        console.error('Error loading history:', error);
        document.getElementById('history-content').innerHTML = 
            '<p class="empty-state">Failed to load history</p>';
    }
}

function displayHistory(submissions) {
    const container = document.getElementById('history-content');
    
    if (submissions.length === 0) {
        container.innerHTML = '<p class="empty-state">No submissions found</p>';
        return;
    }
    
    const table = `
        <table class="history-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Time (UTC)</th>
                    <th>Operating Hours</th>
                    <th>Δ Operating Hours</th>
                    <th>Starts</th>
                    <th>Δ Starts</th>
                    <th>Consumption (m³)</th>
                    <th>Δ Consumption (m³)</th>
                    <th>Supply Temp (°C)</th>
                    <th>Outside-Temp. Sensor (°C)</th>
                    <th>Submitted (Local)</th>
                </tr>
            </thead>
            <tbody>
                ${submissions.map(submission => `
                    <tr>
                        <td>${submission.datum}</td>
                        <td>${submission.uhrzeit}</td>
                        <td>${submission.betriebsstunden}</td>
                        <td>${formatDelta(getDeltaValue(submission, 'delta_betriebsstunden', 'betriebsstunden_delta'), { kind: 'int' })}</td>
                        <td>${submission.starts}</td>
                        <td>${formatDelta(getDeltaValue(submission, 'delta_starts', 'starts_delta'), { kind: 'int' })}</td>
                        <td>${submission.verbrauch_qm}</td>
                        <td>${formatDelta(getDeltaValue(submission, 'delta_verbrauch_qm', 'verbrauch_qm_delta'), { kind: 'decimal', decimals: 2 })}</td>
                        <td>${submission.vorlauf_temp != null ? Number(submission.vorlauf_temp).toFixed(1) : '—'}</td>
                        <td>${submission.aussentemp != null ? Number(submission.aussentemp).toFixed(1) : '—'}</td>
                        <td>${formatTimestamp(submission.timestamp_utc)}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
    
    container.innerHTML = table;
}

function updatePaginationControls(hasNextPage) {
    const controls = document.getElementById('pagination-controls');
    if (!controls) {
        return;
    }
    
    if (!hasNextPage && !state.historyNextToken) {
        controls.style.display = 'none';
        return;
    }
    
    controls.style.display = 'flex';
    
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    
    if (prevBtn) {
        prevBtn.disabled = !state.historyPreviousToken;
        prevBtn.addEventListener('click', () => {
            if (state.historyPreviousToken) {
                loadHistory(state.historyPreviousToken);
            }
        });
    }
    
    if (nextBtn) {
        nextBtn.disabled = !hasNextPage;
        nextBtn.addEventListener('click', () => {
            if (state.historyNextToken) {
                loadHistory(state.historyNextToken);
            }
        });
    }
}

// Analyze (YTD Statistics) Functions
function parseGermanDateToUtcMidnight(dateStr) {
    if (typeof dateStr !== 'string') {
        return null;
    }
    const trimmed = dateStr.trim();
    const match = trimmed.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
    if (!match) {
        return null;
    }
    const day = parseInt(match[1], 10);
    const month = parseInt(match[2], 10);
    const year = parseInt(match[3], 10);
    if (!Number.isFinite(day) || !Number.isFinite(month) || !Number.isFinite(year)) {
        return null;
    }
    // Use UTC midnight to avoid DST/timezone skew when computing day deltas.
    const d = new Date(Date.UTC(year, month - 1, day));
    // Validate round-trip
    if (d.getUTCFullYear() !== year || d.getUTCMonth() !== (month - 1) || d.getUTCDate() !== day) {
        return null;
    }
    return d;
}

function getSubmissionUtcDay(submission) {
    if (!submission || typeof submission !== 'object') {
        return null;
    }

    // Prefer the explicit dd.mm.yyyy field.
    const fromDatum = parseGermanDateToUtcMidnight(submission.datum);
    if (fromDatum) {
        return fromDatum;
    }

    // Fallback to timestamp_utc (ISO string).
    if (typeof submission.timestamp_utc === 'string' && submission.timestamp_utc.trim() !== '') {
        const ts = new Date(submission.timestamp_utc);
        if (!Number.isNaN(ts.getTime())) {
            return new Date(Date.UTC(ts.getUTCFullYear(), ts.getUTCMonth(), ts.getUTCDate()));
        }
    }

    return null;
}

function compareSubmissionsByDay(a, b) {
    const da = getSubmissionUtcDay(a);
    const db = getSubmissionUtcDay(b);
    if (!da && !db) return 0;
    if (!da) return 1;
    if (!db) return -1;
    return da.getTime() - db.getTime();
}

function computeInclusiveDays(earliestSubmission, latestSubmission) {
    const start = getSubmissionUtcDay(earliestSubmission);
    const end = getSubmissionUtcDay(latestSubmission);
    if (!start || !end) {
        return null;
    }
    const diffDays = Math.round((end.getTime() - start.getTime()) / 86400000);
    return diffDays + 1;
}

function sumConsumptionAcrossSubmissions(submissions) {
    if (!Array.isArray(submissions) || submissions.length === 0) {
        return null;
    }

    let sum = 0;
    let seenAny = false;

    for (const s of submissions) {
        const n = normalizeNumber(s && s.verbrauch_qm);
        if (n === null) continue;
        sum += n;
        seenAny = true;
    }
    return seenAny ? sum : null;
}

function computeYtdTotals(earliestSubmission, latestSubmission, submissionsInRange = null) {
    if (!earliestSubmission || !latestSubmission) {
        return null;
    }

    const earliestHours = normalizeNumber(earliestSubmission.betriebsstunden);
    const latestHours = normalizeNumber(latestSubmission.betriebsstunden);
    const earliestStarts = normalizeNumber(earliestSubmission.starts);
    const latestStarts = normalizeNumber(latestSubmission.starts);

    const totalOperatingHours = (earliestHours === null || latestHours === null) ? null : (latestHours - earliestHours);
    const totalStarts = (earliestStarts === null || latestStarts === null) ? null : (latestStarts - earliestStarts);
    // Consumption is per-entry (not cumulative), so total consumption is the SUM from earliest through latest.
    const totalConsumption = sumConsumptionAcrossSubmissions(submissionsInRange);

    const days = computeInclusiveDays(earliestSubmission, latestSubmission);
    return {
        earliest: earliestSubmission,
        latest: latestSubmission,
        totalOperatingHours,
        totalStarts,
        totalConsumption,
        days,
    };
}

/**
 * ISO-8601 week (Monday first; week 1 is the week with the year's first Thursday).
 * @param {Date} utcMidnight - calendar day at UTC midnight
 * @returns {{ isoWeekYear: number, isoWeek: number } | null}
 */
function getIsoWeekPartsFromUtcDate(utcMidnight) {
    if (!utcMidnight || !(utcMidnight instanceof Date) || Number.isNaN(utcMidnight.getTime())) {
        return null;
    }
    const d = new Date(utcMidnight.getTime());
    const dow = d.getUTCDay();
    const isoDow = dow === 0 ? 7 : dow;
    d.setUTCDate(d.getUTCDate() + 4 - isoDow);
    const isoWeekYear = d.getUTCFullYear();
    const yearStart = new Date(Date.UTC(isoWeekYear, 0, 1));
    const weekNo = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
    return { isoWeekYear, isoWeek: weekNo };
}

/** Today’s calendar day in UTC, as ISO week (same basis as submission days). */
function getCurrentUtcIsoWeekParts() {
    const now = new Date();
    const utcMidnight = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    return getIsoWeekPartsFromUtcDate(utcMidnight);
}

function compareIsoWeekOrder(yearA, weekA, yearB, weekB) {
    if (yearA !== yearB) {
        return yearA - yearB;
    }
    return weekA - weekB;
}

/**
 * Monday 00:00 UTC of the given ISO week (ISO-8601; week 1 contains Jan 4 of isoWeekYear).
 * @param {number} isoWeekYear
 * @param {number} isoWeek
 * @returns {Date | null}
 */
function getMondayUtcOfIsoWeek(isoWeekYear, isoWeek) {
    if (!Number.isFinite(isoWeekYear) || !Number.isFinite(isoWeek)) {
        return null;
    }
    const jan4 = new Date(Date.UTC(isoWeekYear, 0, 4));
    const dow = jan4.getUTCDay();
    const isoDow = dow === 0 ? 7 : dow;
    const monday = new Date(jan4);
    monday.setUTCDate(jan4.getUTCDate() - (isoDow - 1) + (isoWeek - 1) * 7);
    return monday;
}

/**
 * @param {number} isoWeekYear
 * @param {number} isoWeek
 * @returns {string} e.g. "29.12-04.01" (Monday–Sunday, dd.mm, no calendar year)
 */
function formatIsoWeekDdMmRange(isoWeekYear, isoWeek) {
    const monday = getMondayUtcOfIsoWeek(isoWeekYear, isoWeek);
    if (!monday) {
        return '';
    }
    const sunday = new Date(monday.getTime());
    sunday.setUTCDate(monday.getUTCDate() + 6);
    const fmt = (d) => `${String(d.getUTCDate()).padStart(2, '0')}.${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
    return `${fmt(monday)}-${fmt(sunday)}`;
}

/**
 * Chained delta vs. previous submission in sort order (temperatures have no stored deltas).
 * First row contributes 0; missing predecessor or missing value yields no contribution.
 * @param {object} submission
 * @param {object | null} prevSubmission
 * @param {string} key - e.g. vorlauf_temp, aussentemp
 * @returns {number | null} null = skip adding to weekly sum
 */
function chainedReadingDelta(submission, prevSubmission, key) {
    if (!submission || typeof submission !== 'object') {
        return null;
    }
    if (!prevSubmission) {
        return 0;
    }
    const c = normalizeNumber(submission[key]);
    const p = normalizeNumber(prevSubmission[key]);
    if (c === null || p === null) {
        return null;
    }
    return c - p;
}

/**
 * Per-ISO-week aggregates for consumption-related stats (same rules as peak/min week cards).
 * @param {object[]} sortedSubmissions
 * @returns {Array<{ isoWeekYear: number, isoWeek: number, sumDeltaBetriebsstunden: number, sumDeltaStarts: number, sumVerbrauchQm: number, sumDeltaVorlauf: number, sumDeltaAussen: number, vorlaufDeltaCount: number, aussenDeltaCount: number }>}
 */
function buildWeeklyConsumptionBuckets(sortedSubmissions) {
    if (!Array.isArray(sortedSubmissions) || sortedSubmissions.length === 0) {
        return [];
    }

    const map = new Map();
    for (let i = 0; i < sortedSubmissions.length; i++) {
        const submission = sortedSubmissions[i];
        const prevSubmission = i > 0 ? sortedSubmissions[i - 1] : null;
        const day = getSubmissionUtcDay(submission);
        if (!day) {
            continue;
        }

        const parts = getIsoWeekPartsFromUtcDate(day);
        if (!parts) {
            continue;
        }

        const key = `${parts.isoWeekYear}:${parts.isoWeek}`;
        let bucket = map.get(key);
        if (!bucket) {
            bucket = {
                isoWeekYear: parts.isoWeekYear,
                isoWeek: parts.isoWeek,
                sumDeltaBetriebsstunden: 0,
                sumDeltaStarts: 0,
                sumVerbrauchQm: 0,
                sumDeltaVorlauf: 0,
                sumDeltaAussen: 0,
                vorlaufDeltaCount: 0,
                aussenDeltaCount: 0,
            };
            map.set(key, bucket);
        }

        const dBh = normalizeNumber(getDeltaValue(submission, 'delta_betriebsstunden', 'betriebsstunden_delta'));
        if (dBh !== null) {
            bucket.sumDeltaBetriebsstunden += dBh;
        }
        const dSt = normalizeNumber(getDeltaValue(submission, 'delta_starts', 'starts_delta'));
        if (dSt !== null) {
            bucket.sumDeltaStarts += dSt;
        }
        const v = normalizeNumber(submission && submission.verbrauch_qm);
        if (v !== null) {
            bucket.sumVerbrauchQm += v;
        }

        const dVl = chainedReadingDelta(submission, prevSubmission, 'vorlauf_temp');
        if (dVl !== null) {
            bucket.sumDeltaVorlauf += dVl;
            bucket.vorlaufDeltaCount += 1;
        }
        const dAu = chainedReadingDelta(submission, prevSubmission, 'aussentemp');
        if (dAu !== null) {
            bucket.sumDeltaAussen += dAu;
            bucket.aussenDeltaCount += 1;
        }
    }

    return Array.from(map.values());
}

/**
 * @param {object[]} aggregates - weekly buckets from buildWeeklyConsumptionBuckets
 * @param {'max'|'min'} mode
 * @returns {object | null}
 */
function pickWeeklyBucketByConsumptionExtreme(aggregates, mode) {
    if (!aggregates.length) {
        return null;
    }
    let bestAgg = null;
    for (const agg of aggregates) {
        if (bestAgg === null) {
            bestAgg = agg;
            continue;
        }
        const sum = agg.sumVerbrauchQm;
        if (mode === 'max') {
            const betterSum = sum > bestAgg.sumVerbrauchQm;
            const tieEarlier =
                sum === bestAgg.sumVerbrauchQm &&
                compareIsoWeekOrder(agg.isoWeekYear, agg.isoWeek, bestAgg.isoWeekYear, bestAgg.isoWeek) < 0;
            if (betterSum || tieEarlier) {
                bestAgg = agg;
            }
        } else {
            const betterSum = sum < bestAgg.sumVerbrauchQm;
            const tieEarlier =
                sum === bestAgg.sumVerbrauchQm &&
                compareIsoWeekOrder(agg.isoWeekYear, agg.isoWeek, bestAgg.isoWeekYear, bestAgg.isoWeek) < 0;
            if (betterSum || tieEarlier) {
                bestAgg = agg;
            }
        }
    }
    return bestAgg;
}

/**
 * Weekly sums over the same submission list as YTD (typically sorted by calendar day).
 * Per ISO week: sum of delta_betriebsstunden, delta_starts, verbrauch_qm, and chained
 * vorlauf_temp / aussentemp deltas vs. the prior list entry.
 * Peak week is the week with maximum sum verbrauch_qm; ties break to lexicographically
 * earlier (isoWeekYear, isoWeek). Operating hours and starts shown are sums for that week.
 * consumptionPeakTied is true when more than one week shares that maximum consumption sum.
 * peakVorlaufTemp / peakOutsideTemp are null when no chained temperature delta contributed in that ISO week.
 *
 * @param {object[]} sortedSubmissions
 * @returns {{
 *   peakBetriebsstunden: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   peakStarts: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   peakVerbrauchQm: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   peakVorlaufTemp: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   peakOutsideTemp: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   consumptionPeakTied: boolean,
 * }}
 */
function computeWeeklyPeakStats(sortedSubmissions) {
    const empty = {
        peakBetriebsstunden: null,
        peakStarts: null,
        peakVerbrauchQm: null,
        peakVorlaufTemp: null,
        peakOutsideTemp: null,
        consumptionPeakTied: false,
    };

    const aggregates = buildWeeklyConsumptionBuckets(sortedSubmissions);
    if (aggregates.length === 0) {
        return empty;
    }

    const bestAgg = pickWeeklyBucketByConsumptionExtreme(aggregates, 'max');
    if (!bestAgg) {
        return empty;
    }

    const maxConsumption = bestAgg.sumVerbrauchQm;
    let weeksAtMax = 0;
    for (const agg of aggregates) {
        if (agg.sumVerbrauchQm === maxConsumption) {
            weeksAtMax += 1;
        }
    }
    const consumptionPeakTied = weeksAtMax > 1;

    const { isoWeekYear, isoWeek } = bestAgg;
    return {
        peakBetriebsstunden: {
            sum: bestAgg.sumDeltaBetriebsstunden,
            isoWeekYear,
            isoWeek,
        },
        peakStarts: {
            sum: bestAgg.sumDeltaStarts,
            isoWeekYear,
            isoWeek,
        },
        peakVerbrauchQm: {
            sum: bestAgg.sumVerbrauchQm,
            isoWeekYear,
            isoWeek,
        },
        peakVorlaufTemp: bestAgg.vorlaufDeltaCount > 0
            ? {
                sum: bestAgg.sumDeltaVorlauf,
                isoWeekYear,
                isoWeek,
            }
            : null,
        peakOutsideTemp: bestAgg.aussenDeltaCount > 0
            ? {
                sum: bestAgg.sumDeltaAussen,
                isoWeekYear,
                isoWeek,
            }
            : null,
        consumptionPeakTied,
    };
}

/**
 * Same weekly aggregation as peak; selects the ISO week with minimum sum verbrauch_qm.
 * The current UTC ISO week is omitted from the candidate set (incomplete partial week).
 * Ties break to lexicographically earlier (isoWeekYear, isoWeek).
 *
 * @param {object[]} sortedSubmissions
 * @returns {{
 *   minBetriebsstunden: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   minStarts: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   minVerbrauchQm: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   minVorlaufTemp: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   minOutsideTemp: { sum: number, isoWeekYear: number, isoWeek: number } | null,
 *   consumptionMinimumTied: boolean,
 * }}
 */
function computeWeeklyMinimumStats(sortedSubmissions) {
    const empty = {
        minBetriebsstunden: null,
        minStarts: null,
        minVerbrauchQm: null,
        minVorlaufTemp: null,
        minOutsideTemp: null,
        consumptionMinimumTied: false,
    };

    const aggregatesAll = buildWeeklyConsumptionBuckets(sortedSubmissions);
    const currentIso = getCurrentUtcIsoWeekParts();
    const aggregates = currentIso
        ? aggregatesAll.filter(
            (a) => a.isoWeekYear !== currentIso.isoWeekYear || a.isoWeek !== currentIso.isoWeek,
        )
        : aggregatesAll;
    if (aggregates.length === 0) {
        return empty;
    }

    const bestAgg = pickWeeklyBucketByConsumptionExtreme(aggregates, 'min');
    if (!bestAgg) {
        return empty;
    }

    const minConsumption = bestAgg.sumVerbrauchQm;
    let weeksAtMin = 0;
    for (const agg of aggregates) {
        if (agg.sumVerbrauchQm === minConsumption) {
            weeksAtMin += 1;
        }
    }
    const consumptionMinimumTied = weeksAtMin > 1;

    const { isoWeekYear, isoWeek } = bestAgg;
    return {
        minBetriebsstunden: {
            sum: bestAgg.sumDeltaBetriebsstunden,
            isoWeekYear,
            isoWeek,
        },
        minStarts: {
            sum: bestAgg.sumDeltaStarts,
            isoWeekYear,
            isoWeek,
        },
        minVerbrauchQm: {
            sum: bestAgg.sumVerbrauchQm,
            isoWeekYear,
            isoWeek,
        },
        minVorlaufTemp: bestAgg.vorlaufDeltaCount > 0
            ? {
                sum: bestAgg.sumDeltaVorlauf,
                isoWeekYear,
                isoWeek,
            }
            : null,
        minOutsideTemp: bestAgg.aussenDeltaCount > 0
            ? {
                sum: bestAgg.sumDeltaAussen,
                isoWeekYear,
                isoWeek,
            }
            : null,
        consumptionMinimumTied,
    };
}

function formatMetricValue(value, opts = {}) {
    const { kind = 'int', decimals = 2 } = opts;
    const n = normalizeNumber(value);
    if (n === null) {
        return '—';
    }
    if (kind === 'decimal') {
        return n.toFixed(decimals);
    }
    return String(Math.trunc(n));
}

async function fetchHistoryPage(limit, nextToken) {
    let url = `${CONFIG.API_ENDPOINT}/history?limit=${encodeURIComponent(String(limit))}`;
    if (nextToken) {
        url += `&next_token=${encodeURIComponent(nextToken)}`;
    }
    const response = await authenticatedFetch(url);
    if (!response || !response.ok) {
        throw new Error('Failed to load history');
    }
    const data = await response.json();
    return {
        submissions: (data && Array.isArray(data.submissions)) ? data.submissions : [],
        nextToken: (data && data.next_token) ? data.next_token : null,
    };
}

async function fetchLatestSubmission() {
    const { submissions } = await fetchHistoryPage(1, null);
    const latest = submissions.length > 0 && typeof submissions[0] === 'object' ? submissions[0] : null;
    return latest;
}

async function fetchEarliestSubmission() {
    // We page through the /history endpoint until next_token is exhausted.
    // The plan calls out: "keep the oldest item from the final page".
    // To be robust to ordering quirks, we also track the earliest by date across all items.
    let nextToken = null;
    let lastPageOldest = null;
    let overallEarliest = null;

    // Safety valve to avoid infinite loops if the API misbehaves.
    let pagesFetched = 0;
    const MAX_PAGES = 500;

    do {
        const page = await fetchHistoryPage(100, nextToken);
        const submissions = page.submissions;

        if (submissions.length > 0) {
            const oldestFromThisPage = submissions[submissions.length - 1];
            lastPageOldest = oldestFromThisPage;

            for (const s of submissions) {
                if (!overallEarliest) {
                    overallEarliest = s;
                    continue;
                }
                if (compareSubmissionsByDay(s, overallEarliest) < 0) {
                    overallEarliest = s;
                }
            }
        }

        nextToken = page.nextToken;
        pagesFetched += 1;
        if (pagesFetched > MAX_PAGES) {
            break;
        }
    } while (nextToken);

    return overallEarliest || lastPageOldest;
}

async function fetchAllSubmissions() {
    // Pages through /history until next_token is exhausted and returns all submissions.
    // Includes safeguards to avoid infinite loops if the API misbehaves.
    let nextToken = null;
    const all = [];

    let pagesFetched = 0;
    const MAX_PAGES = 500;

    do {
        const page = await fetchHistoryPage(100, nextToken);
        const submissions = page.submissions;

        for (const s of submissions) {
            if (s && typeof s === 'object') {
                all.push(s);
            }
        }

        nextToken = page.nextToken;
        pagesFetched += 1;
        if (pagesFetched > MAX_PAGES) {
            break;
        }
    } while (nextToken);
    return all;
}

function getAnalyzeTotalsContainer() {
    // First column of the Analyze grid (Totals).
    return document.querySelector('#analyze-page .analyze-grid .analyze-col') ||
           document.querySelector('#analyze-page .analyze-grid > div') ||
           null;
}

function getAnalyzePeakWeekContainer() {
    return document.getElementById('analyze-peak-week-col');
}

function getAnalyzeMinimumWeekContainer() {
    return document.getElementById('analyze-min-week-col');
}

function setAnalyzePageTitle(year) {
    const el = document.getElementById('analyze-page-title');
    if (!el) {
        return;
    }
    if (year != null && Number.isFinite(year)) {
        el.textContent = `Statistics Year to Date - ${year}`;
    } else {
        el.textContent = 'Statistics Year to Date';
    }
}

function renderAnalyzePeakWeekLoading() {
    const container = getAnalyzePeakWeekContainer();
    if (!container) return;
    container.innerHTML = `
        <h3>Peak week (consumption)</h3>
        <p class="empty-state">Loading statistics...</p>
    `;
}

function renderAnalyzePeakWeekError(message) {
    const container = getAnalyzePeakWeekContainer();
    if (!container) return;
    const safeMsg = (typeof message === 'string' && message.trim() !== '') ? message.trim() : 'Failed to load statistics';
    container.innerHTML = `
        <h3>Peak week (consumption)</h3>
        <p class="empty-state">${safeMsg}</p>
    `;
}

function renderAnalyzePeakWeekEmpty() {
    const container = getAnalyzePeakWeekContainer();
    if (!container) return;
    container.innerHTML = `
        <h3>Peak week (consumption)</h3>
        <p class="empty-state">No submissions found yet.</p>
    `;
}

function renderAnalyzeMinWeekLoading() {
    const container = getAnalyzeMinimumWeekContainer();
    if (!container) return;
    container.innerHTML = `
        <h3>Minimum week (consumption)</h3>
        <p class="empty-state">Loading statistics...</p>
    `;
}

function renderAnalyzeMinWeekError(message) {
    const container = getAnalyzeMinimumWeekContainer();
    if (!container) return;
    const safeMsg = (typeof message === 'string' && message.trim() !== '') ? message.trim() : 'Failed to load statistics';
    container.innerHTML = `
        <h3>Minimum week (consumption)</h3>
        <p class="empty-state">${safeMsg}</p>
    `;
}

function renderAnalyzeMinWeekEmpty() {
    const container = getAnalyzeMinimumWeekContainer();
    if (!container) return;
    container.innerHTML = `
        <h3>Minimum week (consumption)</h3>
        <p class="empty-state">No submissions found yet.</p>
    `;
}

/**
 * @param {{ isoWeekYear: number, isoWeek: number } | null | undefined} peak - e.g. peakVerbrauchQm
 * @returns {string} e.g. "CW 12 – 29.12-04.01", or "" if not representable
 */
function formatPeakWeekContextLine(peak) {
    if (!peak || typeof peak !== 'object' || !Number.isFinite(peak.isoWeek)) {
        return '';
    }
    const range = formatIsoWeekDdMmRange(peak.isoWeekYear, peak.isoWeek);
    if (!range) {
        return '';
    }
    return `CW ${peak.isoWeek} – ${range}`;
}

function formatPeakScalarValue(peak, valueOpts) {
    if (!peak || typeof peak !== 'object') {
        return '—';
    }
    return formatMetricValue(peak.sum, valueOpts);
}

function formatPeakTempValue(peak, valueOpts) {
    if (!peak || typeof peak !== 'object') {
        return '---';
    }
    return formatMetricValue(peak.sum, valueOpts);
}

/**
 * @param {{ peakBetriebsstunden, peakStarts, peakVerbrauchQm, peakVorlaufTemp, peakOutsideTemp, consumptionPeakTied }} peaks - from computeWeeklyPeakStats
 */
function renderAnalyzePeakWeek(peaks) {
    const container = getAnalyzePeakWeekContainer();
    if (!container) return;

    const p = peaks && typeof peaks === 'object' ? peaks : {};
    const tied = Boolean(p.consumptionPeakTied);
    const cardClass = tied ? 'analyze-card analyze-card--consumption-tied' : 'analyze-card';
    const tieBanner = tied
        ? '<p class="analyze-peak-tie-banner" role="status">⚠ Multiple weeks share this peak consumption; showing the lexicographically earlier week.</p>'
        : '';

    const cwLine = formatPeakWeekContextLine(p.peakVerbrauchQm);
    const cwLineHtml = cwLine
        ? `<div class="analyze-peak-week-range-line" role="note">${cwLine}</div>`
        : '';

    container.innerHTML = `
        <div class="${cardClass}">
            <div class="analyze-card-title">Peak week (consumption)</div>
            ${tieBanner}
            <div class="analyze-metrics">
                ${cwLineHtml}
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Consumption (m³)</span>
                    <span class="analyze-metric-value">${formatPeakScalarValue(p.peakVerbrauchQm, { kind: 'decimal', decimals: 2 })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Operating hours</span>
                    <span class="analyze-metric-value">${formatPeakScalarValue(p.peakBetriebsstunden, { kind: 'int' })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Starts</span>
                    <span class="analyze-metric-value">${formatPeakScalarValue(p.peakStarts, { kind: 'int' })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Supply Temp. (°C)</span>
                    <span class="analyze-metric-value">${formatPeakTempValue(p.peakVorlaufTemp, { kind: 'decimal', decimals: 1 })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Outside Temp Sensor (°C)</span>
                    <span class="analyze-metric-value">${formatPeakTempValue(p.peakOutsideTemp, { kind: 'decimal', decimals: 1 })}</span>
                </div>
            </div>
        </div>
    `;
}

/**
 * @param {{ minBetriebsstunden, minStarts, minVerbrauchQm, minVorlaufTemp, minOutsideTemp, consumptionMinimumTied }} mins - from computeWeeklyMinimumStats
 */
function renderAnalyzeMinWeek(mins) {
    const container = getAnalyzeMinimumWeekContainer();
    if (!container) return;

    const m = mins && typeof mins === 'object' ? mins : {};
    const tied = Boolean(m.consumptionMinimumTied);
    const cardClass = tied ? 'analyze-card analyze-card--consumption-tied' : 'analyze-card';
    const tieBanner = tied
        ? '<p class="analyze-peak-tie-banner" role="status">⚠ Multiple weeks share this minimum consumption; showing the lexicographically earlier week.</p>'
        : '';

    const cwLine = formatPeakWeekContextLine(m.minVerbrauchQm);
    const cwLineHtml = cwLine
        ? `<div class="analyze-peak-week-range-line" role="note">${cwLine}</div>`
        : '';

    container.innerHTML = `
        <div class="${cardClass}">
            <div class="analyze-card-title">Minimum week (consumption)</div>
            ${tieBanner}
            <div class="analyze-metrics">
                ${cwLineHtml}
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Consumption (m³)</span>
                    <span class="analyze-metric-value">${formatPeakScalarValue(m.minVerbrauchQm, { kind: 'decimal', decimals: 2 })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Operating hours</span>
                    <span class="analyze-metric-value">${formatPeakScalarValue(m.minBetriebsstunden, { kind: 'int' })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Starts</span>
                    <span class="analyze-metric-value">${formatPeakScalarValue(m.minStarts, { kind: 'int' })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Supply Temp. (°C)</span>
                    <span class="analyze-metric-value">${formatPeakTempValue(m.minVorlaufTemp, { kind: 'decimal', decimals: 1 })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Outside Temp Sensor (°C)</span>
                    <span class="analyze-metric-value">${formatPeakTempValue(m.minOutsideTemp, { kind: 'decimal', decimals: 1 })}</span>
                </div>
            </div>
        </div>
    `;
}

function renderAnalyzeLoading() {
    setAnalyzePageTitle(null);
    const container = getAnalyzeTotalsContainer();
    if (!container) return;
    container.innerHTML = `
        <h3>Totals</h3>
        <p class="empty-state">Loading statistics...</p>
    `;
    renderAnalyzePeakWeekLoading();
    renderAnalyzeMinWeekLoading();
}

function renderAnalyzeError(message) {
    setAnalyzePageTitle(null);
    const container = getAnalyzeTotalsContainer();
    if (!container) return;
    const safeMsg = (typeof message === 'string' && message.trim() !== '') ? message.trim() : 'Failed to load statistics';
    container.innerHTML = `
        <h3>Totals</h3>
        <p class="empty-state">${safeMsg}</p>
    `;
    renderAnalyzePeakWeekError(safeMsg);
    renderAnalyzeMinWeekError(safeMsg);
}

function renderAnalyzeEmpty() {
    setAnalyzePageTitle(null);
    const container = getAnalyzeTotalsContainer();
    if (!container) return;
    container.innerHTML = `
        <h3>Totals</h3>
        <p class="empty-state">No submissions found yet.</p>
    `;
    renderAnalyzePeakWeekEmpty();
    renderAnalyzeMinWeekEmpty();
}

function renderAnalyzeTotals(stats) {
    const container = getAnalyzeTotalsContainer();
    if (!container) return;

    const earliestDay = getSubmissionUtcDay(stats.earliest);
    const latestDay = getSubmissionUtcDay(stats.latest);
    const rangeText = (earliestDay && latestDay)
        ? `From ${earliestDay.toLocaleDateString('de-DE')} to ${latestDay.toLocaleDateString('de-DE')}`
        : 'Date range unavailable';

    container.innerHTML = `
        <div class="analyze-card">
            <div class="analyze-totals-range">${rangeText}</div>
            <div class="analyze-card-title">Totals</div>
            <div class="analyze-metrics">
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Consumption (m³)</span>
                    <span class="analyze-metric-value">${formatMetricValue(stats.totalConsumption, { kind: 'decimal', decimals: 2 })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Operating hours</span>
                    <span class="analyze-metric-value">${formatMetricValue(stats.totalOperatingHours, { kind: 'int' })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Starts</span>
                    <span class="analyze-metric-value">${formatMetricValue(stats.totalStarts, { kind: 'int' })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Days</span>
                    <span class="analyze-metric-value">${stats.days === null ? '—' : String(stats.days)}</span>
                </div>
            </div>
        </div>
    `;
}

// Live Page Functions
function getLiveContentContainer() {
    return document.getElementById('live-content');
}

function renderLiveLoading() {
    const container = getLiveContentContainer();
    if (!container) return;
    container.innerHTML = '<p class="empty-state">Loading live heating data...</p>';
}

function renderLiveError(message) {
    const container = getLiveContentContainer();
    if (!container) return;
    const safeMsg = (typeof message === 'string' && message.trim() !== '') ? message.trim() : 'Failed to load heating data';
    container.innerHTML = `<p class="empty-state">${safeMsg}</p>`;
}

function renderLiveData(data) {
    const container = getLiveContentContainer();
    if (!container) return;

    const formatVal = (v) => (v === null || v === undefined ? '—' : String(v));
    const fetchedAt = data.fetched_at
        ? formatTimestamp(data.fetched_at)
        : '—';

    container.innerHTML = `
        <div class="analyze-card">
            <div class="analyze-card-title">Live Heating Values</div>
            <div class="analyze-metrics">
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Gas Consumption (m³ today so far)</span>
                    <span class="analyze-metric-value">${formatVal(data.gas_consumption_m3_today)}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Gas Consumption (m³ yesterday)</span>
                    <span class="analyze-metric-value">${formatVal(data.gas_consumption_m3_yesterday)}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Operating Hours</span>
                    <span class="analyze-metric-value">${formatVal(data.betriebsstunden)}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Starts</span>
                    <span class="analyze-metric-value">${formatVal(data.starts)}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Supply Temp (°C)</span>
                    <span class="analyze-metric-value">${formatVal(data.supply_temp)}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Outside-Temp. Sensor (°C)</span>
                    <span class="analyze-metric-value">${formatVal(data.outside_temp)}</span>
                </div>
            </div>
            <div style="margin-top: 1rem; color: #7f8c8d; font-size: 0.95rem;">
                Fetched at: ${fetchedAt}
            </div>
        </div>
    `;
}

/**
 * Fetches live heating data from the API.
 * Shared by loadLive (Live tab) and injectLiveDataIntoForm (Init tab Live button).
 *
 * @returns {Promise<{gas_consumption_m3_today, gas_consumption_m3_yesterday, betriebsstunden, starts, supply_temp, outside_temp, fetched_at}>}
 * @throws {Error} On auth failure, non-OK response, or network error
 */
async function fetchLiveHeatingData() {
    if (typeof authenticatedFetch !== 'function') {
        throw new Error('Not authenticated yet.');
    }

    const response = await authenticatedFetch(`${CONFIG.API_ENDPOINT}/heating/live`);
    if (!response.ok) {
        const errBody = await response.json().catch(() => ({}));
        const msg = errBody.error || `Request failed: ${response.status}`;
        throw new Error(msg);
    }

    return response.json();
}

async function loadLive() {
    renderLiveLoading();

    try {
        const data = await fetchLiveHeatingData();
        renderLiveData(data);
    } catch (error) {
        console.error('Error loading live heating data:', error);
        renderLiveError(error.message || 'Failed to load heating data');
    }
}

/**
 * Fetches live heating data and injects it into the Submit Data form fields.
 * Excludes Date (datum) and Time (uhrzeit).
 */
async function injectLiveDataIntoForm() {
    const liveBtn = document.getElementById('live-inject-btn');
    const originalText = liveBtn ? liveBtn.textContent : 'Live';

    try {
        if (liveBtn) {
            liveBtn.disabled = true;
            liveBtn.textContent = 'Loading…';
        }
        clearFormMessage();

        const data = await fetchLiveHeatingData();

        // Inject into form fields (excluding datum and uhrzeit)
        const betriebsstundenEl = document.getElementById('betriebsstunden');
        const startsEl = document.getElementById('starts');
        const verbrauchEl = document.getElementById('verbrauch_qm');
        const vorlaufEl = document.getElementById('vorlauf_temp');
        const aussentempEl = document.getElementById('aussentemp');

        if (betriebsstundenEl && data.betriebsstunden != null) {
            betriebsstundenEl.value = String(data.betriebsstunden);
        }
        if (startsEl && data.starts != null) {
            startsEl.value = String(data.starts);
        }
        if (verbrauchEl && data.gas_consumption_m3_yesterday != null) {
            verbrauchEl.value = Number(data.gas_consumption_m3_yesterday).toFixed(2);
        }
        if (vorlaufEl && data.supply_temp != null) {
            vorlaufEl.value = Number(data.supply_temp).toFixed(1);
        }
        if (aussentempEl && data.outside_temp != null) {
            aussentempEl.value = Number(data.outside_temp).toFixed(1);
        }

        showFormMessage('Live data injected successfully.', 'success');
    } catch (error) {
        console.error('Error injecting live data:', error);
        showFormMessage(error.message || 'Failed to load live data.', 'error');
    } finally {
        if (liveBtn) {
            liveBtn.disabled = false;
            liveBtn.textContent = originalText;
        }
    }
}

async function loadAnalyze() {
    renderAnalyzeLoading();

    try {
        if (typeof authenticatedFetch !== 'function') {
            renderAnalyzeError('Not authenticated yet.');
            return;
        }

        const submissions = await fetchAllSubmissions();
        if (!Array.isArray(submissions) || submissions.length === 0) {
            renderAnalyzeEmpty();
            return;
        }

        const sorted = submissions.slice().sort(compareSubmissionsByDay);
        const earliest = sorted.find((s) => getSubmissionUtcDay(s)) || sorted[0] || null;
        const latest = sorted.slice().reverse().find((s) => getSubmissionUtcDay(s)) || sorted[sorted.length - 1] || null;

        if (!earliest || !latest) {
            renderAnalyzeEmpty();
            return;
        }

        const stats = computeYtdTotals(earliest, latest, sorted);
        if (!stats) {
            renderAnalyzeError('Failed to compute statistics.');
            return;
        }

        const latestDay = getSubmissionUtcDay(latest);
        setAnalyzePageTitle(latestDay ? latestDay.getUTCFullYear() : null);

        renderAnalyzeTotals(stats);
        renderAnalyzePeakWeek(computeWeeklyPeakStats(sorted));
        renderAnalyzeMinWeek(computeWeeklyMinimumStats(sorted));
    } catch (error) {
        console.error('Error loading analyze statistics:', error);
        renderAnalyzeError('Failed to load statistics');
    }
}

// Utility Functions
function formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString('de-DE', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function getDeltaValue(obj, preferredKey, fallbackKey) {
    if (!obj || typeof obj !== 'object') {
        return null;
    }
    if (Object.prototype.hasOwnProperty.call(obj, preferredKey)) {
        return obj[preferredKey];
    }
    if (Object.prototype.hasOwnProperty.call(obj, fallbackKey)) {
        return obj[fallbackKey];
    }
    return null;
}

function normalizeNumber(value) {
    if (value === null || value === undefined) {
        return null;
    }
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : null;
    }
    if (typeof value === 'string') {
        const normalized = value.replace(',', '.').trim();
        if (normalized === '') return null;
        const n = Number(normalized);
        return Number.isFinite(n) ? n : null;
    }
    return null;
}

function formatDelta(deltaRaw, opts = {}) {
    const { kind = 'int', decimals = 2 } = opts;
    const delta = normalizeNumber(deltaRaw);
    if (delta === null) {
        return '';
    }

    let valueStr;
    if (kind === 'decimal') {
        valueStr = delta.toFixed(decimals);
    } else {
        valueStr = String(Math.trunc(delta));
    }

    if (delta > 0) {
        return `(+${valueStr})`;
    }
    if (delta < 0) {
        return `(${valueStr})`;
    }
    return '(0)';
}

// Exports for Jest tests (Node environment). No impact in browser runtime.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        initializeFormPage,
        prefillFromLatestSubmission,
        parseGermanDateToUtcMidnight,
        getSubmissionUtcDay,
        computeInclusiveDays,
        computeYtdTotals,
        computeWeeklyPeakStats,
        computeWeeklyMinimumStats,
        getIsoWeekPartsFromUtcDate,
        formatIsoWeekDdMmRange,
        normalizeSettingsConfig,
        validateSettingsPayload,
        normalizeSettingsSchedulerMetadata,
        renderSettingsSchedulerMetadata,
        loadSettings,
        __setAuthenticatedFetchForTests: (fn) => {
            authenticatedFetch = fn;
        },
        __setConfigForTests: (cfg) => {
            if (cfg && typeof cfg === 'object') {
                Object.assign(CONFIG, cfg);
            }
        },
    };
}
