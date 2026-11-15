/** @jest-environment jsdom */

const {
    formatHparamTimestamp,
    formatHparamValue,
    formatHparamPrev,
    renderHparamRows,
    renderHparamTable,
    loadHparam,
    prefillHparamForm,
    validateHparamForm,
    buildHparamPayload,
    handleHparamSubmit,
    __getStateForTests,
    __setAuthenticatedFetchForTests,
    __setConfigForTests,
} = require('./src/app');

const ITEM = {
    event_at: '2026-10-29T07:40',
    created_at: '2026-10-29T07:41',
    komfort: 23,
    normal: 21,
    reduziert: 16,
    neigung: 1.4,
    niveau: 0,
    prev: { neigung: 1.2 },
    source: 'api',
};

function jsonResponse(body, ok = true) {
    return Promise.resolve({ ok, json: () => Promise.resolve(body) });
}

beforeEach(() => {
    document.body.innerHTML = `
        <div id="hparam-content"></div>
        <div id="hparam-more" style="display:none"></div>`;
    const state = __getStateForTests();
    state.hparamNextToken = null;
    state.hparamLoading = false;
    __setConfigForTests({ API_ENDPOINT: 'https://api.test' });
});

describe('hparam formatting', () => {
    test('formats local timestamps as dd.mm.yyyy hh:mm', () => {
        expect(formatHparamTimestamp('2026-10-29T07:40')).toBe('29.10.2026 07:40');
        expect(formatHparamTimestamp('2026-10-29')).toBe('29.10.2026');
        expect(formatHparamTimestamp(undefined)).toBe('—');
    });

    test('formats values with fixed decimals per parameter', () => {
        expect(formatHparamValue('komfort', 23)).toBe('23');
        expect(formatHparamValue('neigung', 1.4)).toBe('1.4');
        expect(formatHparamValue('niveau', 0)).toBe('0.0');
        expect(formatHparamValue('niveau', null)).toBe('—');
    });

    test('formats prev in parameter order and escapes nothing unsafe', () => {
        expect(formatHparamPrev({ niveau: -1, komfort: 22 })).toBe('Komfort 22, Niveau -1.0');
        expect(formatHparamPrev({})).toBe('—');
        expect(formatHparamPrev(undefined)).toBe('—');
    });
});

describe('hparam rendering', () => {
    test('table has prev as second-to-last and source as last column, no PK/SK', () => {
        document.body.innerHTML = renderHparamTable([{ ...ITEM, PK: 'SYSTEM#haus', SK: 'EVT#x' }]);
        const headers = [...document.querySelectorAll('th')].map(th => th.textContent.trim());
        expect(headers.slice(-2)).toEqual(['prev', 'source']);
        expect(headers).not.toContain('PK');
        expect(headers).not.toContain('SK');
        expect(document.body.textContent).not.toContain('SYSTEM#haus');
    });

    test('marks changed parameters from prev keys', () => {
        document.body.innerHTML = `<table><tbody>${renderHparamRows([ITEM])}</tbody></table>`;
        const changed = [...document.querySelectorAll('.hparam-changed')].map(td => td.textContent);
        expect(changed).toEqual(['1.4']);
    });

    test('escapes source to avoid HTML injection', () => {
        const html = renderHparamRows([{ ...ITEM, source: '<img src=x onerror=alert(1)>' }]);
        expect(html).not.toContain('<img');
        expect(html).toContain('&lt;img');
    });
});

describe('loadHparam', () => {
    test('loads first page, requests limit and shows more-button when next_token exists', async () => {
        const fetchMock = jest.fn(() => jsonResponse({ items: [ITEM], count: 1, next_token: 'tok' }));
        __setAuthenticatedFetchForTests(fetchMock);

        await loadHparam();

        expect(fetchMock).toHaveBeenCalledWith('https://api.test/heating/parameters?limit=50');
        expect(document.querySelectorAll('#hparam-tbody tr')).toHaveLength(1);
        expect(document.getElementById('hparam-more').style.display).toBe('flex');
    });

    test('append uses next_token and adds rows without replacing the table', async () => {
        const fetchMock = jest.fn()
            .mockImplementationOnce(() => jsonResponse({ items: [ITEM], count: 1, next_token: 'a/b+c=' }))
            .mockImplementationOnce(() => jsonResponse({ items: [{ ...ITEM, event_at: '2026-10-01T06:00' }], count: 1 }));
        __setAuthenticatedFetchForTests(fetchMock);

        await loadHparam();
        await loadHparam({ append: true });

        expect(fetchMock.mock.calls[1][0]).toBe(
            'https://api.test/heating/parameters?limit=50&next_token=a%2Fb%2Bc%3D'
        );
        expect(document.querySelectorAll('#hparam-tbody tr')).toHaveLength(2);
        expect(document.getElementById('hparam-more').style.display).toBe('none');
    });

    test('shows empty state', async () => {
        __setAuthenticatedFetchForTests(() => jsonResponse({ items: [], count: 0 }));
        await loadHparam();
        expect(document.getElementById('hparam-content').textContent).toContain('No heating parameters found');
    });

    test('shows error state on failure', async () => {
        const spy = jest.spyOn(console, 'error').mockImplementation(() => {});
        __setAuthenticatedFetchForTests(() => jsonResponse({}, false));
        await loadHparam();
        expect(document.getElementById('hparam-content').textContent).toContain('Failed to load heating parameters');
        expect(__getStateForTests().hparamLoading).toBe(false);
        spy.mockRestore();
    });
});


