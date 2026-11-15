/** @jest-environment jsdom */

const {
    formatHparamTimestamp,
    formatHparamValue,
    formatHparamPrev,
    renderHparamRows,
    renderHparamTable,
    loadHparam,
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
