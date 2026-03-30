/** @jest-environment jsdom */

const {
    normalizeSettingsConfig,
    normalizeSettingsSchedulerMetadata,
    validateSettingsPayload,
    renderSettingsSchedulerMetadata,
    loadSettings,
    __setAuthenticatedFetchForTests,
    __setConfigForTests,
} = require('./src/app');

describe('settings payload validation', () => {
    test('accepts a valid payload', () => {
        const payload = {
            schemaVersion: 1,
            frequentActiveWindows: [{ start: '08:00', stop: '12:00' }],
            maxRetries: 3,
            retryDelaySeconds: 300,
            userId: '123e4567-e89b-12d3-a456-426614174000',
        };

        expect(validateSettingsPayload(payload)).toEqual([]);
    });

    test('rejects invalid UUID format', () => {
        const payload = {
            schemaVersion: 1,
            frequentActiveWindows: [{ start: '08:00', stop: '12:00' }],
            maxRetries: 3,
            retryDelaySeconds: 300,
            userId: 'operator-user',
        };

        expect(validateSettingsPayload(payload)).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    field: 'settings-user-id-error',
                    message: expect.stringContaining('valid UUID'),
                }),
            ])
        );
    });

    test('rejects windows where start is not earlier than stop', () => {
        const payload = {
            schemaVersion: 1,
            frequentActiveWindows: [{ start: '12:00', stop: '12:00' }],
            maxRetries: 3,
            retryDelaySeconds: 300,
            userId: '123e4567-e89b-12d3-a456-426614174000',
        };

        expect(validateSettingsPayload(payload)).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    field: 'settings-active-windows-error',
                    message: expect.stringContaining('start must be earlier than stop'),
                }),
            ])
        );
    });

    test('rejects more than five active windows', () => {
        const payload = {
            schemaVersion: 1,
            frequentActiveWindows: [
                { start: '00:00', stop: '01:00' },
                { start: '01:00', stop: '02:00' },
                { start: '02:00', stop: '03:00' },
                { start: '03:00', stop: '04:00' },
                { start: '04:00', stop: '05:00' },
                { start: '05:00', stop: '06:00' },
            ],
            maxRetries: 3,
            retryDelaySeconds: 300,
            userId: '123e4567-e89b-12d3-a456-426614174000',
        };

        expect(validateSettingsPayload(payload)).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    field: 'settings-active-windows-error',
                    message: expect.stringContaining('No more than 5 active windows'),
                }),
            ])
        );
    });
});

describe('normalizeSettingsSchedulerMetadata', () => {
    test('applies daily defaults when payload is missing', () => {
        const normalized = normalizeSettingsSchedulerMetadata(null);
        expect(normalized.dailyAvailable).toBe(false);
        expect(normalized.dailySource).toBe('scheduler');
        expect(normalized.dailyScheduleCron).toBe(null);
        expect(normalized.dailyScheduleTimezone).toBe(null);
    });

    test('accepts valid daily fields from API shape', () => {
        const normalized = normalizeSettingsSchedulerMetadata({
            dailyAvailable: true,
            dailyScheduleCron: '0 7 * * ? *',
            dailyScheduleTimezone: 'Europe/Berlin',
            dailyScheduleName: 'heating-auto-retrieval-dev',
            dailyScheduleGroupName: 'default',
            dailyState: 'ENABLED',
        });
        expect(normalized.dailyAvailable).toBe(true);
        expect(normalized.dailyScheduleCron).toBe('0 7 * * ? *');
        expect(normalized.dailyScheduleTimezone).toBe('Europe/Berlin');
    });
});

describe('settings config normalization', () => {
    test('uses fallback user id and default window when missing', () => {
        const normalized = normalizeSettingsConfig(
            {
                schemaVersion: 1,
                maxRetries: 4,
                retryDelaySeconds: 600,
                frequentActiveWindows: [],
            },
            '123e4567-e89b-12d3-a456-426614174000'
        );

        expect(normalized.userId).toBe('123e4567-e89b-12d3-a456-426614174000');
        expect(normalized.frequentActiveWindows).toEqual([{ start: '08:00', stop: '18:00' }]);
    });

    test('keeps only first five windows', () => {
        const normalized = normalizeSettingsConfig({
            schemaVersion: 1,
            maxRetries: 4,
            retryDelaySeconds: 600,
            userId: '123e4567-e89b-12d3-a456-426614174000',
            frequentActiveWindows: [
                { start: '00:00', stop: '01:00' },
                { start: '01:00', stop: '02:00' },
                { start: '02:00', stop: '03:00' },
                { start: '03:00', stop: '04:00' },
                { start: '04:00', stop: '05:00' },
                { start: '05:00', stop: '06:00' },
            ],
        });

        expect(normalized.frequentActiveWindows).toHaveLength(5);
        expect(normalized.frequentActiveWindows[4]).toEqual({ start: '04:00', stop: '05:00' });
    });
});

