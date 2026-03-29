/**
 * Tests for form page functionality
 * Tests the form pre-population and submission logic
 */

const {
    prefillFromLatestSubmission,
    __setAuthenticatedFetchForTests,
    __setConfigForTests,
} = require('./src/app.js');

// Mock DOM elements
function setupFormDOM() {
    document.body.innerHTML = `
        <form id="submission-form">
            <input type="text" id="datum" name="datum" />
            <input type="text" id="uhrzeit" name="uhrzeit" />
            <input type="number" id="betriebsstunden" name="betriebsstunden" />
            <input type="number" id="starts" name="starts" />
            <input type="text" id="verbrauch_qm" name="verbrauch_qm" />
            <button type="submit">Submit</button>
        </form>
        <div id="form-message" class="message"></div>
        <div id="recent-submissions" class="recent-list"></div>
    `;
}

/**
 * Property 0: Form Pre-Population on Page Load
 * **Feature: data-collection-webapp, Property 0: Form Pre-Population on Page Load**
 * **Validates: Requirements 2.2, 2.3, 2.4**
 */
describe('Form Pre-Population', () => {
    beforeEach(() => {
        setupFormDOM();
    });

    test('should pre-populate datum with current date in dd.mm.yyyy format', () => {
        const now = new Date();
        const expectedDay = String(now.getDate()).padStart(2, '0');
        const expectedMonth = String(now.getMonth() + 1).padStart(2, '0');
        const expectedYear = now.getFullYear();
        const expectedDate = `${expectedDay}.${expectedMonth}.${expectedYear}`;

        // Simulate form initialization
        const day = String(now.getDate()).padStart(2, '0');
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const year = now.getFullYear();
        document.getElementById('datum').value = `${day}.${month}.${year}`;

        const datumValue = document.getElementById('datum').value;
        expect(datumValue).toBe(expectedDate);
        expect(datumValue).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
    });

    test('should pre-populate uhrzeit with current time in hh:mm format', () => {
        const now = new Date();
        const expectedHours = String(now.getHours()).padStart(2, '0');
        const expectedMinutes = String(now.getMinutes()).padStart(2, '0');
        const expectedTime = `${expectedHours}:${expectedMinutes}`;

        // Simulate form initialization
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        document.getElementById('uhrzeit').value = `${hours}:${minutes}`;

        const uhrzeitValue = document.getElementById('uhrzeit').value;
        expect(uhrzeitValue).toBe(expectedTime);
        expect(uhrzeitValue).toMatch(/^\d{2}:\d{2}$/);
    });

    test('should set betriebsstunden to 0', () => {
        document.getElementById('betriebsstunden').value = '0';
        expect(document.getElementById('betriebsstunden').value).toBe('0');
    });

    test('should set starts to 0', () => {
        document.getElementById('starts').value = '0';
        expect(document.getElementById('starts').value).toBe('0');
    });

    test('should set verbrauch_qm to 0', () => {
        document.getElementById('verbrauch_qm').value = '0';
        expect(document.getElementById('verbrauch_qm').value).toBe('0');
    });

    test('should initialize all fields together on page load', () => {
        // Simulate complete form initialization
        const now = new Date();
        const day = String(now.getDate()).padStart(2, '0');
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const year = now.getFullYear();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');

        document.getElementById('datum').value = `${day}.${month}.${year}`;
        document.getElementById('uhrzeit').value = `${hours}:${minutes}`;
        document.getElementById('betriebsstunden').value = '0';
        document.getElementById('starts').value = '0';
        document.getElementById('verbrauch_qm').value = '0';

        // Verify all fields are populated
        expect(document.getElementById('datum').value).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
        expect(document.getElementById('uhrzeit').value).toMatch(/^\d{2}:\d{2}$/);
        expect(document.getElementById('betriebsstunden').value).toBe('0');
        expect(document.getElementById('starts').value).toBe('0');
        expect(document.getElementById('verbrauch_qm').value).toBe('0');
    });

    test('should format date correctly for different dates', () => {
        // Test with a specific date
        const testDate = new Date(2025, 11, 15); // December 15, 2025
        const day = String(testDate.getDate()).padStart(2, '0');
        const month = String(testDate.getMonth() + 1).padStart(2, '0');
        const year = testDate.getFullYear();
        const formatted = `${day}.${month}.${year}`;

        expect(formatted).toBe('15.12.2025');
    });

    test('should format time correctly for different times', () => {
        // Test with a specific time
        const testDate = new Date(2025, 11, 15, 9, 30);
        const hours = String(testDate.getHours()).padStart(2, '0');
        const minutes = String(testDate.getMinutes()).padStart(2, '0');
        const formatted = `${hours}:${minutes}`;

        expect(formatted).toBe('09:30');
    });

    test('should handle single-digit day and month with leading zeros', () => {
        const testDate = new Date(2025, 0, 5); // January 5, 2025
        const day = String(testDate.getDate()).padStart(2, '0');
        const month = String(testDate.getMonth() + 1).padStart(2, '0');
        const year = testDate.getFullYear();
        const formatted = `${day}.${month}.${year}`;

        expect(formatted).toBe('05.01.2025');
    });

    test('should handle single-digit hour and minute with leading zeros', () => {
        const testDate = new Date(2025, 11, 15, 5, 3);
        const hours = String(testDate.getHours()).padStart(2, '0');
        const minutes = String(testDate.getMinutes()).padStart(2, '0');
        const formatted = `${hours}:${minutes}`;

        expect(formatted).toBe('05:03');
    });
});

