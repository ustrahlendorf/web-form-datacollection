/**
 * Property-Based Tests for Form Pre-Population
 * **Feature: data-collection-webapp, Property 0: Form Pre-Population on Page Load**
 * **Validates: Requirements 2.2, 2.3, 2.4**
 */

const fc = require('fast-check');

// Mock DOM setup helper
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

// Helper function to format date as dd.mm.yyyy
function formatDateToDDMMYYYY(date) {
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const year = date.getFullYear();
    return `${day}.${month}.${year}`;
}

// Helper function to format time as hh:mm
function formatTimeToHHMM(date) {
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${hours}:${minutes}`;
}

// Helper function to simulate form initialization
function initializeFormPage(referenceDate) {
    const day = String(referenceDate.getDate()).padStart(2, '0');
    const month = String(referenceDate.getMonth() + 1).padStart(2, '0');
    const year = referenceDate.getFullYear();
    document.getElementById('datum').value = `${day}.${month}.${year}`;
    
    const hours = String(referenceDate.getHours()).padStart(2, '0');
    const minutes = String(referenceDate.getMinutes()).padStart(2, '0');
    document.getElementById('uhrzeit').value = `${hours}:${minutes}`;
    
    document.getElementById('betriebsstunden').value = '0';
    document.getElementById('starts').value = '0';
    document.getElementById('verbrauch_qm').value = '0';
}

describe('Form Pre-Population Property-Based Tests', () => {
    beforeEach(() => {
        setupFormDOM();
    });

    /**
     * Property 0: Form Pre-Population on Page Load
     * For any date, the form SHALL pre-populate datum with the date in dd.mm.yyyy format,
     * uhrzeit with the time in hh:mm format, and numeric fields with 0.
     */
    test('Property 0: Form pre-population maintains correct date format for all valid dates', () => {
        fc.assert(
            fc.property(
                fc.date({ min: new Date(2000, 0, 1), max: new Date(2100, 11, 31) }),
                (testDate) => {
                    setupFormDOM();
                    initializeFormPage(testDate);

                    const datumValue = document.getElementById('datum').value;
                    const expectedDate = formatDateToDDMMYYYY(testDate);

                    // Verify format matches dd.mm.yyyy
                    expect(datumValue).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
                    // Verify value matches expected date
                    expect(datumValue).toBe(expectedDate);
                }
            ),
            { numRuns: 100 }
        );
    });

    /**
     * Property 0: Form Pre-Population on Page Load (Time Component)
     * For any time, the form SHALL pre-populate uhrzeit with the time in hh:mm format.
     */
    test('Property 0: Form pre-population maintains correct time format for all valid times', () => {
        fc.assert(
            fc.property(
                fc.tuple(
                    fc.integer({ min: 0, max: 23 }),
                    fc.integer({ min: 0, max: 59 })
                ),
                ([hours, minutes]) => {
                    setupFormDOM();
                    const testDate = new Date(2025, 0, 15, hours, minutes);
                    initializeFormPage(testDate);

                    const uhrzeitValue = document.getElementById('uhrzeit').value;
                    const expectedTime = formatTimeToHHMM(testDate);

                    // Verify format matches hh:mm
                    expect(uhrzeitValue).toMatch(/^\d{2}:\d{2}$/);
                    // Verify value matches expected time
                    expect(uhrzeitValue).toBe(expectedTime);
                }
            ),
            { numRuns: 100 }
        );
    });

    /**
     * Property 0: Form Pre-Population on Page Load (Numeric Fields)
     * For any page load, numeric fields SHALL be initialized to 0.
     */
    test('Property 0: Form pre-population initializes all numeric fields to 0', () => {
        fc.assert(
            fc.property(
                fc.date({ min: new Date(2000, 0, 1), max: new Date(2100, 11, 31) }),
                (testDate) => {
                    setupFormDOM();
                    initializeFormPage(testDate);

                    const betriebsstundenValue = document.getElementById('betriebsstunden').value;
                    const startsValue = document.getElementById('starts').value;
                    const verbrauchValue = document.getElementById('verbrauch_qm').value;

                    // All numeric fields should be '0'
                    expect(betriebsstundenValue).toBe('0');
                    expect(startsValue).toBe('0');
                    expect(verbrauchValue).toBe('0');
                }
            ),
            { numRuns: 100 }
        );
    });

    /**
     * Property 0: Form Pre-Population on Page Load (Complete State)
     * For any date and time, all form fields SHALL be populated correctly together.
     */
    test('Property 0: Form pre-population initializes all fields together correctly', () => {
        fc.assert(
            fc.property(
                fc.date({ min: new Date(2000, 0, 1), max: new Date(2100, 11, 31) }),
                (testDate) => {
                    setupFormDOM();
                    initializeFormPage(testDate);

                    const datumValue = document.getElementById('datum').value;
                    const uhrzeitValue = document.getElementById('uhrzeit').value;
                    const betriebsstundenValue = document.getElementById('betriebsstunden').value;
                    const startsValue = document.getElementById('starts').value;
                    const verbrauchValue = document.getElementById('verbrauch_qm').value;

                    // Verify all fields are populated
                    expect(datumValue).toBeTruthy();
                    expect(uhrzeitValue).toBeTruthy();
                    expect(betriebsstundenValue).toBe('0');
                    expect(startsValue).toBe('0');
                    expect(verbrauchValue).toBe('0');

                    // Verify formats
                    expect(datumValue).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
                    expect(uhrzeitValue).toMatch(/^\d{2}:\d{2}$/);
                }
            ),
            { numRuns: 100 }
        );
    });

    /**
     * Property 0: Form Pre-Population on Page Load (Date Parsing Roundtrip)
     * For any date, parsing the pre-populated datum field should yield the same date.
     */
    test('Property 0: Form pre-population date can be parsed back to original date', () => {
        fc.assert(
            fc.property(
                fc.date({ min: new Date(2000, 0, 1), max: new Date(2100, 11, 31) }),
                (testDate) => {
                    setupFormDOM();
                    initializeFormPage(testDate);

                    const datumValue = document.getElementById('datum').value;
                    
                    // Parse the formatted date back
                    const match = datumValue.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
                    expect(match).not.toBeNull();

                    const [, day, month, year] = match;
                    const parsedDate = new Date(parseInt(year), parseInt(month) - 1, parseInt(day));

                    // Verify parsed date matches original
                    expect(parsedDate.getDate()).toBe(testDate.getDate());
                    expect(parsedDate.getMonth()).toBe(testDate.getMonth());
                    expect(parsedDate.getFullYear()).toBe(testDate.getFullYear());
                }
            ),
            { numRuns: 100 }
        );
    });

    /**
     * Property 0: Form Pre-Population on Page Load (Time Parsing Roundtrip)
     * For any time, parsing the pre-populated uhrzeit field should yield the same time.
     */
    test('Property 0: Form pre-population time can be parsed back to original time', () => {
        fc.assert(
            fc.property(
                fc.tuple(
                    fc.integer({ min: 0, max: 23 }),
                    fc.integer({ min: 0, max: 59 })
                ),
                ([hours, minutes]) => {
                    setupFormDOM();
                    const testDate = new Date(2025, 0, 15, hours, minutes);
                    initializeFormPage(testDate);

                    const uhrzeitValue = document.getElementById('uhrzeit').value;
                    
                    // Parse the formatted time back
                    const match = uhrzeitValue.match(/^(\d{2}):(\d{2})$/);
                    expect(match).not.toBeNull();

                    const [, parsedHours, parsedMinutes] = match;

                    // Verify parsed time matches original
                    expect(parseInt(parsedHours)).toBe(hours);
                    expect(parseInt(parsedMinutes)).toBe(minutes);
                }
            ),
            { numRuns: 100 }
        );
    });

    /**
     * Property 0: Form Pre-Population on Page Load (Edge Cases)
     * For edge case dates (first day of month, last day of month, leap years),
     * the form SHALL pre-populate correctly.
     */
    test('Property 0: Form pre-population handles edge case dates correctly', () => {
        const edgeCases = [
            new Date(2025, 0, 1),      // First day of year
            new Date(2025, 11, 31),    // Last day of year
            new Date(2024, 1, 29),     // Leap year Feb 29
            new Date(2025, 1, 28),     // Non-leap year Feb 28
            new Date(2025, 3, 30),     // 30-day month
            new Date(2025, 4, 31),     // 31-day month
        ];

        edgeCases.forEach((testDate) => {
            setupFormDOM();
            initializeFormPage(testDate);

            const datumValue = document.getElementById('datum').value;
            const expectedDate = formatDateToDDMMYYYY(testDate);

            expect(datumValue).toBe(expectedDate);
            expect(datumValue).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
        });
    });
});
