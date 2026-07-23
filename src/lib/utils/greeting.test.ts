import { describe, it, expect } from 'vitest';
import { deriveFirstName, getTimeOfDay } from './greeting';

describe('deriveFirstName', () => {
	it('title-cases an ALL-CAPS directory name', () => {
		expect(deriveFirstName('KHAIRUL BIN ABDULLAH')).toBe('Khairul');
	});

	it('keeps a normal first name', () => {
		expect(deriveFirstName('Zack Chong')).toBe('Zack');
	});

	it('lower-cases a shouted single name', () => {
		expect(deriveFirstName('ZACK')).toBe('Zack');
	});

	it('skips leading honorifics', () => {
		expect(deriveFirstName('Dr Tan Wei Ming')).toBe('Tan');
		expect(deriveFirstName('Haji Abdullah')).toBe('Abdullah');
		expect(deriveFirstName('Mr Zack Chong')).toBe('Zack');
	});

	it('keeps the common Chinese-Malaysian surname Tan rather than treating it as a title', () => {
		// "Tan" collides with the award title "Tan Sri" but is far more often a surname; we
		// must not strip it, or we mis-greet a huge slice of the userbase.
		expect(deriveFirstName('Tan Wei Ming')).toBe('Tan');
	});

	it('does not mangle internal capitals', () => {
		expect(deriveFirstName('McArthur Young')).toBe('McArthur');
		expect(deriveFirstName("O'Brien")).toBe("O'Brien");
	});

	it('returns null for email-like or handle values', () => {
		expect(deriveFirstName('khairul.abdullah@sunway.com')).toBeNull();
		expect(deriveFirstName('zack_chong')).toBeNull();
	});

	it('returns null when nothing usable remains', () => {
		expect(deriveFirstName('')).toBeNull();
		expect(deriveFirstName('   ')).toBeNull();
		expect(deriveFirstName(null)).toBeNull();
		expect(deriveFirstName(undefined)).toBeNull();
		expect(deriveFirstName('bin')).toBeNull();
		expect(deriveFirstName('x')).toBeNull();
		expect(deriveFirstName('123')).toBeNull();
	});
});

describe('getTimeOfDay', () => {
	const at = (h: number) => new Date(2026, 6, 21, h, 0, 0);

	it('splits the day into morning / afternoon / evening', () => {
		expect(getTimeOfDay(at(0))).toBe('morning');
		expect(getTimeOfDay(at(8))).toBe('morning');
		expect(getTimeOfDay(at(11))).toBe('morning');
		expect(getTimeOfDay(at(12))).toBe('afternoon');
		expect(getTimeOfDay(at(17))).toBe('afternoon');
		expect(getTimeOfDay(at(18))).toBe('evening');
		expect(getTimeOfDay(at(23))).toBe('evening');
	});
});