function formHtml() {
    const params = ['komfort', 'normal', 'reduziert', 'neigung', 'niveau'];
    return `
        <div id="hparam-content"></div><div id="hparam-more"></div>
        <form id="hparam-form">
            <input id="hparam-datum"><span id="hparam-datum-error" class="error-message"></span>
            <input id="hparam-uhrzeit"><span id="hparam-uhrzeit-error" class="error-message"></span>
            ${params.map(p => `<input id="hparam-${p}"><span id="hparam-${p}-error" class="error-message"></span>`).join('')}
            <button id="hparam-submit-btn" type="submit"></button>
        </form>
        <div id="hparam-message" class="message"></div>`;
}

const VALUES = {
    datum: '29.10.2026', uhrzeit: '07:40',
    komfort: '23', normal: '21', reduziert: '16', neigung: '1.4', niveau: '0.0',
};
const NOW = new Date(2026, 9, 29, 12, 0);
const fields = errors => errors.map(e => e.field);

describe('validateHparamForm', () => {
    test('accepts plausible values that differ from current', () => {
        expect(validateHparamForm({ ...VALUES, neigung: '1.6' }, ITEM, NOW)).toEqual([]);
    });

    test('accepts comma as decimal separator', () => {
        expect(validateHparamForm({ ...VALUES, neigung: '1,5' }, ITEM, NOW)).toEqual([]);
    });

    test('rejects out of range values', () => {
        const errors = validateHparamForm({ ...VALUES, komfort: '31', neigung: '3.6', niveau: '-10.5' }, ITEM, NOW);
        expect(fields(errors)).toEqual(expect.arrayContaining(['komfort', 'neigung', 'niveau']));
    });

    test('rejects non-integer temperatures and too many decimals', () => {
        const errors = validateHparamForm({ ...VALUES, normal: '21.5', neigung: '1.45' }, ITEM, NOW);
        expect(fields(errors)).toEqual(expect.arrayContaining(['normal', 'neigung']));
    });

    test('rejects empty and non-numeric input', () => {
        const errors = validateHparamForm({ ...VALUES, komfort: '', reduziert: 'abc' }, ITEM, NOW);
        expect(fields(errors)).toEqual(expect.arrayContaining(['komfort', 'reduziert']));
    });

    test('rejects reduziert > normal and normal > komfort', () => {
        const a = validateHparamForm({ ...VALUES, reduziert: '22' }, ITEM, NOW);
        expect(a).toEqual([expect.objectContaining({ field: 'reduziert' })]);
        const b = validateHparamForm({ ...VALUES, normal: '24', reduziert: '16' }, ITEM, NOW);
        expect(b).toEqual([expect.objectContaining({ field: 'normal' })]);
    });

    test('rejects invalid and future date/time', () => {
        expect(fields(validateHparamForm({ ...VALUES, datum: '31.02.2026' }, ITEM, NOW))).toContain('datum');
        expect(fields(validateHparamForm({ ...VALUES, uhrzeit: '25:00' }, ITEM, NOW))).toContain('uhrzeit');
        expect(fields(validateHparamForm({ ...VALUES, datum: '05.11.2026' }, ITEM, NOW))).toContain('datum');
    });

    test('requires at least one change versus current values', () => {
        const same = { ...VALUES, neigung: '1.4', niveau: '0', komfort: '23', normal: '21', reduziert: '16' };
        expect(validateHparamForm(same, ITEM, NOW)).toEqual([expect.objectContaining({ field: 'form' })]);
    });

    test('does not require a change when there is no current entry', () => {
        expect(validateHparamForm(VALUES, null, NOW)).toEqual([]);
    });
});

