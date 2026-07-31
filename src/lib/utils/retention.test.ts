import { describe, it, expect } from 'vitest';
import { getDaysUntilExpiry, isNearExpiry } from './retention';

// Fixed clock so the tests don't drift. Epoch ms.
const NOW = Date.UTC(2026, 6, 28, 12, 0, 0);
const DAY = 86400;
/** A chat last touched `d` days ago, as epoch SECONDS. */
const updatedDaysAgo = (d: number) => NOW / 1000 - d * DAY;

describe('getDaysUntilExpiry', () => {
	it('counts down from updated_at, not created_at', () => {
		expect(getDaysUntilExpiry(updatedDaysAgo(0), 30, NOW)).toBe(30);
		expect(getDaysUntilExpiry(updatedDaysAgo(25), 30, NOW)).toBe(5);
		expect(getDaysUntilExpiry(updatedDaysAgo(29), 30, NOW)).toBe(1);
	});

	it('goes negative for a chat the sweep has not collected yet', () => {
		expect(getDaysUntilExpiry(updatedDaysAgo(31), 30, NOW)).toBe(-1);
	});

	it('returns null when retention is disabled or the timestamp is missing', () => {
		expect(getDaysUntilExpiry(updatedDaysAgo(10), 0, NOW)).toBeNull();
		expect(getDaysUntilExpiry(updatedDaysAgo(10), null, NOW)).toBeNull();
		expect(getDaysUntilExpiry(updatedDaysAgo(10), -5, NOW)).toBeNull();
		expect(getDaysUntilExpiry(null, 30, NOW)).toBeNull();
		expect(getDaysUntilExpiry(0, 30, NOW)).toBeNull();
		expect(getDaysUntilExpiry(undefined, undefined, NOW)).toBeNull();
	});
});

describe('isNearExpiry', () => {
	it('is false well before the threshold', () => {
		expect(isNearExpiry(updatedDaysAgo(0), 30, 7, NOW)).toBe(false);
		expect(isNearExpiry(updatedDaysAgo(22), 30, 7, NOW)).toBe(false);
	});

	it('is true from the threshold onward, including past due', () => {
		expect(isNearExpiry(updatedDaysAgo(23), 30, 7, NOW)).toBe(true);
		expect(isNearExpiry(updatedDaysAgo(29), 30, 7, NOW)).toBe(true);
		expect(isNearExpiry(updatedDaysAgo(35), 30, 7, NOW)).toBe(true);
	});

	it('is false when retention is off, so the badge never replaces the time-ago label', () => {
		expect(isNearExpiry(updatedDaysAgo(999), 0, 7, NOW)).toBe(false);
	});
});
