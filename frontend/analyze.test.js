const {
  parseGermanDateToUtcMidnight,
  computeYtdTotals,
  computeWeeklyPeakStats,
  computeWeeklyMinimumStats,
  getIsoWeekPartsFromUtcDate,
  formatIsoWeekDdMmRange,
} = require('./src/app.js');

describe('Analyze helpers', () => {
  describe('parseGermanDateToUtcMidnight', () => {
    test('parses dd.mm.yyyy into a UTC-midnight Date', () => {
      const d = parseGermanDateToUtcMidnight('01.01.2025');
      expect(d).toBeInstanceOf(Date);
      expect(d.toISOString()).toBe('2025-01-01T00:00:00.000Z');
    });

    test('returns null for invalid dates', () => {
      expect(parseGermanDateToUtcMidnight('32.01.2025')).toBeNull();
      expect(parseGermanDateToUtcMidnight('01.13.2025')).toBeNull();
      expect(parseGermanDateToUtcMidnight('not-a-date')).toBeNull();
      expect(parseGermanDateToUtcMidnight(null)).toBeNull();
    });
  });

  describe('computeYtdTotals', () => {
    test('computes hours/starts as latest - earliest, consumption as SUM across entries, and inclusive day count', () => {
      const earliest = {
        datum: '01.01.2025',
        betriebsstunden: 100,
        starts: 10,
        verbrauch_qm: 5.0,
      };
      const middle = {
        datum: '02.01.2025',
        betriebsstunden: 120,
        starts: 12,
        verbrauch_qm: 6.0,
      };
      const latest = {
        datum: '03.01.2025',
        betriebsstunden: 150,
        starts: 15,
        verbrauch_qm: 7.5,
      };

      const stats = computeYtdTotals(earliest, latest, [earliest, middle, latest]);
      expect(stats).not.toBeNull();
      expect(stats.totalOperatingHours).toBe(50);
      expect(stats.totalStarts).toBe(5);
      expect(stats.totalConsumption).toBeCloseTo(18.5, 10);
      expect(stats.days).toBe(3);
    });

    test('uses timestamp_utc as fallback when datum is missing/invalid', () => {
      const earliest = {
        datum: 'invalid',
        timestamp_utc: '2025-01-01T12:34:56.000Z',
        betriebsstunden: '100',
        starts: '10',
        verbrauch_qm: '5,0',
      };
      const latest = {
        datum: '',
        timestamp_utc: '2025-01-02T00:01:00.000Z',
        betriebsstunden: '101',
        starts: '11',
        verbrauch_qm: '5.5',
      };

      const stats = computeYtdTotals(earliest, latest, [earliest, latest]);
      expect(stats).not.toBeNull();
      expect(stats.totalOperatingHours).toBe(1);
      expect(stats.totalStarts).toBe(1);
      expect(stats.totalConsumption).toBeCloseTo(10.5, 10);
      expect(stats.days).toBe(2);
    });
  });

  describe('getIsoWeekPartsFromUtcDate', () => {
    test('matches ISO week for known UTC calendar days', () => {
      expect(getIsoWeekPartsFromUtcDate(new Date(Date.UTC(2015, 0, 1)))).toEqual({
        isoWeekYear: 2015,
        isoWeek: 1,
      });
      expect(getIsoWeekPartsFromUtcDate(new Date(Date.UTC(2005, 0, 1)))).toEqual({
        isoWeekYear: 2004,
        isoWeek: 53,
      });
    });
  });

  describe('computeWeeklyPeakStats', () => {
    test('aggregates by ISO week; peak week is max consumption; hours/starts match that week', () => {
      const w1a = {
        datum: '01.01.2025',
        delta_betriebsstunden: 10,
        delta_starts: 2,
        verbrauch_qm: 1.0,
      };
      const w1b = {
        datum: '02.01.2025',
        delta_betriebsstunden: 5,
        delta_starts: 1,
        verbrauch_qm: 2.0,
      };
      const w2 = {
        datum: '08.01.2025',
        delta_betriebsstunden: 30,
        delta_starts: 1,
        verbrauch_qm: 1.0,
      };
      const sorted = [w1a, w1b, w2];
      const peaks = computeWeeklyPeakStats(sorted);
      expect(peaks.consumptionPeakTied).toBe(false);
      expect(peaks.peakVerbrauchQm).toEqual({
        sum: 3,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
      expect(peaks.peakBetriebsstunden).toEqual({
        sum: 15,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
      expect(peaks.peakStarts).toEqual({
        sum: 3,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
      expect(peaks.peakVorlaufTemp).toBeNull();
      expect(peaks.peakOutsideTemp).toBeNull();
    });

    test('on equal consumption across weeks picks lexicographically earlier week and sets consumptionPeakTied', () => {
      const earlierWeek = {
        datum: '10.02.2025',
        delta_betriebsstunden: 5,
        delta_starts: 0,
        verbrauch_qm: 1,
      };
      const laterWeek = {
        datum: '17.02.2025',
        delta_betriebsstunden: 5,
        delta_starts: 0,
        verbrauch_qm: 1,
      };
      const peaks = computeWeeklyPeakStats([laterWeek, earlierWeek]);
      expect(peaks.consumptionPeakTied).toBe(true);
      expect(peaks.peakBetriebsstunden).toEqual({
        sum: 5,
        isoWeekYear: 2025,
        isoWeek: 7,
      });
      expect(peaks.peakStarts).toEqual({
        sum: 0,
        isoWeekYear: 2025,
        isoWeek: 7,
      });
      expect(peaks.peakVerbrauchQm).toEqual({
        sum: 1,
        isoWeekYear: 2025,
        isoWeek: 7,
      });
      expect(peaks.peakVorlaufTemp).toBeNull();
      expect(peaks.peakOutsideTemp).toBeNull();
    });

    test('empty submissions array returns null peaks for all metrics', () => {
      expect(computeWeeklyPeakStats([])).toEqual({
        peakBetriebsstunden: null,
        peakStarts: null,
        peakVerbrauchQm: null,
        peakVorlaufTemp: null,
        peakOutsideTemp: null,
        consumptionPeakTied: false,
      });
    });

    test('skips invalid datum and still aggregates valid rows', () => {
      const valid = {
        datum: '01.01.2025',
        delta_betriebsstunden: 7,
        delta_starts: 2,
        verbrauch_qm: 3,
      };
      const peaks = computeWeeklyPeakStats([
        { datum: 'not-a-date', delta_betriebsstunden: 99 },
        valid,
        { datum: '', verbrauch_qm: 50 },
      ]);
      expect(peaks.peakBetriebsstunden).toEqual({
        sum: 7,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
      expect(peaks.peakStarts).toEqual({
        sum: 2,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
      expect(peaks.peakVerbrauchQm).toEqual({
        sum: 3,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
      expect(peaks.peakVorlaufTemp).toBeNull();
      expect(peaks.peakOutsideTemp).toBeNull();
      expect(peaks.consumptionPeakTied).toBe(false);
    });

    test('equal weekly sums across ISO week years: picks lexicographically earlier week', () => {
      const dEarlier = parseGermanDateToUtcMidnight('15.12.2025');
      const dLater = parseGermanDateToUtcMidnight('29.12.2025');
      const pEarlier = getIsoWeekPartsFromUtcDate(dEarlier);
      const pLater = getIsoWeekPartsFromUtcDate(dLater);
      const lexEarlier =
        pEarlier.isoWeekYear < pLater.isoWeekYear ||
        (pEarlier.isoWeekYear === pLater.isoWeekYear && pEarlier.isoWeek < pLater.isoWeek);
      expect(lexEarlier).toBe(true);

      const rowEarlier = {
        datum: '15.12.2025',
        delta_betriebsstunden: 4,
        delta_starts: 2,
        verbrauch_qm: 1.25,
      };
      const rowLater = {
        datum: '29.12.2025',
        delta_betriebsstunden: 4,
        delta_starts: 2,
        verbrauch_qm: 1.25,
      };
      const peaks = computeWeeklyPeakStats([rowLater, rowEarlier]);
      expect(peaks.consumptionPeakTied).toBe(true);
      expect(peaks.peakBetriebsstunden).toEqual({
        sum: 4,
        isoWeekYear: pEarlier.isoWeekYear,
        isoWeek: pEarlier.isoWeek,
      });
      expect(peaks.peakStarts).toEqual({
        sum: 2,
        isoWeekYear: pEarlier.isoWeekYear,
        isoWeek: pEarlier.isoWeek,
      });
      expect(peaks.peakVerbrauchQm).toEqual({
        sum: 1.25,
        isoWeekYear: pEarlier.isoWeekYear,
        isoWeek: pEarlier.isoWeek,
      });
      expect(peaks.peakVorlaufTemp).toBeNull();
      expect(peaks.peakOutsideTemp).toBeNull();
    });

    test('returns null peaks when no valid calendar day', () => {
      expect(
        computeWeeklyPeakStats([{ datum: 'invalid', delta_betriebsstunden: 1 }])
      ).toEqual({
        peakBetriebsstunden: null,
        peakStarts: null,
        peakVerbrauchQm: null,
        peakVorlaufTemp: null,
        peakOutsideTemp: null,
        consumptionPeakTied: false,
      });
    });

    test('averages vorlauf_temp and aussentemp readings within peak consumption ISO week', () => {
      const a = {
        datum: '01.01.2025',
        delta_betriebsstunden: 0,
        delta_starts: 0,
        verbrauch_qm: 1,
        vorlauf_temp: 40,
        aussentemp: 10,
      };
      const b = {
        datum: '02.01.2025',
        delta_betriebsstunden: 0,
        delta_starts: 0,
        verbrauch_qm: 10,
        vorlauf_temp: 42,
        aussentemp: 7,
      };
      const peaks = computeWeeklyPeakStats([a, b]);
      expect(peaks.peakVorlaufTemp).toEqual({
        mean: 41,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
      expect(peaks.peakOutsideTemp).toEqual({
        mean: 8.5,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
    });

    test('null peak temperature metrics when peak week has no temperature readings', () => {
      const w1a = {
        datum: '01.01.2025',
        verbrauch_qm: 1,
        vorlauf_temp: 40,
        aussentemp: 5,
      };
      const w1b = {
        datum: '02.01.2025',
        verbrauch_qm: 1,
        vorlauf_temp: 41,
        aussentemp: 6,
      };
      const w2a = {
        datum: '08.01.2025',
        verbrauch_qm: 10,
      };
      const w2b = {
        datum: '09.01.2025',
        verbrauch_qm: 5,
      };
      const peaks = computeWeeklyPeakStats([w1a, w1b, w2a, w2b]);
      expect(peaks.peakVerbrauchQm && peaks.peakVerbrauchQm.isoWeek).toBeGreaterThan(1);
      expect(peaks.peakVorlaufTemp).toBeNull();
      expect(peaks.peakOutsideTemp).toBeNull();
    });
  });

  describe('computeWeeklyMinimumStats', () => {
    test('aggregates by ISO week; minimum week is min consumption; hours/starts match that week', () => {
      const w1a = {
        datum: '01.01.2025',
        delta_betriebsstunden: 10,
        delta_starts: 2,
        verbrauch_qm: 1.0,
      };
      const w1b = {
        datum: '02.01.2025',
        delta_betriebsstunden: 5,
        delta_starts: 1,
        verbrauch_qm: 2.0,
      };
      const w2 = {
        datum: '08.01.2025',
        delta_betriebsstunden: 30,
        delta_starts: 1,
        verbrauch_qm: 1.0,
      };
      const sorted = [w1a, w1b, w2];
      const mins = computeWeeklyMinimumStats(sorted);
      expect(mins.consumptionMinimumTied).toBe(false);
      expect(mins.minVerbrauchQm).toEqual({
        sum: 1,
        isoWeekYear: 2025,
        isoWeek: 2,
      });
      expect(mins.minBetriebsstunden).toEqual({
        sum: 30,
        isoWeekYear: 2025,
        isoWeek: 2,
      });
      expect(mins.minStarts).toEqual({
        sum: 1,
        isoWeekYear: 2025,
        isoWeek: 2,
      });
      expect(mins.minVorlaufTemp).toBeNull();
      expect(mins.minOutsideTemp).toBeNull();
    });

    test('on equal consumption across weeks picks lexicographically earlier week and sets consumptionMinimumTied', () => {
      const earlierWeek = {
        datum: '10.02.2025',
        delta_betriebsstunden: 5,
        delta_starts: 0,
        verbrauch_qm: 1,
      };
      const laterWeek = {
        datum: '17.02.2025',
        delta_betriebsstunden: 5,
        delta_starts: 0,
        verbrauch_qm: 1,
      };
      const mins = computeWeeklyMinimumStats([laterWeek, earlierWeek]);
      expect(mins.consumptionMinimumTied).toBe(true);
      expect(mins.minBetriebsstunden).toEqual({
        sum: 5,
        isoWeekYear: 2025,
        isoWeek: 7,
      });
      expect(mins.minStarts).toEqual({
        sum: 0,
        isoWeekYear: 2025,
        isoWeek: 7,
      });
      expect(mins.minVerbrauchQm).toEqual({
        sum: 1,
        isoWeekYear: 2025,
        isoWeek: 7,
      });
      expect(mins.minVorlaufTemp).toBeNull();
      expect(mins.minOutsideTemp).toBeNull();
    });

    test('empty submissions array returns null mins for all metrics', () => {
      expect(computeWeeklyMinimumStats([])).toEqual({
        minBetriebsstunden: null,
        minStarts: null,
        minVerbrauchQm: null,
        minVorlaufTemp: null,
        minOutsideTemp: null,
        consumptionMinimumTied: false,
      });
    });

    test('equal weekly sums across ISO week years: picks lexicographically earlier week', () => {
      const rowEarlier = {
        datum: '15.12.2025',
        delta_betriebsstunden: 4,
        delta_starts: 2,
        verbrauch_qm: 1.25,
      };
      const rowLater = {
        datum: '29.12.2025',
        delta_betriebsstunden: 4,
        delta_starts: 2,
        verbrauch_qm: 1.25,
      };
      const dEarlier = parseGermanDateToUtcMidnight('15.12.2025');
      const pEarlier = getIsoWeekPartsFromUtcDate(dEarlier);
      const mins = computeWeeklyMinimumStats([rowLater, rowEarlier]);
      expect(mins.consumptionMinimumTied).toBe(true);
      expect(mins.minVerbrauchQm).toEqual({
        sum: 1.25,
        isoWeekYear: pEarlier.isoWeekYear,
        isoWeek: pEarlier.isoWeek,
      });
    });

    test('averages vorlauf_temp and aussentemp in the minimum-consumption ISO week', () => {
      const lowA = {
        datum: '01.01.2025',
        delta_betriebsstunden: 0,
        delta_starts: 0,
        verbrauch_qm: 1,
        vorlauf_temp: 40,
        aussentemp: 10,
      };
      const lowB = {
        datum: '02.01.2025',
        delta_betriebsstunden: 0,
        delta_starts: 0,
        verbrauch_qm: 1,
        vorlauf_temp: 41,
        aussentemp: 9,
      };
      const highA = {
        datum: '08.01.2025',
        delta_betriebsstunden: 0,
        delta_starts: 0,
        verbrauch_qm: 20,
      };
      const highB = {
        datum: '09.01.2025',
        delta_betriebsstunden: 0,
        delta_starts: 0,
        verbrauch_qm: 30,
      };
      const mins = computeWeeklyMinimumStats([lowA, lowB, highA, highB]);
      expect(mins.minVerbrauchQm && mins.minVerbrauchQm.isoWeek).toBe(1);
      expect(mins.minVorlaufTemp).toEqual({
        mean: 40.5,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
      expect(mins.minOutsideTemp).toEqual({
        mean: 9.5,
        isoWeekYear: 2025,
        isoWeek: 1,
      });
    });

    test('excludes the current UTC ISO week so partial-week data is not the minimum', () => {
      jest.useFakeTimers();
      jest.setSystemTime(new Date(Date.UTC(2025, 0, 15, 12, 0, 0)));
      try {
        const priorWeek = {
          datum: '08.01.2025',
          delta_betriebsstunden: 10,
          delta_starts: 2,
          verbrauch_qm: 100,
        };
        const currentWeekLow = {
          datum: '14.01.2025',
          delta_betriebsstunden: 1,
          delta_starts: 1,
          verbrauch_qm: 1,
        };
        const mins = computeWeeklyMinimumStats([priorWeek, currentWeekLow]);
        expect(mins.minVerbrauchQm).toEqual({
          sum: 100,
          isoWeekYear: 2025,
          isoWeek: 2,
        });
        expect(mins.minBetriebsstunden).toEqual({
          sum: 10,
          isoWeekYear: 2025,
          isoWeek: 2,
        });
      } finally {
        jest.useRealTimers();
      }
    });

    test('returns empty minimum stats when only the current UTC ISO week has data', () => {
      jest.useFakeTimers();
      jest.setSystemTime(new Date(Date.UTC(2025, 0, 15, 12, 0, 0)));
      try {
        expect(
          computeWeeklyMinimumStats([
            {
              datum: '14.01.2025',
              delta_betriebsstunden: 1,
              delta_starts: 1,
              verbrauch_qm: 5,
            },
          ]),
        ).toEqual({
          minBetriebsstunden: null,
          minStarts: null,
          minVerbrauchQm: null,
          minVorlaufTemp: null,
          minOutsideTemp: null,
          consumptionMinimumTied: false,
        });
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe('formatIsoWeekDdMmRange', () => {
    test('formats ISO week 1 of 2015 as Monday–Sunday dd.mm-dd.mm without year', () => {
      expect(formatIsoWeekDdMmRange(2015, 1)).toBe('29.12-04.01');
    });
  });
});


