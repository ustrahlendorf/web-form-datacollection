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
    } else if (page === 'form') {
        initializeFormPage();
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
    const formData = {
        datum: document.getElementById('datum').value.trim(),
        uhrzeit: document.getElementById('uhrzeit').value.trim(),
        betriebsstunden: parseInt(document.getElementById('betriebsstunden').value),
        starts: parseInt(document.getElementById('starts').value),
        verbrauch_qm: parseFloat(document.getElementById('verbrauch_qm').value.replace(',', '.')),
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
                    <span class="recent-item-value">${submission.verbrauch_qm} kWh/m² <span class="delta">${formatDelta(getDeltaValue(submission, 'delta_verbrauch_qm', 'verbrauch_qm_delta'), { kind: 'decimal', decimals: 2 })}</span></span>
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
                    <th>Consumption (kWh/m²)</th>
                    <th>Δ Consumption</th>
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
