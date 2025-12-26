/**
 * Authentication Module
 * Handles Cognito OAuth2 flow, JWT token management, and API request authorization
 */

class AuthManager {
    constructor(config) {
        this.config = config;
        this.token = null;
        this.idToken = null;
        this.refreshToken = null;
        this.tokenExpiresAt = null;
        this.userId = null;
        this.listeners = [];
        
        // Load tokens from storage on initialization
        this.loadTokensFromStorage();
    }

    /**
     * Register a listener for authentication state changes
     */
    onAuthStateChanged(callback) {
        this.listeners.push(callback);
    }

    /**
     * Notify all listeners of authentication state changes
     */
    notifyListeners(isAuthenticated) {
        this.listeners.forEach(callback => {
            callback(isAuthenticated);
        });
    }

    /**
     * Load tokens from localStorage
     */
    loadTokensFromStorage() {
        this.token = localStorage.getItem('access_token');
        this.idToken = localStorage.getItem('id_token');
        this.refreshToken = localStorage.getItem('refresh_token');
        this.tokenExpiresAt = localStorage.getItem('token_expires_at');
        this.userId = localStorage.getItem('user_id');
    }

    /**
     * Save tokens to localStorage
     */
    saveTokensToStorage() {
        if (this.token) {
            localStorage.setItem('access_token', this.token);
        }
        if (this.idToken) {
            localStorage.setItem('id_token', this.idToken);
        }
        if (this.refreshToken) {
            localStorage.setItem('refresh_token', this.refreshToken);
        }
        if (this.tokenExpiresAt) {
            localStorage.setItem('token_expires_at', this.tokenExpiresAt);
        }
        if (this.userId) {
            localStorage.setItem('user_id', this.userId);
        }
    }

    /**
     * Clear all tokens from storage
     */
    clearTokensFromStorage() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('id_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('token_expires_at');
        localStorage.removeItem('user_id');
    }

    /**
     * Check if user is currently authenticated
     */
    isAuthenticated() {
        if (!this.token) {
            return false;
        }

        // Check if token is expired
        if (this.tokenExpiresAt) {
            const expiresAt = parseInt(this.tokenExpiresAt);
            const now = Math.floor(Date.now() / 1000);
            
            if (now >= expiresAt) {
                return false;
            }
        }

        return true;
    }

    /**
     * Initiate Cognito OAuth2 authorization flow
     */
    initiateLogin() {
        const authUrl = `${this.config.COGNITO_DOMAIN}/oauth2/authorize?` +
            `client_id=${this.config.COGNITO_CLIENT_ID}&` +
            `response_type=code&` +
            `scope=openid+profile+email&` +
            `redirect_uri=${encodeURIComponent(this.config.COGNITO_REDIRECT_URI)}`;
        
        window.location.href = authUrl;
    }

    /**
     * Handle OAuth callback and exchange code for tokens
     * This should be called after redirect from Cognito
     */
    async handleAuthCallback() {
        const urlParams = new URLSearchParams(window.location.search);
        const code = urlParams.get('code');
        const error = urlParams.get('error');

        if (error) {
            console.error('Authentication error:', error);
            this.notifyListeners(false);
            return false;
        }

        if (!code) {
            return false;
        }

        try {
            // Exchange authorization code for tokens
            // In a production app, this should be done on the backend for security
            // For now, we'll use the Cognito token endpoint directly
            const tokenResponse = await this.exchangeCodeForToken(code);
            
            if (tokenResponse) {
                this.setTokens(tokenResponse);
                
                // Extract user_id from ID token
                this.userId = this.extractUserIdFromToken(this.idToken);
                
                // Clean up URL
                window.history.replaceState({}, document.title, window.location.pathname);
                
                this.notifyListeners(true);
                return true;
            }
        } catch (error) {
            console.error('Error handling auth callback:', error);
            this.notifyListeners(false);
            return false;
        }

        return false;
    }

