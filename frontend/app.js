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
};

// Initialize AuthManager
let authManager;
let authenticatedFetch;

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
    if (hash && ['form', 'analyze', 'history', 'live'].includes(hash)) {
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
                <span>${submission.datum} ${submission.uhrzeit}</span>
                <span class="recent-item-date">${formatTimestamp(submission.timestamp_utc)}</span>
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
                    <th>Time</th>
                    <th>Operating Hours</th>
                    <th>Δ Operating Hours</th>
                    <th>Starts</th>
                    <th>Δ Starts</th>
                    <th>Consumption (m³)</th>
                    <th>Δ Consumption (m³)</th>
                    <th>Supply Temp (°C)</th>
                    <th>Outside-Temp. Sensor (°C)</th>
                    <th>Submitted</th>
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

function renderAnalyzeLoading() {
    const container = getAnalyzeTotalsContainer();
    if (!container) return;
    container.innerHTML = `
        <h3>Totals</h3>
        <p class="empty-state">Loading statistics...</p>
    `;
}

function renderAnalyzeError(message) {
    const container = getAnalyzeTotalsContainer();
    if (!container) return;
    const safeMsg = (typeof message === 'string' && message.trim() !== '') ? message.trim() : 'Failed to load statistics';
    container.innerHTML = `
        <h3>Totals</h3>
        <p class="empty-state">${safeMsg}</p>
    `;
}

function renderAnalyzeEmpty() {
    const container = getAnalyzeTotalsContainer();
    if (!container) return;
    container.innerHTML = `
        <h3>Totals</h3>
        <p class="empty-state">No submissions found yet.</p>
    `;
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
            <div class="analyze-card-title">Totals</div>
            <div class="analyze-metrics">
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Operating hours</span>
                    <span class="analyze-metric-value">${formatMetricValue(stats.totalOperatingHours, { kind: 'int' })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Starts</span>
                    <span class="analyze-metric-value">${formatMetricValue(stats.totalStarts, { kind: 'int' })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Consumption</span>
                    <span class="analyze-metric-value">${formatMetricValue(stats.totalConsumption, { kind: 'decimal', decimals: 2 })}</span>
                </div>
                <div class="analyze-metric">
                    <span class="analyze-metric-label">Days</span>
                    <span class="analyze-metric-value">${stats.days === null ? '—' : String(stats.days)}</span>
                </div>
            </div>
            <div style="margin-top: 1rem; color: #7f8c8d; font-size: 0.95rem;">
                ${rangeText}
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

        renderAnalyzeTotals(stats);
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