describe('hparam form', () => {
    beforeEach(() => {
        document.body.innerHTML = formHtml();
        const state = __getStateForTests();
        state.hparamCurrent = null;
        state.hparamSubmitting = false;
        state.hparamNextToken = null;
        state.hparamLoading = false;
    });

    test('prefills parameters from current values and date/time with now', () => {
        __getStateForTests().hparamCurrent = ITEM;
        prefillHparamForm();
        expect(document.getElementById('hparam-komfort').value).toBe('23');
        expect(document.getElementById('hparam-neigung').value).toBe('1.4');
        expect(document.getElementById('hparam-niveau').value).toBe('0.0');
        expect(document.getElementById('hparam-datum').value).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
        expect(document.getElementById('hparam-uhrzeit').value).toMatch(/^\d{2}:\d{2}$/);
    });

    test('loadHparam prefills the form from the newest entry', async () => {
        __setAuthenticatedFetchForTests(() => jsonResponse({ items: [ITEM, { ...ITEM, komfort: 20 }], count: 2 }));
        await loadHparam();
        expect(document.getElementById('hparam-komfort').value).toBe('23');
    });

    test('buildHparamPayload converts to event_at and numbers', () => {
        expect(buildHparamPayload({ ...VALUES, neigung: '1,5' })).toEqual({
            event_at: '2026-10-29T07:40', komfort: 23, normal: 21, reduziert: 16, neigung: 1.5, niveau: 0,
        });
    });

    function fillForm(overrides = {}) {
        Object.entries({ ...VALUES, ...overrides }).forEach(([k, v]) => {
            document.getElementById(`hparam-${k}`).value = v;
        });
    }

    test('submit posts payload, shows success and reloads table', async () => {
        __getStateForTests().hparamCurrent = ITEM;
        const fetchMock = jest.fn()
            .mockImplementationOnce(() => jsonResponse({ status: 'created', item: ITEM }))
            .mockImplementationOnce(() => jsonResponse({ items: [ITEM], count: 1 }));
        __setAuthenticatedFetchForTests(fetchMock);
        fillForm({ neigung: '1.6' });
        // Date in the past relative to real clock, so future check passes
        await handleHparamSubmit({ preventDefault() {} });

        const [url, opts] = fetchMock.mock.calls[0];
        expect(url).toBe('https://api.test/heating/parameters');
        expect(opts.method).toBe('POST');
        expect(JSON.parse(opts.body)).toMatchObject({ neigung: 1.6, event_at: '2026-10-29T07:40' });
        expect(fetchMock).toHaveBeenCalledTimes(2); // POST + table reload
        expect(document.getElementById('hparam-message').textContent).toBe('Submission successful!');
        expect(document.getElementById('hparam-message').classList.contains('success')).toBe(true);
        expect(document.getElementById('hparam-submit-btn').disabled).toBe(false);
    });

    test('invalid input shows field errors and sends nothing', async () => {
        __getStateForTests().hparamCurrent = ITEM;
        const fetchMock = jest.fn();
        __setAuthenticatedFetchForTests(fetchMock);
        fillForm({ reduziert: '25' });
        await handleHparamSubmit({ preventDefault() {} });

        expect(fetchMock).not.toHaveBeenCalled();
        expect(document.getElementById('hparam-reduziert-error').textContent).toContain('must not exceed Normal');
        expect(document.getElementById('hparam-reduziert').classList.contains('error')).toBe(true);
    });

    test('server error message is displayed', async () => {
        __getStateForTests().hparamCurrent = ITEM;
        __setAuthenticatedFetchForTests(() => jsonResponse({ error: 'Plausibilität verletzt' }, false));
        fillForm({ neigung: '1.6' });
        await handleHparamSubmit({ preventDefault() {} });
        expect(document.getElementById('hparam-message').textContent).toBe('Plausibilität verletzt');
        expect(document.getElementById('hparam-message').classList.contains('error')).toBe(true);
    });

    test('unchanged response is reported as no change', async () => {
        __getStateForTests().hparamCurrent = ITEM;
        __setAuthenticatedFetchForTests(() => jsonResponse({ status: 'unchanged', state: {} }));
        fillForm({ neigung: '1.6' });
        await handleHparamSubmit({ preventDefault() {} });
        expect(document.getElementById('hparam-message').textContent).toContain('No change');
    });
});