    /**
     * Exchange authorization code for tokens via Cognito token endpoint
     */
    async exchangeCodeForToken(code) {
        try {
            const response = await fetch(`${this.config.COGNITO_DOMAIN}/oauth2/token`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: new URLSearchParams({
                    grant_type: 'authorization_code',
                    client_id: this.config.COGNITO_CLIENT_ID,
                    code: code,
                    redirect_uri: this.config.COGNITO_REDIRECT_URI,
                }),
            });

            if (!response.ok) {
                throw new Error(`Token exchange failed: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error exchanging code for token:', error);
            throw error;
        }
    }

    /**
     * Set tokens and calculate expiration time
     */
    setTokens(tokenResponse) {
        this.token = tokenResponse.access_token;
        this.idToken = tokenResponse.id_token;
        this.refreshToken = tokenResponse.refresh_token;

        // Calculate token expiration time
        if (tokenResponse.expires_in) {
            const expiresIn = parseInt(tokenResponse.expires_in);
            const now = Math.floor(Date.now() / 1000);
            this.tokenExpiresAt = (now + expiresIn).toString();
        }

        this.saveTokensToStorage();
    }

    /**
     * Refresh access token using refresh token
     */
    async refreshAccessToken() {
        if (!this.refreshToken) {
            console.warn('No refresh token available');
            return false;
        }

        try {
            const response = await fetch(`${this.config.COGNITO_DOMAIN}/oauth2/token`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: new URLSearchParams({
                    grant_type: 'refresh_token',
                    client_id: this.config.COGNITO_CLIENT_ID,
                    refresh_token: this.refreshToken,
                }),
            });

            if (!response.ok) {
                throw new Error(`Token refresh failed: ${response.statusText}`);
            }

            const tokenResponse = await response.json();
            this.setTokens(tokenResponse);
            this.notifyListeners(true);
            return true;
        } catch (error) {
            console.error('Error refreshing token:', error);
            // If refresh fails, clear tokens and logout
            this.logout();
            return false;
        }
    }

    /**
     * Extract user ID from JWT token
     */
    extractUserIdFromToken(token) {
        try {
            const parts = token.split('.');
            if (parts.length !== 3) {
                throw new Error('Invalid token format');
            }

            const decoded = JSON.parse(atob(parts[1]));
            return decoded.sub || decoded['cognito:username'] || null;
        } catch (error) {
            console.error('Error decoding token:', error);
            return null;
        }
    }

    /**
     * Get current access token
     */
    getAccessToken() {
        // Check if token needs refresh
        if (this.tokenExpiresAt) {
            const expiresAt = parseInt(this.tokenExpiresAt);
            const now = Math.floor(Date.now() / 1000);
            const timeUntilExpiry = expiresAt - now;

            // Refresh if token expires in less than 5 minutes
            if (timeUntilExpiry < 300) {
                // Note: This is async, but we return the current token
                // In production, you might want to handle this differently
                this.refreshAccessToken();
            }
        }

        return this.token;
    }

    /**
     * Get authorization header for API requests
     */
    getAuthorizationHeader() {
        const token = this.getAccessToken();
        if (token) {
            return `Bearer ${token}`;
        }
        return null;
    }

    /**
     * Logout user and clear all tokens
     */
    logout() {
        this.token = null;
        this.idToken = null;
        this.refreshToken = null;
        this.tokenExpiresAt = null;
        this.userId = null;

        this.clearTokensFromStorage();
        this.notifyListeners(false);

        // Redirect to Cognito logout endpoint
        const logoutUrl = `${this.config.COGNITO_DOMAIN}/logout?` +
            `client_id=${this.config.COGNITO_CLIENT_ID}&` +
            `logout_uri=${encodeURIComponent(this.config.COGNITO_REDIRECT_URI)}`;
        
        window.location.href = logoutUrl;
    }

    /**
     * Get user ID
     */
    getUserId() {
        return this.userId;
    }
}

/**
 * Create a fetch wrapper that automatically adds JWT token to requests
 */
function createAuthenticatedFetch(authManager) {
    return async function authenticatedFetch(url, options = {}) {
        const headers = options.headers || {};
        
        // Add authorization header if user is authenticated
        if (authManager.isAuthenticated()) {
            const authHeader = authManager.getAuthorizationHeader();
            if (authHeader) {
                headers['Authorization'] = authHeader;
            }
        }

        const response = await fetch(url, {
            ...options,
            headers,
        });

        // If we get a 401, try to refresh token and retry once
        if (response.status === 401 && authManager.refreshToken) {
            const refreshed = await authManager.refreshAccessToken();
            if (refreshed) {
                // Retry the request with new token
                const newHeaders = { ...headers };
                const authHeader = authManager.getAuthorizationHeader();
                if (authHeader) {
                    newHeaders['Authorization'] = authHeader;
                }

                return fetch(url, {
                    ...options,
                    headers: newHeaders,
                });
            }
        }

        return response;
    };
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AuthManager, createAuthenticatedFetch };
}