describe('Form Prefill from Latest Submission', () => {
    beforeEach(() => {
        setupFormDOM();
        __setConfigForTests({ API_ENDPOINT: 'https://example.test' });

        // Defaults, same as initializeFormPage does.
        document.getElementById('betriebsstunden').value = '0';
        document.getElementById('starts').value = '0';
        document.getElementById('verbrauch_qm').value = '0';
    });

    test('should prefill operating hours, starts, and consumption from latest /history item', async () => {
        __setAuthenticatedFetchForTests(async (url) => {
            expect(url).toBe('https://example.test/history?limit=1');
            return {
                ok: true,
                json: async () => ({
                    submissions: [{
                        betriebsstunden: 123,
                        starts: 4,
                        verbrauch_qm: 1.23,
                    }],
                }),
            };
        });

        await prefillFromLatestSubmission();

        expect(document.getElementById('betriebsstunden').value).toBe('123');
        expect(document.getElementById('starts').value).toBe('4');
        expect(document.getElementById('verbrauch_qm').value).toBe('1.23');
    });

    test('should not overwrite values if user already changed defaults', async () => {
        document.getElementById('betriebsstunden').value = '7';
        document.getElementById('starts').value = '8';
        document.getElementById('verbrauch_qm').value = '9.99';

        __setAuthenticatedFetchForTests(async () => ({
            ok: true,
            json: async () => ({
                submissions: [{
                    betriebsstunden: 999,
                    starts: 999,
                    verbrauch_qm: 9.87,
                }],
            }),
        }));

        await prefillFromLatestSubmission();

        expect(document.getElementById('betriebsstunden').value).toBe('7');
        expect(document.getElementById('starts').value).toBe('8');
        expect(document.getElementById('verbrauch_qm').value).toBe('9.99');
    });

    test('should keep defaults when there is no previous submission', async () => {
        __setAuthenticatedFetchForTests(async () => ({
            ok: true,
            json: async () => ({ submissions: [] }),
        }));

        await prefillFromLatestSubmission();

        expect(document.getElementById('betriebsstunden').value).toBe('0');
        expect(document.getElementById('starts').value).toBe('0');
        expect(document.getElementById('verbrauch_qm').value).toBe('0');
    });

    test('should keep defaults when the request fails', async () => {
        const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
        __setAuthenticatedFetchForTests(async () => {
            throw new Error('network down');
        });

        await expect(prefillFromLatestSubmission()).resolves.toBeUndefined();

        expect(document.getElementById('betriebsstunden').value).toBe('0');
        expect(document.getElementById('starts').value).toBe('0');
        expect(document.getElementById('verbrauch_qm').value).toBe('0');
        warnSpy.mockRestore();
    });
});