function renderSchedulerFixture() {
    document.body.innerHTML = `
        <div id="settings-page">
            <span id="settings-scheduler-frequent-cron"></span>
            <span id="settings-scheduler-frequent-interval"></span>
            <p id="settings-scheduler-note"></p>
            <span id="settings-scheduler-daily-cron"></span>
            <span id="settings-scheduler-daily-timezone"></span>
            <p id="settings-scheduler-daily-note"></p>
            <div id="settings-message"></div>
        </div>
    `;
}

describe('settings scheduler metadata rendering', () => {
    beforeEach(() => {
        renderSchedulerFixture();
    });

    test('renders complete scheduler metadata values', () => {
        renderSettingsSchedulerMetadata({
            available: true,
            source: 'eventbridge',
            frequentScheduleCron: '0/15 * * * ? *',
            frequentScheduleExpression: 'cron(0/15 * * * ? *)',
            frequentIntervalMinutes: 15,
            frequentRuleName: 'heating-auto-retrieval-frequent-dev',
        });

        expect(document.getElementById('settings-scheduler-frequent-cron').textContent).toBe('0/15 * * * ? *');
        expect(document.getElementById('settings-scheduler-frequent-interval').textContent).toBe('15 minutes');
        expect(document.getElementById('settings-scheduler-note').textContent).toBe(
            'Source: eventbridge (available, rule heating-auto-retrieval-frequent-dev)'
        );
        expect(document.getElementById('settings-scheduler-daily-cron').textContent).toBe('Not available');
        expect(document.getElementById('settings-scheduler-daily-timezone').textContent).toBe('Not available');
        expect(document.getElementById('settings-scheduler-daily-note').textContent).toBe('Source: scheduler (unavailable)');
    });

    test('renders daily scheduler metadata when present', () => {
        renderSettingsSchedulerMetadata({
            available: true,
            source: 'eventbridge',
            frequentScheduleCron: '0/15 * * * ? *',
            frequentIntervalMinutes: 15,
            frequentRuleName: 'heating-auto-retrieval-frequent-dev',
            dailyAvailable: true,
            dailySource: 'scheduler',
            dailyScheduleCron: '0 7 * * ? *',
            dailyScheduleTimezone: 'Europe/Berlin',
            dailyScheduleName: 'heating-auto-retrieval-dev',
            dailyScheduleGroupName: 'default',
            dailyState: 'ENABLED',
        });

        expect(document.getElementById('settings-scheduler-daily-cron').textContent).toBe('0 7 * * ? *');
        expect(document.getElementById('settings-scheduler-daily-timezone').textContent).toBe('Europe/Berlin');
        expect(document.getElementById('settings-scheduler-daily-note').textContent).toBe(
            'Source: scheduler (available, schedule heating-auto-retrieval-dev, group default, state ENABLED)'
        );
    });

    test('renders placeholders for malformed scheduler metadata', () => {
        renderSettingsSchedulerMetadata({
            available: 'yes',
            source: '   ',
            frequentScheduleCron: 123,
            frequentScheduleExpression: [],
            frequentIntervalMinutes: 'nope',
            frequentRuleName: 7,
        });

        expect(document.getElementById('settings-scheduler-frequent-cron').textContent).toBe('Not available');
        expect(document.getElementById('settings-scheduler-frequent-interval').textContent).toBe('Not available');
        expect(document.getElementById('settings-scheduler-note').textContent).toBe('Source: eventbridge (unavailable)');
        expect(document.getElementById('settings-scheduler-daily-cron').textContent).toBe('Not available');
        expect(document.getElementById('settings-scheduler-daily-timezone').textContent).toBe('Not available');
        expect(document.getElementById('settings-scheduler-daily-note').textContent).toBe('Source: scheduler (unavailable)');
    });

    test('loadSettings keeps scheduler placeholders when metadata fetch fails', async () => {
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
        try {
            __setConfigForTests({ API_ENDPOINT: 'http://example.test' });
            __setAuthenticatedFetchForTests(async () => {
                throw new Error('network down');
            });
            renderSettingsSchedulerMetadata({
                available: true,
                source: 'eventbridge',
                frequentScheduleCron: '0/30 * * * ? *',
                frequentIntervalMinutes: 30,
                frequentRuleName: 'rule-a',
            });

            await loadSettings();

            expect(document.getElementById('settings-scheduler-frequent-cron').textContent).toBe('Not available');
            expect(document.getElementById('settings-scheduler-frequent-interval').textContent).toBe('Not available');
            expect(document.getElementById('settings-scheduler-note').textContent).toBe('Source: eventbridge (unavailable)');
            expect(document.getElementById('settings-scheduler-daily-cron').textContent).toBe('Not available');
            expect(document.getElementById('settings-scheduler-daily-timezone').textContent).toBe('Not available');
            expect(document.getElementById('settings-scheduler-daily-note').textContent).toBe('Source: scheduler (unavailable)');
            expect(document.getElementById('settings-message').textContent).toBe('network down');
            expect(document.getElementById('settings-message').classList.contains('error')).toBe(true);
        } finally {
            consoleErrorSpy.mockRestore();
        }
    });
});
