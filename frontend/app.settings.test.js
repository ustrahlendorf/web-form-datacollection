/** @jest-environment jsdom */

const {
    normalizeSettingsConfig,
    validateSettingsPayload,
} = require('./app');

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
